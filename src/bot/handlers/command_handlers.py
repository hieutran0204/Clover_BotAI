"""
name: command_handlers
description: Telegram command handlers for /start, /help, /learn, /model, /stats, and /clear.
"""

import html
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.bot.jobs.vocab_jobs import build_quiz_message_and_markup
from src.core.config import AIBackend, get_settings
from src.db.models import GrammarGroundTruth, UserStudySchedule, VocabGroundTruth
from src.db.session import get_db_session
from src.services.ai.agent_service import StudyAgentService
from src.services.ai.chat_service import AIChatService
from src.services.chat_log_service import ChatLogService
from src.services.redis_service import RedisService
from src.services.schedule_service import ScheduleService
from src.services.vocab_ingestion_service import VocabIngestionService
from src.services.vocab_service import VocabService

logger = logging.getLogger(__name__)


async def _reply_safe_html(message: Any, text: str) -> None:
    """
    Send message using HTML parse mode, falling back to plain text if Telegram entity parsing fails.

    Parameters:
        message: Telegram Message object with reply_text method.
        text (str): Content string to send.
    """
    try:
        await message.reply_text(text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Telegram HTML entity parsing failed (%s); falling back to plain text", exc)
        await message.reply_text(text)


async def _safe_send_typing(chat: Any) -> None:
    """Send typing action safely without throwing on network disconnects."""
    try:
        if chat:
            await chat.send_action(ChatAction.TYPING)
    except Exception as exc:
        logger.debug("Non-fatal network error sending typing action: %s", exc)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /start command with a welcome guide and available commands.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context containing bot_data services.
    """
    if not update.effective_message:
        return
    welcome = (
        "👋 <b>Chào mừng đến với AI-Telegram Study Buddy!</b>\n\n"
        "Bạn có thể nhắn tin trực tiếp với mình để luyện giao tiếp tiếng Anh tự nhiên, "
        "hoặc dùng các lệnh sau:\n"
        "• <code>/vocab [từ|câu]</code> hoặc <code>/vocal</code> — Tra cứu từ vựng DB-First hoặc xem lịch ôn tập\n"
        "• <code>/vocab schedule [số_từ] [HH:MM]</code> — Đặt lịch học từ mới mỗi ngày\n"
        "• <code>/grammar [câu|công thức]</code> hoặc <code>/gramma</code> — Tra cứu ngữ pháp & phân tích câu DB-First\n"
        "• <code>/grammar list</code> — Xem danh sách các chủ điểm ngữ pháp trong DB\n"
        "• <code>/quiz</code> — Ôn tập nhanh 1 từ đến hạn theo thuật toán SM-2\n"
        "• <code>/report [lý do]</code> — Báo cáo nội dung sai để admin kiểm duyệt\n"
        "• <code>/learn [chủ đề]</code> — Học ngay một từ vựng mới kèm quiz\n"
        "• <code>/model [gemini|ollama|huggingface]</code> — Xem hoặc chuyển đổi tầng AI\n"
        "• <code>/stats</code> — Xem thống kê kho từ vựng và Golden Dataset\n"
        "• <code>/clear</code> — Xóa ngữ cảnh hội thoại gần đây trong Redis\n"
        "• <code>/help</code> — Hiển thị hướng dẫn"
    )
    await _reply_safe_html(update.effective_message, welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /help command.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    await start_command(update, context)


async def learn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /learn [topic] by generating a structured vocabulary lesson and saving it to PostgreSQL.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    topic = " ".join(context.args).strip() if context.args else "daily communication"

    redis_service: RedisService = context.bot_data["redis_service"]
    ai_service: AIChatService = context.bot_data["ai_service"]

    lock_token = await redis_service.acquire_user_lock(user_id)
    if not lock_token:
        await update.effective_message.reply_text("⏳ Mình đang xử lý yêu cầu trước của bạn, đợi chút nhé!")
        return

    try:
        await _safe_send_typing(update.effective_chat)
        vocab_schema, model_name = await ai_service.generate_vocab_item(topic=topic)

        async with get_db_session() as session:
            ingestion: VocabIngestionService = context.bot_data["vocab_ingestion"]
            await ingestion.ingest_items(session, [vocab_schema], telegram_user_id=user_id)

        lesson_text = (
            f"📚 <b>Từ vựng mới ({html.escape(vocab_schema.cefr_level)})</b> — <i>[{html.escape(model_name)}]</i>\n\n"
            f"🔤 <b>{html.escape(vocab_schema.word)}</b> "
            f"<code>{html.escape(vocab_schema.phonetic)}</code> "
            f"(<i>{html.escape(vocab_schema.part_of_speech)}</i>)\n"
            f"🇻🇳 {html.escape(vocab_schema.definition_vi)}\n"
            f"🇬🇧 {html.escape(vocab_schema.definition_en)}\n\n"
            f"💬 <b>Ví dụ:</b>\n"
            f"<i>{html.escape(vocab_schema.example_sentence)}</i>\n"
            f"↳ {html.escape(vocab_schema.example_translation)}\n\n"
            "⏰ Từ này đã được lưu vào hàng đợi ôn tập (Spaced Repetition)!"
        )
        await update.effective_message.reply_text(lesson_text, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /learn command for user %s: %s", user_id, exc)
        await update.effective_message.reply_text(
            "⚠️ Có lỗi khi tạo từ vựng mới. Vui lòng thử lại sau."
        )
    finally:
        await redis_service.release_user_lock(user_id, lock_token)


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /model to inspect or switch the active AI backend stage (gemini, ollama, huggingface).

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    if not update.effective_message or not update.effective_user:
        return

    settings = get_settings()
    redis_service: RedisService = context.bot_data["redis_service"]

    if not context.args:
        current = await redis_service.get_active_backend()
        await update.effective_message.reply_text(
            f"🤖 Tầng AI hiện tại: <code>{html.escape(current.value)}</code>\n"
            "Dùng: <code>/model gemini</code>, <code>/model ollama</code>, hoặc <code>/model huggingface</code>",
            parse_mode="HTML",
        )
        return

    # Restrict switching to admins if ADMIN_USER_IDS is configured
    if settings.admin_user_ids and update.effective_user.id not in settings.admin_user_ids:
        await update.effective_message.reply_text("⛔ Chỉ admin mới được phép chuyển đổi tầng AI.")
        return

    target_raw = context.args[0].strip().lower()
    try:
        target_backend = AIBackend(target_raw)
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Tầng AI không hợp lệ. Chọn một trong: <code>gemini</code>, <code>ollama</code>, <code>huggingface</code>.",
            parse_mode="HTML",
        )
        return

    await redis_service.set_active_backend(target_backend)
    await update.effective_message.reply_text(
        f"✅ Đã chuyển sang tầng AI: <code>{html.escape(target_backend.value)}</code>",
        parse_mode="HTML",
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /stats to report vocabulary count and chat log distillation statuses from PostgreSQL.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    if not update.effective_message:
        return

    try:
        async with get_db_session() as session:
            vocab_count = await VocabService.count_vocab(session)
            status_counts = await ChatLogService.get_status_counts(session)

        total_chats = sum(status_counts.values())
        golden = status_counts.get("verified_golden", 0)
        raw = status_counts.get("raw", 0)
        rejected = status_counts.get("rejected", 0)

        msg = (
            "📊 <b>Thống kê Hệ thống (PostgreSQL)</b>\n\n"
            f"📚 Tổng từ vựng: <b>{vocab_count}</b>\n"
            f"💬 Tổng lượt chat logs: <b>{total_chats}</b>\n"
            f"  • Golden (verified): <b>{golden}</b>\n"
            f"  • Raw (chờ lọc): <b>{raw}</b>\n"
            f"  • Rejected: <b>{rejected}</b>"
        )
        await update.effective_message.reply_text(msg, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /stats command: %s", exc)
        await update.effective_message.reply_text("⚠️ Không thể truy vấn thống kê từ cơ sở dữ liệu.")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /clear to reset the user's Redis sliding-window chat history.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    if not update.effective_message or not update.effective_user:
        return

    redis_service: RedisService = context.bot_data["redis_service"]
    await redis_service.clear_chat_history(update.effective_user.id)
    await update.effective_message.reply_text("🧹 Đã xóa bộ nhớ ngữ cảnh hội thoại gần đây!")


async def vocab_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /vocab and /vocal: manage study schedule or lookup vocabulary DB-first.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context with bot_data services.
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    args = context.args or []

    # 1. No args: Show current learning schedule and SM-2 due status
    if not args:
        async with get_db_session() as session:
            schedule = await ScheduleService.get_schedule(session, user_id)
            due_stmt = (
                select(func.count(VocabGroundTruth.id))
                .where(
                    VocabGroundTruth.telegram_user_id == user_id,
                    VocabGroundTruth.next_review_at <= datetime.now(timezone.utc),
                )
            )
            due_count = (await session.execute(due_stmt)).scalar() or 0

            total_stmt = (
                select(func.count(VocabGroundTruth.id))
                .where(VocabGroundTruth.telegram_user_id == user_id)
            )
            total_user_words = (await session.execute(total_stmt)).scalar() or 0

        goal_str = f"{schedule.daily_new_words} từ/ngày lúc {schedule.reminder_hour:02d}:{schedule.reminder_minute:02d}" if schedule else "Chưa đặt lịch (dùng /vocab schedule)"
        msg = (
            "📖 <b>Lịch Học & Ôn Tập Từ Vựng Cá Nhân</b>\n\n"
            f"🎯 <b>Mục tiêu hằng ngày:</b> {goal_str}\n"
            f"📚 <b>Tổng số từ của bạn:</b> {total_user_words}\n"
            f"⏰ <b>Số từ đến hạn ôn hôm nay:</b> <b>{due_count}</b> từ\n\n"
            "💡 <i>Gợi ý lệnh:</i>\n"
            "• <code>/vocab schedule 5 20:00</code> — Đặt lịch học 5 từ/ngày lúc 20h\n"
            "• <code>/vocab [từ hoặc câu]</code> — Tra cứu từ vựng DB-First\n"
            "• <code>/quiz</code> — Bắt đầu ôn tập từ vựng ngay bây giờ"
        )
        await update.effective_message.reply_text(msg, parse_mode="HTML")
        return

    # 2. Schedule configuration: /vocab schedule <count> [HH:MM]
    if args[0].lower() == "schedule":
        try:
            count = int(args[1]) if len(args) > 1 else 5
            hour = 20
            minute = 0
            if len(args) > 2 and ":" in args[2]:
                parts = args[2].split(":")
                hour = int(parts[0])
                minute = int(parts[1])

            async with get_db_session() as session:
                await ScheduleService.set_schedule(
                    session=session,
                    user_id=user_id,
                    daily_new_words=count,
                    reminder_hour=hour,
                    reminder_minute=minute,
                )
                # Automatically enroll first batch from Global Seed if user has no words yet
                enrolled = await ScheduleService.enroll_daily_words_from_seed(
                    session=session,
                    user_id=user_id,
                    count=count,
                )

            enrolled_note = f"\n🎁 Đã nạp trước <b>{len(enrolled)}</b> từ đầu tiên vào kho ôn tập của bạn!" if enrolled else ""
            reply = (
                f"✅ <b>Đã cài đặt lịch học thành công!</b>\n\n"
                f"• Mục tiêu: <b>{count} từ mới/ngày</b>\n"
                f"• Giờ nhắc: <b>{hour:02d}:{minute:02d}</b> (Giờ Việt Nam)"
                f"{enrolled_note}\n\n"
                "Hãy gõ <code>/quiz</code> bất cứ lúc nào để ôn tập nhé!"
            )
            await update.effective_message.reply_text(reply, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Invalid /vocab schedule format: %s", exc)
            await update.effective_message.reply_text("⚠️ Cú pháp chưa đúng: <code>/vocab schedule 5 20:00</code>", parse_mode="HTML")
        return

    # 3. Direct DB-First Inquiry: /vocab <term or sentence>
    query_text = " ".join(args).strip()
    await _safe_send_typing(update.effective_chat)
    agent_service: StudyAgentService = context.bot_data["study_agent"]
    async with get_db_session() as session:
        reply_text, tag = await agent_service.handle_study_query(session, query_text)
    await _reply_safe_html(update.effective_message, reply_text)


async def grammar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /grammar and /gramma: list grammar patterns or query formulas DB-first.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context with bot_data services.
    """
    if not update.effective_message or not update.effective_user:
        return

    args = context.args or []

    # 1. /grammar list: Show stored grammar patterns from PostgreSQL
    if args and args[0].lower() == "list":
        async with get_db_session() as session:
            stmt = select(GrammarGroundTruth).order_by(GrammarGroundTruth.cefr_level.asc(), GrammarGroundTruth.title.asc())
            result = await session.execute(stmt)
            patterns = list(result.scalars().all())

        if not patterns:
            await update.effective_message.reply_text("📭 Hiện chưa có công thức ngữ pháp nào trong cơ sở dữ liệu.")
            return

        lines = ["📚 <b>Danh Sách Cấu Trúc Ngữ Pháp Trong Cơ Sở Dữ Liệu:</b>\n"]
        for p in patterns:
            lines.append(f"• <b>{html.escape(p.title)}</b> (<i>{html.escape(p.cefr_level)}</i>)\n  ↳ <code>{html.escape(p.formula)}</code>")

        lines.append("\n💡 <i>Tra cứu chi tiết:</i> <code>/grammar [tên công thức hoặc câu ví dụ]</code>")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # 2. No args guide
    if not args:
        guide = (
            "📐 <b>Tra Cứu Ngữ Pháp Tiếng Anh (DB-First)</b>\n\n"
            "• Gõ <code>/grammar list</code> để xem toàn bộ danh sách chủ điểm ngữ pháp trong kho.\n"
            "• Gõ <code>/grammar [câu tiếng Anh hoặc tên công thức]</code> để phân tích cấu trúc câu.\n\n"
            "<i>Ví dụ:</i>\n"
            "<code>/grammar Had I mitigated the bottleneck, would it work?</code>\n"
            "<code>/grammar Đảo ngữ câu điều kiện loại 3</code>"
        )
        await update.effective_message.reply_text(guide, parse_mode="HTML")
        return

    # 3. Direct Grammar Inquiry via Agent Router
    query_text = " ".join(args).strip()
    await _safe_send_typing(update.effective_chat)
    agent_service: StudyAgentService = context.bot_data["study_agent"]
    async with get_db_session() as session:
        reply_text, tag = await agent_service.handle_study_query(session, query_text)
    await _reply_safe_html(update.effective_message, reply_text)


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /quiz: immediately dispatch a due SM-2 vocabulary quiz for the user.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context with bot_data services.
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    now = datetime.now(timezone.utc)

    async with get_db_session() as session:
        # Check due words for this user
        stmt = (
            select(VocabGroundTruth)
            .where(
                VocabGroundTruth.telegram_user_id == user_id,
                VocabGroundTruth.next_review_at <= now,
            )
            .order_by(VocabGroundTruth.next_review_at.asc())
            .limit(1)
        )
        res = await session.execute(stmt)
        due_item = res.scalar_one_or_none()

        # If no personal word is due, offer a random unlearned global seed
        if due_item is None:
            user_words = await ScheduleService.enroll_daily_words_from_seed(session, user_id, count=1)
            if user_words:
                due_item = user_words[0]

    if due_item is None:
        await update.effective_message.reply_text(
            "🎉 <b>Tuyệt vời!</b> Bạn đã hoàn thành tất cả từ vựng cần ôn hôm nay.\n"
            "Dùng <code>/vocab schedule 5</code> để học thêm từ mới nhé!",
            parse_mode="HTML",
        )
        return

    text_msg, markup = build_quiz_message_and_markup(due_item)
    await update.effective_message.reply_text(text_msg, reply_markup=markup, parse_mode="HTML")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /report: flag inaccurate bot responses and quarantine the underlying knowledge record.

    Parameters:
        update (Update): Incoming Telegram update.
        context (ContextTypes.DEFAULT_TYPE): Callback context.
    """
    if not update.effective_message:
        return

    reply_to = update.effective_message.reply_to_message
    reason = " ".join(context.args).strip() if context.args else "Người dùng báo cáo nội dung sai"

    # Identify target word or pattern from replied text if possible
    target_text = reply_to.text if reply_to and reply_to.text else ""
    quarantined_name = ""

    async with get_db_session() as session:
        if target_text:
            # Check if any vocab matches words in the message
            vocab_stmt = select(VocabGroundTruth).where(VocabGroundTruth.status != "quarantined")
            v_res = await session.execute(vocab_stmt)
            for v in v_res.scalars().all():
                if v.word.lower() in target_text.lower():
                    v.status = "quarantined"
                    v.report_count += 1
                    quarantined_name = f"từ vựng '{v.word}'"
                    break

            if not quarantined_name:
                grammar_stmt = select(GrammarGroundTruth).where(GrammarGroundTruth.status != "quarantined")
                g_res = await session.execute(grammar_stmt)
                for g in g_res.scalars().all():
                    if g.title.lower() in target_text.lower() or g.pattern_key in target_text.lower():
                        g.status = "quarantined"
                        g.report_count += 1
                        quarantined_name = f"công thức '{g.title}'"
                        break

        await session.commit()

    detail = f" đối với {quarantined_name}" if quarantined_name else ""
    msg = (
        f"🚩 <b>Đã tiếp nhận báo cáo{detail}!</b>\n\n"
        "Bản ghi tri thức liên quan đã được chuyển sang trạng thái <code>quarantined</code> "
        "và tạm thời loại khỏi luồng tra cứu RAG chờ Quản trị viên thẩm định.\n"
        f"<i>Lý do:</i> {html.escape(reason)}\n\n"
        "Cảm ơn bạn đã giúp nâng cao chất lượng của trợ lý học tập!"
    )
    await update.effective_message.reply_text(msg, parse_mode="HTML")


