"""
name: vocab_jobs
description: Background JobQueue task that dispatches spaced repetition vocabulary quizzes via Telegram.
"""

import html
import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.db.models import VocabGroundTruth
from src.db.session import get_db_session
from src.services.vocab_service import VocabService

logger = logging.getLogger(__name__)


def build_quiz_message_and_markup(vocab: VocabGroundTruth) -> tuple[str, InlineKeyboardMarkup]:
    """
    Format a vocabulary quiz prompt and its 4-button inline keyboard.

    Parameters:
        vocab (VocabGroundTruth): Vocabulary ORM instance containing quiz question and options.
    Returns:
        tuple[str, InlineKeyboardMarkup]: Formatted message text and inline keyboard markup.
    """
    option_labels = ["A", "B", "C", "D"]
    lines = [
        f"🧠 <b>Ôn tập từ vựng:</b> <code>{html.escape(vocab.word)}</code> ({html.escape(vocab.cefr_level)})",
        "",
        html.escape(vocab.quiz_question),
        "",
    ]
    buttons = []
    for idx, option_text in enumerate(vocab.quiz_options):
        label = option_labels[idx] if idx < len(option_labels) else str(idx + 1)
        lines.append(f"<b>{label}.</b> {html.escape(option_text)}")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{label}. {option_text[:45]}",
                    callback_data=f"quiz:{vocab.id}:{idx}",
                )
            ]
        )

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def send_quiz_for_vocab(bot: Bot, chat_id: int, vocab: VocabGroundTruth) -> None:
    """
    Send an interactive vocabulary quiz message to a specific Telegram chat.

    Parameters:
        bot (Bot): Active Telegram Bot instance.
        chat_id (int): Target Telegram chat or user ID.
        vocab (VocabGroundTruth): Vocabulary item to quiz.
    """
    text, markup = build_quiz_message_and_markup(vocab)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="HTML",
    )


async def check_due_vocab_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Periodic JobQueue callback that checks PostgreSQL for due vocabulary reviews and sends quizzes.

    Parameters:
        context (ContextTypes.DEFAULT_TYPE): PTB job execution context.
    """
    try:
        async with get_db_session() as session:
            due_items = await VocabService.get_due_vocab_items(session, limit=5)
            for vocab in due_items:
                if not vocab.telegram_user_id:
                    continue
                try:
                    await send_quiz_for_vocab(context.bot, vocab.telegram_user_id, vocab)
                    # Snooze next_review_at to prevent re-sending before the user responds
                    vocab.next_review_at = datetime.now(timezone.utc) + timedelta(minutes=30)
                except Exception as exc:
                    logger.warning(
                        "Failed to send quiz for vocab %s to user %s: %s",
                        vocab.id,
                        vocab.telegram_user_id,
                        exc,
                    )
    except Exception as exc:
        logger.exception("Error inside check_due_vocab_job: %s", exc)
