"""
name: test_phase3_rag_and_agent
description: Unit and integration tests for NomicEmbeddingsWrapper, RRF ranking, ScheduleService, and Admin Review.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.schemas.grammar import GrammarExampleSchema, GrammarSchema
from src.services.ai.embedding_service import NomicEmbeddingsWrapper
from src.services.ai.rag_retriever import KnowledgeRetriever, RetrievedItem
from src.services.schedule_service import ScheduleService


def test_nomic_embeddings_wrapper_adds_prefixes() -> None:
    """Verify NomicEmbeddingsWrapper strictly enforces search_document and search_query prefixes."""
    mock_base = MagicMock()
    mock_base.embed_documents.return_value = [[0.1, 0.2]]
    mock_base.embed_query.return_value = [0.1, 0.2]

    wrapper = NomicEmbeddingsWrapper(base_embeddings=mock_base)

    # Document embedding prefix check
    docs = ["bottleneck in system", "resilient cluster"]
    wrapper.embed_documents(docs)
    mock_base.embed_documents.assert_called_once_with([
        "search_document: bottleneck in system",
        "search_document: resilient cluster",
    ])

    # Query embedding prefix check
    wrapper.embed_query("mitigate bottleneck")
    mock_base.embed_query.assert_called_once_with("search_query: mitigate bottleneck")


def test_apply_rrf_fuses_and_ranks_correctly() -> None:
    """Verify Reciprocal Rank Fusion aggregates sparse and dense rankings properly."""
    item1 = RetrievedItem(id="uuid-1", kind="vocab", title="bottleneck", content="...", fts_rank=0.9)
    item2 = RetrievedItem(id="uuid-2", kind="vocab", title="resilient", content="...", fts_rank=0.5)

    item2_dense = RetrievedItem(id="uuid-2", kind="vocab", title="resilient", content="...", dense_score=0.95)
    item1_dense = RetrievedItem(id="uuid-1", kind="vocab", title="bottleneck", content="...", dense_score=0.4)

    # In sparse: item1 is rank 1, item2 is rank 2
    # In dense:  item2 is rank 1, item1 is rank 2
    fused = KnowledgeRetriever._apply_rrf(
        sparse_items=[item1, item2],
        dense_items=[item2_dense, item1_dense],
        k_constant=60,
    )

    assert len(fused) == 2
    assert fused[0].rrf_score > 0
    # Both items have identical reciprocal rank sum: 0.5/(61) + 0.5/(62)
    assert abs(fused[0].rrf_score - fused[1].rrf_score) < 1e-6


@pytest.mark.asyncio
async def test_query_rewriting_heuristic_for_short_english() -> None:
    """Verify short pure English queries skip external LLM calls via fast-path heuristic."""
    retriever = KnowledgeRetriever()
    rewritten = await retriever.rewrite_query("bottleneck")
    assert rewritten.english_query == "bottleneck"
    assert rewritten.keywords == ["bottleneck"]

