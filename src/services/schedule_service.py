"""
name: schedule_service
description: Manages user daily vocabulary study schedules and automated enrollment from global seed words.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import UserStudySchedule, VocabGroundTruth

logger = logging.getLogger(__name__)


class ScheduleService:
    """Handles persistence, retrieval, and daily word enrollment for user study schedules."""

    @staticmethod
    async def get_schedule(
        session: AsyncSession,
        user_id: int,
    ) -> Optional[UserStudySchedule]:
        """
        Retrieve the study schedule configuration for a Telegram user.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            user_id (int): Telegram user ID.
        Returns:
            Optional[UserStudySchedule]: Schedule record or None if not set.
        """
        stmt = select(UserStudySchedule).where(UserStudySchedule.telegram_user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def set_schedule(
        session: AsyncSession,
        user_id: int,
        daily_new_words: int = 5,
        reminder_hour: int = 20,
        reminder_minute: int = 0,
        timezone_str: str = "Asia/Ho_Chi_Minh",
    ) -> UserStudySchedule:
        """
        Upsert a user's daily study schedule.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            user_id (int): Telegram user ID.
            daily_new_words (int): Target number of new words to learn per day.
            reminder_hour (int): Daily reminder hour (0-23).
            reminder_minute (int): Daily reminder minute (0-59).
            timezone_str (str): User timezone identifier.
        Returns:
            UserStudySchedule: Created or updated schedule record.
        """
        schedule = await ScheduleService.get_schedule(session, user_id)
        if schedule is None:
            schedule = UserStudySchedule(
                telegram_user_id=user_id,
                daily_new_words=daily_new_words,
                reminder_hour=reminder_hour,
                reminder_minute=reminder_minute,
                timezone=timezone_str,
                is_active=True,
            )
            session.add(schedule)
        else:
            schedule.daily_new_words = daily_new_words
            schedule.reminder_hour = reminder_hour
            schedule.reminder_minute = reminder_minute
            schedule.timezone = timezone_str
            schedule.is_active = True

        await session.commit()
        return schedule

    @staticmethod
    async def enroll_daily_words_from_seed(
        session: AsyncSession,
        user_id: int,
        count: int = 5,
    ) -> List[VocabGroundTruth]:
        """
        Clone unlearned global seed vocabulary items into the user's personal SM-2 queue.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            user_id (int): Telegram user ID.
            count (int): Maximum number of words to enroll.
        Returns:
            List[VocabGroundTruth]: Newly enrolled vocabulary items for the user.
        """
        # Find words user already owns
        user_words_stmt = select(func.lower(VocabGroundTruth.word)).where(
            VocabGroundTruth.telegram_user_id == user_id
        )
        user_words_res = await session.execute(user_words_stmt)
        owned_words = set(user_words_res.scalars().all())

        # Select candidate global seeds not yet owned by this user
        seed_stmt = (
            select(VocabGroundTruth)
            .where(
                VocabGroundTruth.telegram_user_id.is_(None),
                VocabGroundTruth.status == "verified",
            )
            .order_by(VocabGroundTruth.created_at.asc())
        )
        seed_res = await session.execute(seed_stmt)
        candidates = seed_res.scalars().all()

        enrolled: List[VocabGroundTruth] = []
        now = datetime.now(timezone.utc)
        for seed in candidates:
            if seed.word.lower() in owned_words:
                continue
            # Clone to personal user record
            personal_item = VocabGroundTruth(
                telegram_user_id=user_id,
                word=seed.word,
                phonetic=seed.phonetic,
                part_of_speech=seed.part_of_speech,
                definition_vi=seed.definition_vi,
                definition_en=seed.definition_en,
                example_sentence=seed.example_sentence,
                example_translation=seed.example_translation,
                cefr_level=seed.cefr_level,
                quiz_question=seed.quiz_question,
                quiz_options=seed.quiz_options,
                quiz_correct_index=seed.quiz_correct_index,
                embedding=seed.embedding,
                embedding_model=seed.embedding_model,
                source="global_seed",
                status="verified",
                next_review_at=now,
            )
            session.add(personal_item)
            enrolled.append(personal_item)
            owned_words.add(seed.word.lower())
            if len(enrolled) >= count:
                break

        if enrolled:
            await session.commit()
        return enrolled

