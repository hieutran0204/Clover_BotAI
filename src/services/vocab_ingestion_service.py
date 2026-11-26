"""
name: vocab_ingestion_service
description: Unified ingestion service deduplicating vocabulary items, generating 768-dim embeddings, and persisting to PostgreSQL.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import VocabGroundTruth
from src.schemas.vocab import VocabSchema
from src.services.ai.embedding_service import EmbeddingService


@dataclass
class IngestionReport:
    """Summary of a batch vocabulary ingestion operation."""

    inserted: int = 0
    skipped_duplicates: int = 0
    inserted_words: List[str] = field(default_factory=list)
    skipped_words: List[str] = field(default_factory=list)


class VocabIngestionService:
    """Centralizes deduplication, embedding generation, and persistence for all ingestion sources."""

    def __init__(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        """
        Initialize VocabIngestionService with an EmbeddingService instance.

        Parameters:
            embedding_service (Optional[EmbeddingService]): Service used to compute pgvector embeddings.
        """
        self._embedding = embedding_service or EmbeddingService()

    @staticmethod
    def normalize_word(word: str) -> str:
        """
        Normalize a vocabulary term for case-insensitive deduplication.

        Parameters:
            word (str): Raw English word or phrase.
        Returns:
            str: Trimmed lowercase string.
        """
        return " ".join(word.strip().lower().split())

    @staticmethod
    async def get_existing_words(
        session: AsyncSession,
        telegram_user_id: Optional[int] = None,
    ) -> Set[str]:
        """
        Query existing normalized words in vocab_ground_truth for the given scope.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            telegram_user_id (Optional[int]): User ID scope, or None for global ground truth records.
        Returns:
            Set[str]: Set of normalized lowercase words already stored.
        """
        stmt = select(func.lower(VocabGroundTruth.word))
        if telegram_user_id is None:
            stmt = stmt.where(VocabGroundTruth.telegram_user_id.is_(None))
        else:
            stmt = stmt.where(VocabGroundTruth.telegram_user_id == telegram_user_id)

        result = await session.execute(stmt)
        return {VocabIngestionService.normalize_word(row[0]) for row in result.all() if row[0]}

    async def ingest_items(
        self,
        session: AsyncSession,
        items: List[VocabSchema],
        telegram_user_id: Optional[int] = None,
        review_delay_minutes: int = 5,
        source: str = "global_seed",
        status: str = "verified",
    ) -> IngestionReport:
        """
        Deduplicate incoming VocabSchema entries, compute 768-dim embeddings, and insert new rows.

        Parameters:
            session (AsyncSession): Active SQLAlchemy async session.
            items (List[VocabSchema]): Candidate vocabulary items from seeder, chat, or vision OCR.
            telegram_user_id (Optional[int]): Owner Telegram ID, or None for global seed entries.
            review_delay_minutes (int): Initial delay before the item becomes due for SM-2 quiz.
            source (str): Provenance identifier ('global_seed', 'teacher_gemini', 'passive_chat').
            status (str): Initial moderation status ('verified', 'pending').
        Returns:
            IngestionReport: Counts and word lists for inserted vs skipped duplicate items.
        """
        report = IngestionReport()
        if not items:
            return report

        existing_words = await self.get_existing_words(session, telegram_user_id=telegram_user_id)
        seen_in_batch: Set[str] = set()
        net_new_items: List[VocabSchema] = []

        for item in items:
            norm = self.normalize_word(item.word)
            if not norm or norm in existing_words or norm in seen_in_batch:
                report.skipped_duplicates += 1
                report.skipped_words.append(item.word)
                continue
            seen_in_batch.add(norm)
            net_new_items.append(item)

        if not net_new_items:
            return report

        embed_texts = [self._embedding.build_vocab_embedding_text(item) for item in net_new_items]
        embeddings = await self._embedding.embed_texts(embed_texts)

        due_time = datetime.now(timezone.utc) + timedelta(minutes=review_delay_minutes)
        model_name = self._embedding.get_model_name()
        for item, vector in zip(net_new_items, embeddings):
            record = VocabGroundTruth(
                telegram_user_id=telegram_user_id,
                word=item.word.strip(),
                phonetic=item.phonetic.strip(),
                part_of_speech=item.part_of_speech.strip(),
                definition_vi=item.definition_vi.strip(),
                definition_en=item.definition_en.strip(),
                example_sentence=item.example_sentence.strip(),
                example_translation=item.example_translation.strip(),
                cefr_level=item.cefr_level,
                quiz_question=item.quiz_question.strip(),
                quiz_options=item.quiz_options,
                quiz_correct_index=item.quiz_correct_index,
                embedding=vector,
                embedding_model=model_name,
                source=source,
                status=status,
                next_review_at=due_time,
            )
            session.add(record)
            report.inserted += 1
            report.inserted_words.append(record.word)

        await session.flush()
        return report

