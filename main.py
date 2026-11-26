"""
name: main
description: Application entrypoint that configures logging and starts Telegram bot polling.
"""

import logging

from src.bot.app import create_application
from src.core.config import get_settings


def configure_logging() -> None:
    """
    Configure root logging format and level from application settings.
    """
    settings = get_settings()
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    """
    Initialize logging and start the Telegram bot polling loop.
    """
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Knowledge Distillation Telegram AI Bot...")
    application = create_application()
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

