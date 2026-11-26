"""
name: models
description: SQLAlchemy ORM models for vocabulary ground truth, distillation chat logs, and quiz history.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


class VocabGroundTruth(Base):
    """Stores structured vocabulary entries, vector embeddings, and SM-2 spaced repetition state."""

    __tablename__ = "vocab_ground_truth"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    word: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    phonetic: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    part_of_speech: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    definition_vi: Mapped[str] = mapped_column(Text, nullable=False)
    definition_en: Mapped[str] = mapped_column(Text, default="", nullable=False)
    example_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    example_translation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cefr_level: Mapped[str] = mapped_column(String(10), default="B1", nullable=False)

    # Interactive Quiz fields
    quiz_question: Mapped[str] = mapped_column(Text, nullable=False)
    quiz_options: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    quiz_correct_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Vector embedding for Hybrid RAG (768 dims for Gemini/standard sentence embeddings)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(768), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)

    # Data Governance fields
    source: Mapped[str] = mapped_column(String(50), default="global_seed", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="verified", index=True, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # SuperMemo-2 (SM-2) Spaced Repetition fields
    interval_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    repetition_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5, nullable=False)
    next_review_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    quiz_logs: Mapped[List["QuizLogs"]] = relationship(
        back_populates="vocab", cascade="all, delete-orphan"
    )


class ChatLogs(Base):
    """Stores conversational interactions in ShareGPT-compatible JSONB format for distillation."""

    __tablename__ = "chat_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    ai_backend: Mapped[str] = mapped_column(String(32), default="gemini", nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    turns_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="raw", index=True, nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    __table_args__ = (
        Index("ix_chat_logs_status_created", "status", "created_at"),
    )


class QuizLogs(Base):
    """Records user quiz responses to track learning outcomes and adjust SM-2 schedules."""

    __tablename__ = "quiz_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vocab_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vocab_ground_truth.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vocab: Mapped["VocabGroundTruth"] = relationship(back_populates="quiz_logs")


class GrammarGroundTruth(Base):
    """Stores English grammar patterns, formulas, usage guidelines, and vector embeddings for RAG."""

    __tablename__ = "grammar_ground_truth"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    pattern_key: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    usage_vi: Mapped[str] = mapped_column(Text, nullable=False)
    examples_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    common_mistakes_vi: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cefr_level: Mapped[str] = mapped_column(String(10), default="B1", nullable=False)

    # Vector embedding for Hybrid RAG
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(768), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)

    # Data Governance fields
    source: Mapped[str] = mapped_column(String(50), default="global_seed", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserStudySchedule(Base):
    """Tracks daily vocabulary learning goals and automated reminder schedules per Telegram user."""

    __tablename__ = "user_study_schedules"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    daily_new_words: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    reminder_hour: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    reminder_minute: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


