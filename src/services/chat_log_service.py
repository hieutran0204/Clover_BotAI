"""
name: chat_log_service
description: Database service for persisting ShareGPT-formatted conversation logs and querying dataset stats.
"""

from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ChatLogs


class ChatLogService:
    """Manages persistence and aggregation of conversational distillation logs."""

    @staticmethod
    async def save_chat_log(
        session: AsyncSession,
        telegram_user_id: int,
        ai_backend: str,
        model_name: str,
        prompt: str,
        response: str,
        turns_json: List[Dict[str, Any]],
    ) -> ChatLogs:
        """
        Persist a user-assistant interaction into chat_logs for future distillation.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            telegram_user_id (int): Telegram user identifier.
            ai_backend (str): Backend stage used ('gemini', 'ollama', or 'huggingface').
            model_name (str): Exact model identifier.
            prompt (str): Raw user prompt text.
            response (str): Raw assistant response text.
            turns_json (List[Dict[str, Any]]): ShareGPT multi-turn conversation list.
        Returns:
            ChatLogs: Created ORM record.
        """
        log = ChatLogs(
            telegram_user_id=telegram_user_id,
            ai_backend=ai_backend,
            model_name=model_name,
            prompt=prompt,
            response=response,
            turns_json=turns_json,
            status="raw",
        )
        session.add(log)
        await session.flush()
        return log

    @staticmethod
    async def get_status_counts(session: AsyncSession) -> Dict[str, int]:
        """
        Aggregate chat_logs row counts grouped by curation status.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
        Returns:
            Dict[str, int]: Mapping of status string to count.
        """
        stmt = select(ChatLogs.status, func.count(ChatLogs.id)).group_by(ChatLogs.status)
        result = await session.execute(stmt)
        return {str(status): int(count) for status, count in result.all()}

