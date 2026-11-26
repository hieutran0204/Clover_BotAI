"""
name: test_vocab_ingestion
description: Unit tests for VocabIngestionService deduplication, batch insertion, and 768-dim EmbeddingService.
"""

from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.ai.embedding_service import EmbeddingService
from src.services.vocab_ingestion_service import VocabIngestionService


class _FakeEmbedder:
    """Deterministic fake embedder returning 768-dim vectors."""

    async def aembed_query(self, text: str, output_dimensionality: int = 768) -> List[float]:
        return [0.1] * output_dimensionality

    async def aembed_documents(
        self, texts: List[str], output_dimensionality: int = 768
    ) -> List[List[float]]:
        return [[0.2] * output_dimensionality for _ in texts]


def _make_vocab(word: str) -> VocabSchema:
    return VocabSchema(
        word=word,
        phonetic="/test/",
        part_of_speech="noun",
        definition_vi="nghĩa mẫu",
        definition_en="sample definition",
        example_sentence=f"This uses {word}.",
        example_translation="Đây là ví dụ.",
        cefr_level="B2",
        quiz_question=f"Meaning of {word}?",
        quiz_options=["A", "B", "C", "D"],
        quiz_correct_index=0,
    )


async def test_embedding_service_produces_768_dimensions() -> None:
    """Verify EmbeddingService generates vectors matching the 768-dim pgvector schema."""
    svc = EmbeddingService(embedder=_FakeEmbedder())
    single = await svc.embed_text("resilient")
    assert single is not None
    assert len(single) == 768

    batch = await svc.embed_texts(["alpha", "beta"])
    assert len(batch) == 2
    assert all(vec is not None and len(vec) == 768 for vec in batch)


async def test_vocab_ingestion_deduplicates_db_and_in_batch() -> None:
    """Verify VocabIngestionService skips both DB-existing and intra-batch duplicates before embedding."""
    embed_svc = EmbeddingService(embedder=_FakeEmbedder())
    ingest_svc = VocabIngestionService(embedding_service=embed_svc)

    mock_session = MagicMock()
    mock_session.flush = AsyncMock()
    added_records = []
    mock_session.add = lambda obj: added_records.append(obj)

    items = [_make_vocab("Resilient"), _make_vocab("pragmatic"), _make_vocab("  PRAGMATIC  ")]
    batch_schema = VocabBatchSchema(items=items)
    assert len(batch_schema.items) == 3

    with patch.object(
        VocabIngestionService,
        "get_existing_words",
        AsyncMock(return_value={"resilient"}),
    ):
        report = await ingest_svc.ingest_items(mock_session, items, telegram_user_id=123)

    assert report.inserted == 1
    assert report.skipped_duplicates == 2
    assert report.inserted_words == ["pragmatic"]
    assert len(added_records) == 1
    assert len(added_records[0].embedding) == 768

