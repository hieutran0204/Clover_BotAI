"""
name: message_handlers
description: Telegram text message handler integrating Redis locking, LangChain chat, and PostgreSQL logging.
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.core.config import AIBackend
from src.db.session import get_db_session
from src.services.ai.chat_service import AIChatService
from src.services.ai.vocab_extractor import VocabExtractorService
from src.services.chat_log_service import ChatLogService
from src.services.redis_service import RedisService
from src.services.vocab_ingestion_service import VocabIngestionService

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()


async def _safe_send_typing(chat) -> None:
    """Send typing action safely without throwing on network disconnects."""
    try:
        if chat:
            await chat.send_action(ChatAction.TYPING)
    except Exception as exc:
        logger.debug("Non-fatal network error sending typing action: %s", exc)


async def extract_and_ingest_background(
    user_id: int,
    user_message: str,
    bot_reply: str,
    extractor: VocabExtractorService,
    ingestion: VocabIngestionService,
    backend: AIBackend,
    bot: object | None = None,
    chat_id: int | None = None,
) -> None:
    """
    Asynchronously extract learnable vocabulary from a completed turn and persist it.

    Parameters:
        user_id (int): Telegram user identifier.
        user_message (str): Raw user input text.
        bot_reply (str): Tutor response delivered to the user.
        extractor (VocabExtractorService): Passive vocabulary extractor service.
        ingestion (VocabIngestionService): Unified ingestion service with dedup and embeddings.
        backend (AIBackend): Backend active during the conversation turn.
        bot (Optional[object]): Telegram Bot instance used to send non-blocking confirmation.
        chat_id (Optional[int]): Target Telegram chat ID for notifying newly saved words.
    """
    try:
        batch = await extractor.extract_from_turn(
            user_message=user_message,
            bot_reply=bot_reply,
            backend=backend,
        )
        if not batch.items:
            return
        async with get_db_session() as session:
            report = await ingestion.ingest_items(
                session=session,
                items=batch.items,
                telegram_user_id=user_id,
            )
            if report.inserted:
                logger.info(
                    "Passive extraction saved %s new word(s) for user %s: %s",
                    report.inserted,
                    user_id,
                    report.inserted_words,
                )
                if bot is not None and chat_id is not None:
                    saved_list = ", ".join(report.inserted_words)
                    await bot.send_message(  # type: ignore[attr-defined]
                        chat_id=chat_id,
                        text=f"📝 Đã tự động lưu từ mới vào lịch ôn tập: {saved_list}",
                    )
    except Exception as exc:
        logger.warning("Passive vocabulary extraction skipped for user %s: %s", user_id, exc)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Process incoming user text messages through Redis lock, LangChain AI, and PostgreSQL chat_logs.

    Parameters:
        update (Update): Incoming Telegram update containing user message.
        context (ContextTypes.DEFAULT_TYPE): Callback context with shared services.
    """
    if not update.effective_message or not update.effective_user or not update.effective_message.text:
        return

    user_id = update.effective_user.id
    user_text = update.effective_message.text.strip()
    if not user_text:
        return

    redis_service: RedisService = context.bot_data["redis_service"]
    ai_service: AIChatService = context.bot_data["ai_service"]

    lock_token = await redis_service.acquire_user_lock(user_id)
    if not lock_token:
        await update.effective_message.reply_text("⏳ Bot đang soạn câu trả lời trước, bạn đợi xíu nhé!")
        return

    try:
        await _safe_send_typing(update.effective_chat)
        reply_text, turns_json, backend_used, model_name = await asyncio.wait_for(
            ai_service.chat_with_context(
                user_id=user_id,
                user_message=user_text,
            ),
            timeout=55.0,
        )

        async with get_db_session() as session:
            await ChatLogService.save_chat_log(
                session=session,
                telegram_user_id=user_id,
                ai_backend=backend_used.value,
                model_name=model_name,
                prompt=user_text,
                response=reply_text,
                turns_json=turns_json,
            )

        await update.effective_message.reply_text(reply_text)

        extractor: VocabExtractorService | None = context.bot_data.get("vocab_extractor")
        ingestion: VocabIngestionService | None = context.bot_data.get("vocab_ingestion")
        if extractor is not None and ingestion is not None:
            task = asyncio.create_task(
                extract_and_ingest_background(
                    user_id=user_id,
                    user_message=user_text,
                    bot_reply=reply_text,
                    extractor=extractor,
                    ingestion=ingestion,
                    backend=backend_used,
                    bot=context.bot,
                    chat_id=update.effective_chat.id if update.effective_chat else user_id,
                )
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    except asyncio.TimeoutError:
        logger.warning("AI request timed out after 55s for user %s", user_id)
        await update.effective_message.reply_text(
            "⏳ Hệ thống AI phản hồi hơi lâu, bạn thử lại với câu ngắn hơn nhé!"
        )
    except Exception as exc:
        logger.exception("Error handling message from user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            "⚠️ Xin lỗi, mình đang gặp sự cố kết nối AI. Bạn thử lại sau vài giây nhé!"
        )
    finally:
        await redis_service.release_user_lock(user_id, lock_token)

