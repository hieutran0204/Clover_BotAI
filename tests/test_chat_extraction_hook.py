"""
name: test_chat_extraction_hook
description: Unit tests ensuring non-blocking passive extraction runs safely after Telegram reply delivery.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import message_handlers
from src.core.config import AIBackend
from src.schemas.vocab import VocabBatchSchema, VocabSchema
from src.services.vocab_ingestion_service import IngestionReport


def _sample_vocab(word: str = "resilient") -> VocabSchema:
    """
    Construct a valid VocabSchema record for background extraction hook tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/rɪˈzɪl.jənt/",
        part_of_speech="adjective",
        definition_vi="kiên cường",
        definition_en="able to recover quickly",
        example_sentence="Resilient systems recover fast.",
        example_translation="Hệ thống vững vàng phục hồi nhanh.",
        cefr_level="B2",
        quiz_question="What does resilient mean?",
        quiz_options=["Weak", "Recovering quickly", "Slow", "Silent"],
        quiz_correct_index=1,
    )


@pytest.mark.asyncio
async def test_handle_text_message_triggers_nonblocking_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify user reply is delivered first and passive extraction runs safely even if extraction fails.
    """
    fake_session = MagicMock()

    @asynccontextmanager
    async def fake_db_session():
        yield fake_session

    monkeypatch.setattr(message_handlers, "get_db_session", fake_db_session)
    monkeypatch.setattr(message_handlers.ChatLogService, "save_chat_log", AsyncMock())

    redis_service = MagicMock()
    redis_service.acquire_user_lock = AsyncMock(return_value="token-123")
    redis_service.release_user_lock = AsyncMock()

    ai_service = MagicMock()
    ai_service.chat_with_context = AsyncMock(
        return_value=(
            "Resilient means recovering quickly from failures.",
            [{"role": "user", "content": "What does resilient mean?"}],
            AIBackend.GEMINI,
            "gemini-3.8-flash",
        )
    )

    extractor = MagicMock()
    extractor.extract_from_turn = AsyncMock(
        return_value=VocabBatchSchema(items=[_sample_vocab("resilient")])
    )
    ingestion = MagicMock()
    ingestion.ingest_items = AsyncMock(
        return_value=IngestionReport(inserted=1, inserted_words=["resilient"])
    )

    update = MagicMock()
    update.effective_user.id = 999
    update.effective_chat.id = 999
    update.effective_message.text = "What does resilient mean?"
    update.effective_message.reply_text = AsyncMock()
    update.effective_chat.send_action = AsyncMock()

    context = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot_data = {
        "redis_service": redis_service,
        "ai_service": ai_service,
        "vocab_extractor": extractor,
        "vocab_ingestion": ingestion,
    }

    await message_handlers.handle_text_message(update, context)
    update.effective_message.reply_text.assert_awaited_once_with(
        "Resilient means recovering quickly from failures."
    )
    redis_service.release_user_lock.assert_awaited_once_with(999, "token-123")

    # Allow scheduled background extraction task to complete.
    if message_handlers._background_tasks:
        await asyncio.gather(*list(message_handlers._background_tasks))

    extractor.extract_from_turn.assert_awaited_once()
    ingestion.ingest_items.assert_awaited_once()
    context.bot.send_message.assert_awaited_once()
    assert "resilient" in context.bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_extract_and_ingest_background_swallows_exceptions() -> None:
    """
    Ensure background extraction exceptions are logged and never propagate out of the task.
    """
    extractor = MagicMock()
    extractor.extract_from_turn = AsyncMock(side_effect=RuntimeError("Gemini rate limit"))
    ingestion = MagicMock()
    ingestion.ingest_items = AsyncMock()

    await message_handlers.extract_and_ingest_background(
        user_id=101,
        user_message="Tell me about scalability",
        bot_reply="Scalability is...",
        extractor=extractor,
        ingestion=ingestion,
        backend=AIBackend.GEMINI,
    )

    ingestion.ingest_items.assert_not_called()
