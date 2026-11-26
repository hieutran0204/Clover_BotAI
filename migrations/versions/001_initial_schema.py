"""Initial schema with pgvector extension, vocab_ground_truth, chat_logs, and quiz_logs.

Revision ID: 001_initial
Revises:
Create Date: 2026-11-11

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector extension and create core application tables."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "vocab_ground_truth",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("word", sa.String(length=120), nullable=False),
        sa.Column("phonetic", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("part_of_speech", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("definition_vi", sa.Text(), nullable=False),
        sa.Column("definition_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("example_sentence", sa.Text(), nullable=False),
        sa.Column("example_translation", sa.Text(), nullable=False, server_default=""),
        sa.Column("cefr_level", sa.String(length=10), nullable=False, server_default="B1"),
        sa.Column("quiz_question", sa.Text(), nullable=False),
        sa.Column("quiz_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quiz_correct_index", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("repetition_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vocab_ground_truth_telegram_user_id", "vocab_ground_truth", ["telegram_user_id"])
    op.create_index("ix_vocab_ground_truth_word", "vocab_ground_truth", ["word"])
    op.create_index("ix_vocab_ground_truth_next_review_at", "vocab_ground_truth", ["next_review_at"])

    op.create_table(
        "chat_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("ai_backend", sa.String(length=32), nullable=False, server_default="gemini"),
        sa.Column("model_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("turns_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="raw"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_logs_telegram_user_id", "chat_logs", ["telegram_user_id"])
    op.create_index("ix_chat_logs_status", "chat_logs", ["status"])
    op.create_index("ix_chat_logs_created_at", "chat_logs", ["created_at"])
    op.create_index("ix_chat_logs_status_created", "chat_logs", ["status", "created_at"])

    op.create_table(
        "quiz_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vocab_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vocab_ground_truth.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quiz_logs_vocab_id", "quiz_logs", ["vocab_id"])
    op.create_index("ix_quiz_logs_telegram_user_id", "quiz_logs", ["telegram_user_id"])


def downgrade() -> None:
    """Drop all application tables."""
    op.drop_table("quiz_logs")
    op.drop_table("chat_logs")
    op.drop_table("vocab_ground_truth")

