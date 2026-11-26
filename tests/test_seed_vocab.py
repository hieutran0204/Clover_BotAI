"""
name: test_seed_vocab
description: Unit tests for JSON and CSV vocabulary parsing and file seeding orchestration.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cli import seed_vocab
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.vocab_ingestion_service import IngestionReport, VocabIngestionService


def _make_schema(word: str = "ubiquitous") -> VocabSchema:
    """
    Build a valid VocabSchema object for file seeder tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/test/",
        part_of_speech="adjective",
        definition_vi="phổ biến",
        definition_en="found everywhere",
        example_sentence=f"The word {word} is useful.",
        example_translation="Từ này hữu ích.",
        cefr_level="B2",
        quiz_question=f"Meaning of {word}?",
        quiz_options=["A", "B", "C", "D"],
        quiz_correct_index=1,
    )


def test_parse_seed_file_structured_and_raw_json(tmp_path: Path) -> None:
    """
    Verify structured JSON and raw JSON word arrays are separated accurately.
    """
    structured_file = tmp_path / "structured.json"
    structured_file.write_text(
        json.dumps([_make_schema("pragmatic").model_dump()]),
        encoding="utf-8",
    )
    structured, raw = seed_vocab.parse_seed_file(structured_file)
    assert len(structured) == 1
    assert structured[0].word == "pragmatic"
    assert raw == []

    raw_file = tmp_path / "raw.json"
    raw_file.write_text(json.dumps(["resilient", "mitigate"]), encoding="utf-8")
    structured, raw = seed_vocab.parse_seed_file(raw_file)
    assert structured == []
    assert raw == ["resilient", "mitigate"]


def test_parse_seed_file_csv_structured_and_raw(tmp_path: Path) -> None:
    """
    Verify CSV parsing supports both full structured columns (pipe options) and raw 'word' CSV.
    """
    full_csv = tmp_path / "full.csv"
    full_csv.write_text(
        "word,phonetic,part_of_speech,definition_vi,definition_en,example_sentence,example_translation,cefr_level,quiz_question,quiz_options,quiz_correct_index\n"
        "concise,/kənˈsaɪs/,adjective,ngắn gọn,brief,Be concise.,Hãy ngắn gọn.,B2,Meaning?,Brief|Long|Slow|Dark,0\n",
        encoding="utf-8",
    )
    structured, raw = seed_vocab.parse_seed_file(full_csv)
    assert len(structured) == 1
    assert structured[0].quiz_options == ["Brief", "Long", "Slow", "Dark"]
    assert raw == []

    raw_csv = tmp_path / "raw.csv"
    raw_csv.write_text("word\nambiguous\nstreamline\n", encoding="utf-8")
    structured, raw = seed_vocab.parse_seed_file(raw_csv)
    assert structured == []
    assert raw == ["ambiguous", "streamline"]


@pytest.mark.asyncio
async def test_seed_from_file_enriches_only_new_raw_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ensure raw words already stored in PostgreSQL are excluded before calling Teacher LLM enrichment.
    """
    raw_file = tmp_path / "words.json"
    raw_file.write_text(
        json.dumps(["ubiquitous", "resilient", "Resilient"]),
        encoding="utf-8",
    )

    fake_session = MagicMock()

    @asynccontextmanager
    async def fake_db_session():
        yield fake_session

    monkeypatch.setattr(seed_vocab, "get_db_session", fake_db_session)

    ingestion_service = MagicMock(spec=VocabIngestionService)
    ingestion_service.get_existing_words = AsyncMock(return_value={"ubiquitous"})
    ingestion_service.ingest_items = AsyncMock(
        return_value=IngestionReport(inserted=1, skipped_duplicates=0, inserted_words=["resilient"])
    )

    chat_service = MagicMock()
    chat_service.enrich_raw_words = AsyncMock(
        return_value=(VocabBatchSchema(items=[_make_schema("resilient")]), "gemini-3.8-flash")
    )

    report = await seed_vocab.seed_from_file(
        file_path=raw_file,
        ingestion_service=ingestion_service,
        chat_service=chat_service,
    )

    chat_service.enrich_raw_words.assert_awaited_once_with(words=["resilient"], topic="general")
    assert report.inserted == 1
    assert report.inserted_words == ["resilient"]

