"""
name: vocab_service
description: Database service for managing vocabulary ground truth items, due review queries, and quiz logs.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.algorithms.sm2 import calculate_sm2
from src.db.models import QuizLogs, VocabGroundTruth


class VocabService:
    """Handles persistence and retrieval of vocabulary entries and quiz attempts."""

    @staticmethod
    async def get_due_vocab_items(
        session: AsyncSession,
        limit: int = 5,
    ) -> List[VocabGroundTruth]:
        """
        Fetch vocabulary items whose next_review_at timestamp has elapsed.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            limit (int): Maximum number of due items to retrieve.
        Returns:
            List[VocabGroundTruth]: List of vocabulary items due for review.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(VocabGroundTruth)
            .where(
                VocabGroundTruth.telegram_user_id.is_not(None),
                VocabGroundTruth.next_review_at <= now,
            )
            .order_by(VocabGroundTruth.next_review_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(session: AsyncSession, vocab_id: uuid.UUID) -> Optional[VocabGroundTruth]:
        """
        Retrieve a single vocabulary entry by primary key.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            vocab_id (uuid.UUID): Primary key of the vocabulary record.
        Returns:
            Optional[VocabGroundTruth]: Matching vocabulary record or None.
        """
        stmt = select(VocabGroundTruth).where(VocabGroundTruth.id == vocab_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def record_quiz_attempt(
        session: AsyncSession,
        vocab_id: uuid.UUID,
        telegram_user_id: int,
        selected_index: int,
    ) -> Optional[dict]:
        """
        Evaluate a user's quiz answer, record it in quiz_logs, and bump next_review_at.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            vocab_id (uuid.UUID): Identifier of the tested vocabulary item.
            telegram_user_id (int): Telegram user who answered the quiz.
            selected_index (int): Zero-based index selected via inline button.
        Returns:
            Optional[dict]: Result dictionary with correctness and explanation, or None if not found.
        """
        vocab = await VocabService.get_by_id(session, vocab_id)
        if not vocab:
            return None

        is_correct = selected_index == vocab.quiz_correct_index
        quality_score = 4 if is_correct else 1

        quiz_log = QuizLogs(
            vocab_id=vocab.id,
            telegram_user_id=telegram_user_id,
            is_correct=is_correct,
            quality_score=quality_score,
        )
        session.add(quiz_log)

        # Apply SuperMemo-2 spaced repetition algorithm
        sm2_result = calculate_sm2(
            repetition_count=vocab.repetition_count,
            ease_factor=vocab.ease_factor,
            interval_days=vocab.interval_days,
            quality=quality_score,
        )
        vocab.repetition_count = sm2_result.repetition_count
        vocab.ease_factor = sm2_result.ease_factor
        vocab.interval_days = sm2_result.interval_days
        vocab.next_review_at = sm2_result.next_review_at

        await session.flush()
        return {
            "is_correct": is_correct,
            "word": vocab.word,
            "correct_option": vocab.quiz_options[vocab.quiz_correct_index],
            "definition_vi": vocab.definition_vi,
            "example_sentence": vocab.example_sentence,
            "next_interval_days": sm2_result.interval_days,
        }

    @staticmethod
    async def count_vocab(session: AsyncSession) -> int:
        """
        Count total vocabulary records in vocab_ground_truth.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
        Returns:
            int: Total row count.
        """
        stmt = select(func.count(VocabGroundTruth.id))
        result = await session.execute(stmt)
        return int(result.scalar() or 0)

