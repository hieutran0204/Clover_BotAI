"""
name: app
description: Telegram Application factory wiring services, handlers, lifecycle hooks, and JobQueue tasks.
"""

import logging

from telegram import BotCommand
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.bot.handlers.callback_handlers import handle_quiz_callback
from src.bot.handlers.command_handlers import (
    clear_command,
    grammar_command,
    help_command,
    learn_command,
    model_command,
    quiz_command,
    report_command,
    start_command,
    stats_command,
    vocab_command,
)
from src.bot.handlers.media_handlers import handle_pdf_document, handle_photo_message
from src.bot.handlers.message_handlers import handle_text_message
from src.bot.jobs.vocab_jobs import check_due_vocab_job
from src.core.config import get_settings
from src.db.session import engine
from src.services.ai.agent_service import StudyAgentService
from src.services.ai.chat_service import AIChatService
from src.services.ai.embedding_service import EmbeddingService
from src.services.ai.vision_extractor import VisionExtractorService
from src.services.ai.vocab_extractor import VocabExtractorService
from src.services.redis_service import RedisService
from src.services.vocab_ingestion_service import VocabIngestionService

logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """
    Verify Redis connectivity and register Telegram command menu after initialization.

    Parameters:
        application (Application): Initialized PTB Application instance.
    """
    redis_service: RedisService = application.bot_data["redis_service"]
    healthy = await redis_service.ping()
    logger.info("Redis connectivity check: %s", "OK" if healthy else "UNAVAILABLE (fallback mode)")

    commands = [
        BotCommand("vocab", "Lịch học & tra từ vựng DB-First"),
        BotCommand("grammar", "Tra cứu ngữ pháp & phân tích câu"),
        BotCommand("quiz", "Làm ngay 1 câu ôn tập SM-2"),
        BotCommand("report", "Báo cáo nội dung không chính xác"),
        BotCommand("learn", "Học từ vựng mới theo chủ đề"),
        BotCommand("model", "Xem / đổi tầng AI (gemini/ollama)"),
        BotCommand("stats", "Thống kê dữ liệu & Ground Truth"),
        BotCommand("clear", "Xóa bộ nhớ hội thoại gần đây"),
        BotCommand("help", "Xem hướng dẫn sử dụng"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Configured Telegram command menu (%d commands).", len(commands))
    except Exception as exc:
        logger.warning("Failed to register Telegram command menu: %s", exc)


async def _post_shutdown(application: Application) -> None:
    """
    Gracefully close Redis and PostgreSQL connection pools during shutdown.

    Parameters:
        application (Application): Stopping PTB Application instance.
    """
    redis_service: RedisService = application.bot_data["redis_service"]
    await redis_service.close()
    await engine.dispose()
    logger.info("Closed Redis and PostgreSQL connection pools.")


def create_application() -> Application:
    """
    Build and configure the Telegram Bot Application with handlers, services, and scheduled jobs.

    Returns:
        Application: Ready-to-run python-telegram-bot Application instance.
    Raises:
        ValueError: If TELEGRAM_BOT_TOKEN is missing from configuration.
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN must be configured in environment variables.")

    redis_service = RedisService()
    ai_service = AIChatService(redis_service=redis_service, settings=settings)
    embedding_service = EmbeddingService(settings=settings)
    vocab_ingestion = VocabIngestionService(embedding_service=embedding_service)
    vocab_extractor = VocabExtractorService(redis_service=redis_service)
    vision_extractor = VisionExtractorService()
    study_agent = StudyAgentService(embedding_service=embedding_service, settings=settings)

    request_config = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=20.0,
    )

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(request_config)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    async def _error_handler(update: object, ctx: object) -> None:
        err = getattr(ctx, "error", None)
        logger.error("Telegram bot error occurred: %s (update: %s)", err, update)

    application.add_error_handler(_error_handler)

    application.bot_data["redis_service"] = redis_service
    application.bot_data["ai_service"] = ai_service
    application.bot_data["vocab_ingestion"] = vocab_ingestion
    application.bot_data["vocab_extractor"] = vocab_extractor
    application.bot_data["vision_extractor"] = vision_extractor
    application.bot_data["study_agent"] = study_agent

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("learn", learn_command))
    application.add_handler(CommandHandler(["vocab", "vocal"], vocab_command))
    application.add_handler(CommandHandler(["grammar", "gramma"], grammar_command))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("clear", clear_command))

    application.add_handler(CallbackQueryHandler(handle_quiz_callback, pattern=r"^quiz:"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    if application.job_queue is not None:
        application.job_queue.run_repeating(
            check_due_vocab_job,
            interval=settings.vocab_quiz_interval_seconds,
            first=30,
        )

    return application

