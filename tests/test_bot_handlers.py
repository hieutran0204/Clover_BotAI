"""
name: test_bot_handlers
description: Unit tests for Telegram bot application wiring, quiz message formatting, and command handlers.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.app import create_application
from src.bot.handlers.command_handlers import clear_command, model_command
from src.bot.jobs.vocab_jobs import build_quiz_message_and_markup
from src.core.config import AIBackend, Settings
from src.db.models import VocabGroundTruth
from src.services.redis_service import RedisService
from tests.test_redis_service import _FakeRedis


def test_build_quiz_message_and_markup_escapes_html_and_builds_four_buttons() -> None:
    """Verify quiz formatter creates 4 callback buttons and safely escapes HTML special characters."""
    vocab = VocabGroundTruth(
        id=uuid.uuid4(),
        word="a & b <test>",
        cefr_level="B2",
        quiz_question="What does <test> mean?",
        quiz_options=["Opt 1", "Opt 2", "Opt 3", "Opt 4"],
        quiz_correct_index=2,
        definition_vi="kiểm thử",
        example_sentence="Example",
    )

    text, markup = build_quiz_message_and_markup(vocab)
    assert "a &amp; b &lt;test&gt;" in text
    assert len(markup.inline_keyboard) == 4
    assert markup.inline_keyboard[2][0].callback_data == f"quiz:{vocab.id}:2"


def test_create_application_registers_handlers_and_job() -> None:
    """Verify create_application builds PTB Application with commands, message handler, and repeating job."""
    fake_settings = Settings(telegram_bot_token="123456:FAKE_TOKEN", _env_file=None)
    with patch("src.bot.app.get_settings", return_value=fake_settings):
        app = create_application()
        assert "redis_service" in app.bot_data
        assert "ai_service" in app.bot_data
        assert "vocab_ingestion" in app.bot_data
        assert "vocab_extractor" in app.bot_data
        assert "vision_extractor" in app.bot_data
        assert "study_agent" in app.bot_data
        assert len(app.handlers[0]) == 14  # 10 commands + 1 callback + 1 photo + 1 pdf + 1 text message
        assert len(app.job_queue.jobs()) == 1


async def test_model_and_clear_commands() -> None:
    """Verify /model switches backend in Redis and /clear resets chat memory."""
    redis_service = RedisService(client=_FakeRedis())  # type: ignore[arg-type]
    await redis_service.append_chat_turn(777, "human", "hi")

    update = MagicMock()
    update.effective_user.id = 777
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot_data = {"redis_service": redis_service}
    context.args = ["ollama"]

    fake_settings = Settings(admin_user_ids=[777], _env_file=None)
    with patch("src.bot.handlers.command_handlers.get_settings", return_value=fake_settings):
        await model_command(update, context)
    assert await redis_service.get_active_backend() == AIBackend.OLLAMA

    await clear_command(update, context)
    assert await redis_service.get_chat_history(777) == []

