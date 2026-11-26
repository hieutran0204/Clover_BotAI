"""
name: test_media_handlers
description: Unit tests for Telegram photo OCR and PDF ingestion handlers verifying size guards and Redis locks.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import media_handlers
from src.schemas.vocab import VocabSchema
from src.services.vocab_ingestion_service import IngestionReport


def _make_vocab(word: str) -> VocabSchema:
    """
    Build a minimal VocabSchema instance for Telegram media handler tests.
    """
    return VocabSchema(
        word=word,
        phonetic="/p/",
        part_of_speech="noun",
        definition_vi="khả năng mở rộng",
        definition_en="ability to grow",
        example_sentence=f"Good {word} helps systems handle traffic.",
        example_translation="Khả năng mở rộng giúp hệ thống chịu tải tốt.",
        cefr_level="C1",
        quiz_question=f"What does {word} mean?",
        quiz_options=["A", "B", "C", "D"],
        quiz_correct_index=0,
    )


@pytest.mark.asyncio
async def test_handle_photo_message_downloads_ingests_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify photo OCR downloads bytes in memory, calls ingestion service, and releases Redis lock.
    """
    fake_session = MagicMock()

    @asynccontextmanager
    async def fake_db_session():
        yield fake_session

    monkeypatch.setattr(media_handlers, "get_db_session", fake_db_session)

    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"img-bytes"))

    redis_service = MagicMock()
    redis_service.acquire_user_lock = AsyncMock(return_value="lock-abc")
    redis_service.release_user_lock = AsyncMock()

    vision_extractor = MagicMock()
    vision_extractor.extract_from_image = AsyncMock(return_value=[_make_vocab("scalability")])

    vocab_ingestion = MagicMock()
    vocab_ingestion.ingest_items = AsyncMock(
        return_value=IngestionReport(inserted=1, skipped_duplicates=0, inserted_words=["scalability"])
    )

    update = MagicMock()
    update.effective_user.id = 777
    update.effective_chat.send_action = AsyncMock()
    update.effective_message.photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large", file_size=1024)]
    update.effective_message.caption = "IELTS notes"
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot.get_file = AsyncMock(return_value=tg_file)
    context.bot_data = {
        "redis_service": redis_service,
        "vision_extractor": vision_extractor,
        "vocab_ingestion": vocab_ingestion,
    }

    await media_handlers.handle_photo_message(update, context)

    vision_extractor.extract_from_image.assert_awaited_once()
    vocab_ingestion.ingest_items.assert_awaited_once()
    redis_service.release_user_lock.assert_awaited_once_with(777, "lock-abc")
    assert "scalability" in update.effective_message.reply_text.await_args_list[-1].args[0]


@pytest.mark.asyncio
async def test_handle_pdf_document_rejects_oversized_file() -> None:
    """
    Verify oversized PDF files (>max_telegram_file_mb) are rejected immediately without acquiring a lock or downloading.
    """
    redis_service = MagicMock()
    redis_service.acquire_user_lock = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 888
    update.effective_message.document = SimpleNamespace(
        file_id="huge-doc",
        file_size=media_handlers.MAX_TELEGRAM_FILE_BYTES + 1,
    )
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot.get_file = AsyncMock()
    context.bot_data = {
        "redis_service": redis_service,
        "vision_extractor": MagicMock(),
        "vocab_ingestion": MagicMock(),
    }

    await media_handlers.handle_pdf_document(update, context)

    redis_service.acquire_user_lock.assert_not_called()
    context.bot.get_file.assert_not_called()
    assert "50MB" in update.effective_message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_pdf_document_telegram_cloud_limit_explanation() -> None:
    """Verify BadRequest with 'File is too big' explains Telegram Cloud's 20MB limit and provides advice."""
    from telegram.error import BadRequest

    redis_service = MagicMock()
    redis_service.acquire_user_lock = AsyncMock(return_value="token123")
    redis_service.release_user_lock = AsyncMock()

    update = MagicMock()
    update.effective_user.id = 888
    update.effective_message.document = SimpleNamespace(
        file_id="cloud-rejected-doc",
        file_size=35 * 1024 * 1024,
    )
    update.effective_message.reply_text = AsyncMock()
    update.effective_chat = MagicMock()

    context = MagicMock()
    context.bot.get_file = AsyncMock(side_effect=BadRequest("File is too big"))
    context.bot_data = {
        "redis_service": redis_service,
        "vision_extractor": MagicMock(),
        "vocab_ingestion": MagicMock(),
    }

    await media_handlers.handle_pdf_document(update, context)

    redis_service.release_user_lock.assert_awaited_once_with(888, "token123")
    last_reply = update.effective_message.reply_text.await_args_list[-1].args[0]
    assert "Telegram Cloud" in last_reply
    assert "ilovepdf.com" in last_reply

