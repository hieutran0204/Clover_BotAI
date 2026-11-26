"""
name: test_seed_topics
description: Unit tests for AI topic-based batch vocabulary seeding and exclude_words propagation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cli import seed_vocab
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.vocab_ingestion_service import IngestionReport, VocabIngestionService


def _make_schema(word: str) -> VocabSchema:
    """
    Build a minimal valid VocabSchema for topic batch seeding tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/t/",
        part_of_speech="noun",
        definition_vi="nghĩa",
        definition_en="meaning",
        example_sentence=f"Using {word} in context.",
        example_translation="Dùng từ trong ngữ cảnh.",
        cefr_level="B2",
        quiz_question=f"What is {word}?",
        quiz_options=["1", "2", "3", "4"],
        quiz_correct_index=0,
    )


@pytest.mark.asyncio
async def test_seed_from_topics_propagates_exclude_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verify existing DB words and newly generated words are passed in `exclude_words` across topics.
    """
    fake_session = MagicMock()

    @asynccontextmanager
    async def fake_db_session():
        yield fake_session

    monkeypatch.setattr(seed_vocab, "get_db_session", fake_db_session)

    ingestion_service = MagicMock(spec=VocabIngestionService)
    ingestion_service.get_existing_words = AsyncMock(return_value={"baseline"})
    ingestion_service.ingest_items = AsyncMock(
        side_effect=[
            IngestionReport(inserted=1, inserted_words=["throughput"]),
            IngestionReport(inserted=1, inserted_words=["leverage"]),
        ]
    )

    chat_service = MagicMock()
    chat_service.generate_vocab_batch = AsyncMock(
        side_effect=[
            (VocabBatchSchema(items=[_make_schema("throughput")]), "gemini-3.8-flash"),
            (VocabBatchSchema(items=[_make_schema("leverage")]), "gemini-3.8-flash"),
        ]
    )

    report = await seed_vocab.seed_from_topics(
        topics=["Backend Architecture", "Business Negotiation"],
        count=1,
        ingestion_service=ingestion_service,
        chat_service=chat_service,
    )

    assert report.inserted == 2
    assert report.inserted_words == ["throughput", "leverage"]

    first_call = chat_service.generate_vocab_batch.await_args_list[0].kwargs
    second_call = chat_service.generate_vocab_batch.await_args_list[1].kwargs
    assert "baseline" in first_call["exclude_words"]
    assert "throughput" in second_call["exclude_words"]

