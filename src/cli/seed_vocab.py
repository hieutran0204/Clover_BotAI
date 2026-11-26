"""
name: seed_vocab
description: CLI script to seed ground-truth vocabulary into PostgreSQL from structured/raw JSON/CSV files or AI-generated topic batches.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence

from src.core.config import get_settings
from src.db.session import get_db_session
from src.schemas.vocab import VocabSchema
from src.services.ai.chat_service import AIChatService
from src.services.ai.embedding_service import EmbeddingService
from src.services.redis_service import RedisService
from src.services.vocab_ingestion_service import IngestionReport, VocabIngestionService

logger = logging.getLogger(__name__)

ENRICH_CHUNK_SIZE = 10


def _parse_quiz_options(raw_value: Any) -> List[str]:
    """
    Parse quiz options from either a list, a JSON string, or a pipe-delimited string.

    Args:
        raw_value: Raw field value from CSV or JSON input.

    Returns:
        List of option strings (four items when validly formatted).
    """
    if isinstance(raw_value, list):
        return [str(option).strip() for option in raw_value if str(option).strip()]

    text = str(raw_value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        return [str(option).strip() for option in parsed if str(option).strip()]
    return [part.strip() for part in text.split("|") if part.strip()]


def _has_structured_fields(row: dict[str, Any]) -> bool:
    """
    Check whether a dictionary contains complete VocabSchema fields without requiring LLM enrichment.

    Args:
        row: Input mapping parsed from JSON or CSV.

    Returns:
        True if required structured fields are non-empty.
    """
    required_keys = (
        "word",
        "definition_vi",
        "definition_en",
        "example_sentence",
        "quiz_question",
        "quiz_options",
    )
    return all(bool(str(row.get(k, "")).strip()) for k in required_keys)


def _row_to_vocab_schema(row: dict[str, Any]) -> VocabSchema:
    """
    Convert a structured dictionary row into a validated VocabSchema instance.

    Args:
        row: Dictionary containing full vocabulary fields.

    Returns:
        Validated VocabSchema instance.
    """
    options = _parse_quiz_options(row["quiz_options"])
    return VocabSchema(
        word=str(row["word"]).strip(),
        phonetic=str(row.get("phonetic") or "").strip(),
        part_of_speech=str(row.get("part_of_speech") or "noun").strip(),
        definition_vi=str(row["definition_vi"]).strip(),
        definition_en=str(row["definition_en"]).strip(),
        example_sentence=str(row["example_sentence"]).strip(),
        example_translation=str(row.get("example_translation") or "").strip(),
        cefr_level=str(row.get("cefr_level") or "B2").strip(),
        quiz_question=str(row["quiz_question"]).strip(),
        quiz_options=options,
        quiz_correct_index=int(row.get("quiz_correct_index", 0)),
    )


def parse_seed_file(file_path: Path) -> tuple[List[VocabSchema], List[str]]:
    """
    Load a JSON or CSV seed file and split records into pre-structured VocabSchema items
    and raw word strings that still require LLM enrichment.

    Args:
        file_path: Path to a `.json` or `.csv` file.

    Returns:
        Tuple `(structured_items, raw_words)`.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Seed file not found: {file_path}")

    suffix = file_path.suffix.lower()
    structured: List[VocabSchema] = []
    raw_words: List[str] = []

    if suffix == ".json":
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            entries = payload.get("items") or payload.get("words") or []
        elif isinstance(payload, list):
            entries = payload
        else:
            raise ValueError("JSON seed root must be a list or an object with 'items'/'words'.")

        for entry in entries:
            if isinstance(entry, str):
                word = entry.strip()
                if word:
                    raw_words.append(word)
            elif isinstance(entry, dict):
                if _has_structured_fields(entry):
                    structured.append(_row_to_vocab_schema(entry))
                elif entry.get("word"):
                    raw_words.append(str(entry["word"]).strip())
                else:
                    raise ValueError(f"Invalid JSON vocabulary entry: {entry}")
            else:
                raise ValueError(f"Unsupported JSON entry type: {type(entry).__name__}")

    elif suffix == ".csv":
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "word" not in reader.fieldnames:
                raise ValueError("CSV seed file must include a 'word' header column.")
            for row in reader:
                word = str(row.get("word") or "").strip()
                if not word:
                    continue
                if _has_structured_fields(row):
                    structured.append(_row_to_vocab_schema(row))
                else:
                    raw_words.append(word)
    else:
        raise ValueError(f"Unsupported seed file format '{suffix}'. Expected .json or .csv.")

    return structured, raw_words


async def _enrich_raw_words_in_chunks(
    chat_service: AIChatService,
    raw_words: List[str],
    topic: str = "general",
    chunk_size: int = ENRICH_CHUNK_SIZE,
) -> List[VocabSchema]:
    """
    Enrich raw vocabulary words into full VocabSchema records in bounded batches.

    Args:
        chat_service: AI chat service instance providing `enrich_raw_words`.
        raw_words: List of raw word strings.
        topic: Topic hint passed to the enrichment prompt.
        chunk_size: Maximum words per LLM call.

    Returns:
        Flattened list of enriched VocabSchema items.
    """
    enriched: List[VocabSchema] = []
    for idx in range(0, len(raw_words), chunk_size):
        chunk = raw_words[idx : idx + chunk_size]
        batch, _ = await chat_service.enrich_raw_words(words=chunk, topic=topic)
        enriched.extend(batch.items)
    return enriched


