"""
name: test_vocab_extractor
description: Unit tests for VocabExtractorService trivial filtering and structured extraction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config import AIBackend
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.ai import vocab_extractor
from src.services.ai.vocab_extractor import VocabExtractorService


def _make_vocab(word: str = "ubiquitous") -> VocabSchema:
    """
    Construct a minimal VocabSchema instance for passive extraction tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/juːˈbɪk.wɪ.təs/",
        part_of_speech="adjective",
        definition_vi="phổ biến",
        definition_en="found everywhere",
        example_sentence=f"{word.capitalize()} tools dominate today.",
        example_translation="Các công cụ phổ biến thống trị hiện nay.",
        cefr_level="C1",
        quiz_question=f"Meaning of {word}?",
        quiz_options=["Rare", "Everywhere", "Broken", "Tiny"],
        quiz_correct_index=1,
    )


@pytest.mark.asyncio
async def test_trivial_greeting_skips_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure trivial greetings return an empty batch immediately without invoking an LLM.
    """
    spy_factory = MagicMock()
    monkeypatch.setattr(vocab_extractor.LLMFactory, "get_chat_model", spy_factory)

    service = VocabExtractorService()
    batch = await service.extract_from_turn(user_message="Hello!", bot_reply="Hi! How can I help?")

    assert batch.items == []
    spy_factory.assert_not_called()


@pytest.mark.asyncio
async def test_extract_from_turn_returns_structured_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure meaningful chat turns extract structured VocabSchema items from the LLM.
    """
    expected = VocabBatchSchema(items=[_make_vocab("mitigate")])
    fake_structured_llm = MagicMock()
    fake_structured_llm.ainvoke = AsyncMock(return_value=expected)
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured_llm

    monkeypatch.setattr(
        vocab_extractor.LLMFactory,
        "get_chat_model",
        MagicMock(return_value=(fake_llm, "gemini-3.8-flash")),
    )

    service = VocabExtractorService()
    result = await service.extract_from_turn(
        user_message="How do you mitigate latency bottlenecks?",
        bot_reply="'Mitigate' means to reduce the severity of something.",
        backend=AIBackend.GEMINI,
    )

    assert len(result.items) == 1
    assert result.items[0].word == "mitigate"
    fake_structured_llm.ainvoke.assert_awaited_once()

