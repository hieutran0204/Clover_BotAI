"""
name: media_handlers
description: Telegram handlers for photo OCR and PDF document vocabulary extraction into PostgreSQL.
"""

from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.core.config import get_settings
from src.db.session import get_db_session
from src.services.ai.vision_extractor import VisionExtractorService
from src.services.redis_service import RedisService
from src.services.vocab_ingestion_service import VocabIngestionService

logger = logging.getLogger(__name__)

MAX_TELEGRAM_FILE_BYTES = get_settings().max_telegram_file_bytes


async def _safe_send_typing(chat) -> None:
    """Send typing action safely without throwing on network disconnects."""
    try:
        if chat:
            await chat.send_action(ChatAction.TYPING)
    except Exception as exc:
        logger.debug("Non-fatal network error sending typing action: %s", exc)


async def _download_telegram_file(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> bytes:
    """
    Download a Telegram file completely into memory without writing temporary artifacts to disk.

    Parameters:
        file_id (str): Telegram file identifier.
        context (ContextTypes.DEFAULT_TYPE): Callback context with bot client.

    Returns:
        bytes: Raw downloaded file payload.
    """
    tg_file = await context.bot.get_file(file_id)
    data = await tg_file.download_as_bytearray()
    return bytes(data)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Process incoming Telegram photos using Gemini Vision OCR and save extracted words to ground truth.

    Parameters:
        update (Update): Incoming Telegram update containing photo attachments.
        context (ContextTypes.DEFAULT_TYPE): Callback context holding shared services.
    """
    if not update.effective_message or not update.effective_user or not update.effective_message.photo:
        return

    user_id = update.effective_user.id
    photo = update.effective_message.photo[-1]
    settings = get_settings()
    if photo.file_size and photo.file_size > settings.max_telegram_file_bytes:
        await update.effective_message.reply_text(
            f"⚠️ Ảnh vượt quá giới hạn {settings.max_telegram_file_mb}MB của bot. Bạn vui lòng nén hoặc cắt nhỏ ảnh nhé!"
        )
        return

    redis_service: RedisService = context.bot_data["redis_service"]
    vision_extractor: VisionExtractorService = context.bot_data["vision_extractor"]
    vocab_ingestion: VocabIngestionService = context.bot_data["vocab_ingestion"]

    lock_token = await redis_service.acquire_user_lock(user_id)
    if not lock_token:
        await update.effective_message.reply_text("⏳ Bot đang xử lý yêu cầu trước của bạn, đợi xíu nhé!")
        return

    try:
        await _safe_send_typing(update.effective_chat)
        await update.effective_message.reply_text("🖼️ Đang đọc ảnh và trích xuất từ vựng qua Gemini Vision...")

        image_bytes = await _download_telegram_file(photo.file_id, context)
        extracted_items = await vision_extractor.extract_from_image(
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            caption=update.effective_message.caption,
        )

        if not extracted_items:
            await update.effective_message.reply_text(
                "🔍 Mình chưa nhận diện được từ vựng tiếng Anh nổi bật nào trong ảnh này."
            )
            return

        async with get_db_session() as session:
            report = await vocab_ingestion.ingest_items(
                session=session,
                items=extracted_items,
                telegram_user_id=user_id,
            )

        preview = ", ".join(html.escape(w) for w in report.inserted_words[:10])
        summary_lines = [
            "📚 <b>Kết quả OCR từ ảnh:</b>",
            f"• Thêm mới: <b>{report.inserted}</b> từ",
            f"• Bỏ qua trùng lặp: <b>{report.skipped_duplicates}</b> từ",
        ]
        if preview:
            summary_lines.append(f"• Từ mới: <code>{preview}</code>")
        summary_lines.append("\n⏰ Các từ mới đã được nạp vector 768 chiều và đưa vào lịch ôn SM-2!")
        await update.effective_message.reply_text("\n".join(summary_lines), parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error processing photo OCR for user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            "⚠️ Xin lỗi, quá trình đọc ảnh gặp sự cố. Bạn thử gửi lại ảnh rõ nét hơn nhé!"
        )
    finally:
        await redis_service.release_user_lock(user_id, lock_token)


async def handle_pdf_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Process incoming Telegram PDF documents in bounded page chunks and save extracted vocabulary.

    Parameters:
        update (Update): Incoming Telegram update containing a PDF attachment.
        context (ContextTypes.DEFAULT_TYPE): Callback context holding shared services.
    """
    if not update.effective_message or not update.effective_user or not update.effective_message.document:
        return

    document = update.effective_message.document
    user_id = update.effective_user.id
    settings = get_settings()

    if document.file_size and document.file_size > settings.max_telegram_file_bytes:
        await update.effective_message.reply_text(
            f"⚠️ File PDF vượt quá giới hạn {settings.max_telegram_file_mb}MB. Bạn vui lòng nén hoặc tách nhỏ file rồi gửi lại nhé!"
        )
        return

    redis_service: RedisService = context.bot_data["redis_service"]
    vision_extractor: VisionExtractorService = context.bot_data["vision_extractor"]
    vocab_ingestion: VocabIngestionService = context.bot_data["vocab_ingestion"]

    lock_token = await redis_service.acquire_user_lock(user_id)
    if not lock_token:
        await update.effective_message.reply_text("⏳ Bot đang xử lý yêu cầu trước của bạn, đợi xíu nhé!")
        return

    try:
        await _safe_send_typing(update.effective_chat)
        await update.effective_message.reply_text(
            "📄 Đang đọc tài liệu PDF (tối đa 15 trang đầu) và trích xuất từ vựng..."
        )

        pdf_bytes = await _download_telegram_file(document.file_id, context)
        extracted_items, total_pages, was_truncated = await vision_extractor.extract_from_pdf(
            pdf_bytes=pdf_bytes,
            caption=update.effective_message.caption,
        )

        if not extracted_items:
            await update.effective_message.reply_text(
                "🔍 Không tìm thấy từ vựng tiếng Anh nổi bật nào trong các trang PDF đã đọc."
            )
            return

        async with get_db_session() as session:
            report = await vocab_ingestion.ingest_items(
                session=session,
                items=extracted_items,
                telegram_user_id=user_id,
            )

        preview = ", ".join(html.escape(w) for w in report.inserted_words[:10])
        summary_lines = [
            f"📄 <b>Kết quả trích xuất PDF</b> ({total_pages} trang):",
            f"• Thêm mới: <b>{report.inserted}</b> từ",
            f"• Bỏ qua trùng lặp: <b>{report.skipped_duplicates}</b> từ",
        ]
        if was_truncated:
            summary_lines.append("• <i>Lưu ý: Đã giới hạn xử lý 15 trang đầu để tối ưu tốc độ.</i>")
        if preview:
            summary_lines.append(f"• Từ mới: <code>{preview}</code>")
        await update.effective_message.reply_text("\n".join(summary_lines), parse_mode="HTML")
    except BadRequest as exc:
        if "file is too big" in str(exc).lower():
            file_size_mb = f"{document.file_size / (1024 * 1024):.1f}MB" if document.file_size else "lớn"
            await update.effective_message.reply_text(
                f"⚠️ <b>Máy chủ Telegram Cloud giới hạn tải file:</b>\n"
                f"Telegram hiện chỉ cho phép Bot tải file dưới <b>20MB</b> trực tiếp từ đám mây (file của bạn là <b>{file_size_mb}</b>).\n\n"
                f"💡 <b>Cách xử lý để tiếp tục học:</b>\n"
                f"1. Nén nhanh file tại website miễn phí <i>ilovepdf.com</i> (giảm dung lượng mà chữ vẫn rõ nét).\n"
                f"2. Tách file thành các chương nhỏ hơn hoặc chụp ảnh màn hình các trang muốn phân tích và gửi dạng ảnh nhé!",
                parse_mode="HTML",
            )
        else:
            logger.warning("Telegram BadRequest for user %s: %s", user_id, exc)
            await update.effective_message.reply_text(f"⚠️ Telegram từ chối xử lý file: {html.escape(str(exc))}")
    except ValueError as exc:
        await update.effective_message.reply_text(
            f"⚠️ {html.escape(str(exc))}\n💡 Nếu đây là PDF dạng ảnh scan, bạn có thể chụp màn hình từng trang và gửi dạng ảnh nhé!",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Error processing PDF for user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            "⚠️ Xin lỗi, mình gặp sự cố khi phân tích file PDF này. Bạn thử lại sau nhé!"
        )
    finally:
        await redis_service.release_user_lock(user_id, lock_token)