async def seed_from_file(
    file_path: Path,
    ingestion_service: VocabIngestionService,
    chat_service: Optional[AIChatService] = None,
    telegram_user_id: Optional[int] = None,
) -> IngestionReport:
    """
    Seed vocabulary items from a JSON or CSV file into PostgreSQL.

    Args:
        file_path: Path to the seed file.
        ingestion_service: Unified ingestion service handling dedup + 768-dim embeddings.
        chat_service: AI chat service used only when raw words need enrichment.
        telegram_user_id: Optional Telegram user scope (None for global ground truth).

    Returns:
        IngestionReport summarizing inserted and skipped duplicate words.
    """
    structured, raw_words = parse_seed_file(file_path)

    async with get_db_session() as session:
        items_to_ingest: List[VocabSchema] = list(structured)

        if raw_words:
            # Skip already existing DB words before spending LLM tokens enriching raw entries.
            existing = await ingestion_service.get_existing_words(
                session, telegram_user_id=telegram_user_id
            )
            seen_raw: set[str] = set()
            pending_words: List[str] = []
            for word in raw_words:
                norm = VocabIngestionService.normalize_word(word)
                if norm and norm not in existing and norm not in seen_raw:
                    seen_raw.add(norm)
                    pending_words.append(word)

            if pending_words:
                if chat_service is None:
                    raise RuntimeError(
                        "chat_service is required to enrich raw words from the seed file."
                    )
                enriched = await _enrich_raw_words_in_chunks(chat_service, pending_words)
                items_to_ingest.extend(enriched)

        return await ingestion_service.ingest_items(
            session=session,
            items=items_to_ingest,
            telegram_user_id=telegram_user_id,
        )


async def seed_from_topics(
    topics: Sequence[str],
    count: int,
    ingestion_service: VocabIngestionService,
    chat_service: AIChatService,
    telegram_user_id: Optional[int] = None,
) -> IngestionReport:
    """
    Generate and ingest topic-based vocabulary batches while excluding already stored words.

    Args:
        topics: Non-empty sequence of topic names.
        count: Number of words to generate per topic.
        ingestion_service: Unified ingestion service handling dedup + embeddings.
        chat_service: AI chat service providing `generate_vocab_batch`.
        telegram_user_id: Optional Telegram user scope.

    Returns:
        Aggregated IngestionReport across all topics.
    """
    combined = IngestionReport()
    async with get_db_session() as session:
        existing = await ingestion_service.get_existing_words(
            session, telegram_user_id=telegram_user_id
        )
        exclude_pool = sorted(existing)

        for raw_topic in topics:
            topic = raw_topic.strip()
            if not topic:
                continue
            batch, _ = await chat_service.generate_vocab_batch(
                topic=topic,
                count=count,
                exclude_words=exclude_pool,
            )
            report = await ingestion_service.ingest_items(
                session=session,
                items=batch.items,
                telegram_user_id=telegram_user_id,
            )
            combined.inserted += report.inserted
            combined.skipped_duplicates += report.skipped_duplicates
            combined.inserted_words.extend(report.inserted_words)
            combined.skipped_words.extend(report.skipped_words)
            exclude_pool.extend(report.inserted_words)

    return combined


def build_parser() -> argparse.ArgumentParser:
    """
    Construct the CLI argument parser for `seed_vocab`.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description="Seed ground-truth English vocabulary into PostgreSQL with 768-dim embeddings."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a .json or .csv seed file (structured or raw words).",
    )
    parser.add_argument(
        "--topics",
        type=str,
        default=None,
        help="Comma-separated list of topics to synthesize via Teacher LLM.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of words to generate per topic (default: 5).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Optional Telegram user ID scope (default: global seed).",
    )
    return parser


async def _run_cli(args: argparse.Namespace) -> None:
    """
    Execute the async seeding workflow from parsed CLI arguments.

    Args:
        args: Parsed CLI namespace.
    """
    settings = get_settings()
    embedding_service = EmbeddingService(settings=settings)
    ingestion_service = VocabIngestionService(embedding_service=embedding_service)

    redis_service: Optional[RedisService] = None
    chat_service: Optional[AIChatService] = None

    need_chat_service = bool(args.topics)
    if args.file:
        _, raw_words = parse_seed_file(args.file)
        need_chat_service = need_chat_service or bool(raw_words)

    if need_chat_service:
        redis_service = RedisService()
        chat_service = AIChatService(redis_service=redis_service)

    try:
        if args.file:
            report = await seed_from_file(
                file_path=args.file,
                ingestion_service=ingestion_service,
                chat_service=chat_service,
                telegram_user_id=args.user_id,
            )
            print(
                f"[FILE SEED] inserted={report.inserted}, "
                f"skipped_duplicates={report.skipped_duplicates}"
            )

        if args.topics:
            topic_list = [t.strip() for t in args.topics.split(",") if t.strip()]
            if chat_service is None:
                raise RuntimeError("AIChatService failed to initialize for topic seeding.")
            report = await seed_from_topics(
                topics=topic_list,
                count=args.count,
                ingestion_service=ingestion_service,
                chat_service=chat_service,
                telegram_user_id=args.user_id,
            )
            print(
                f"[TOPIC SEED] inserted={report.inserted}, "
                f"skipped_duplicates={report.skipped_duplicates}"
            )
    finally:
        if redis_service is not None:
            await redis_service.close()


def main() -> None:
    """
    CLI entry point for seeding vocabulary.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    if not args.file and not args.topics:
        parser.error("Provide at least one of --file or --topics.")
    asyncio.run(_run_cli(args))


if __name__ == "__main__":
    main()
