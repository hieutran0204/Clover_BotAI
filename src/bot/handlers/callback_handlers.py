"""
name: callback_handlers
description: Telegram inline keyboard callback handler for interactive vocabulary quizzes.
"""

import html
import logging
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from src.db.session import get_db_session
from src.services.vocab_service import VocabService

logger = logging.getLogger(__name__)


async def handle_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline button clicks formatted as 'quiz:<vocab_uuid>:<option_index>'.

    Parameters:
        update (Update): Incoming callback query update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "quiz":
        return

    try:
        vocab_id = uuid.UUID(parts[1])
        selected_index = int(parts[2])
    except ValueError:
        await query.edit_message_text("⚠️ Dữ liệu câu hỏi không hợp lệ.")
        return

    try:
        async with get_db_session() as session:
            result = await VocabService.record_quiz_attempt(
                session=session,
                vocab_id=vocab_id,
                telegram_user_id=update.effective_user.id,
                selected_index=selected_index,
            )

        if not result:
            await query.edit_message_text("⚠️ Không tìm thấy từ vựng này trong cơ sở dữ liệu.")
            return

        status_icon = "✅ <b>Chính xác!</b>" if result["is_correct"] else "❌ <b>Chưa đúng rồi!</b>"
        feedback = (
            f"{status_icon}\n\n"
            f"🔤 <b>{html.escape(result['word'])}</b> — Đáp án đúng: <b>{html.escape(result['correct_option'])}</b>\n"
            f"🇻🇳 Nghĩa: {html.escape(result['definition_vi'])}\n"
            f"💬 Ví dụ: <i>{html.escape(result['example_sentence'])}</i>"
        )
        await query.edit_message_text(feedback, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Failed to process quiz callback %s: %s", query.data, exc)
        await query.edit_message_text("⚠️ Có lỗi khi lưu kết quả ôn tập.")

