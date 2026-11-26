"""Phase 3 schema: data governance, pg_trgm FTS, grammar_ground_truth, and user_study_schedules.

Revision ID: 002_phase3_schema
Revises: 001_initial
Create Date: 2026-11-11

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_phase3_schema"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply Phase 3 schema extensions, columns, and tables."""
    # 1. Enable pg_trgm extension for fuzzy trigram search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Add Data Governance columns to vocab_ground_truth
    op.add_column(
        "vocab_ground_truth",
        sa.Column("source", sa.String(length=50), nullable=False, server_default="global_seed"),
    )
    op.add_column(
        "vocab_ground_truth",
        sa.Column("status", sa.String(length=30), nullable=False, server_default="verified"),
    )
    op.add_column(
        "vocab_ground_truth",
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vocab_ground_truth",
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vocab_ground_truth",
        sa.Column("embedding_model", sa.String(length=100), nullable=False, server_default=""),
    )
    op.create_index("ix_vocab_ground_truth_status", "vocab_ground_truth", ["status"])

    # Backfill existing vocab rows as verified global_seed
    op.execute("UPDATE vocab_ground_truth SET source='global_seed', status='verified' WHERE source IS NULL")

    # HNSW cosine index on vocab_ground_truth embedding
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vocab_embedding_hnsw "
        "ON vocab_ground_truth USING hnsw (embedding vector_cosine_ops)"
    )

    # Postgres Full-Text Search GIN index on vocab_ground_truth
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vocab_fts_gin "
        "ON vocab_ground_truth USING gin (to_tsvector('english', word || ' ' || COALESCE(definition_vi, '')))"
    )

    # 3. Create grammar_ground_truth table
    op.create_table(
        "grammar_ground_truth",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("pattern_key", sa.String(length=120), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("usage_vi", sa.Text(), nullable=False),
        sa.Column("examples_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("common_mistakes_vi", sa.Text(), nullable=False, server_default=""),
        sa.Column("cefr_level", sa.String(length=10), nullable=False, server_default="B1"),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="global_seed"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_grammar_ground_truth_pattern_key", "grammar_ground_truth", ["pattern_key"])
    op.create_index("ix_grammar_ground_truth_telegram_user_id", "grammar_ground_truth", ["telegram_user_id"])
    op.create_index("ix_grammar_ground_truth_status", "grammar_ground_truth", ["status"])

    # HNSW cosine index on grammar_ground_truth
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_grammar_embedding_hnsw "
        "ON grammar_ground_truth USING hnsw (embedding vector_cosine_ops)"
    )

    # Postgres Full-Text Search GIN index on grammar_ground_truth
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_grammar_fts_gin "
        "ON grammar_ground_truth USING gin (to_tsvector('english', title || ' ' || formula || ' ' || usage_vi))"
    )

    # 4. Create user_study_schedules table
    op.create_table(
        "user_study_schedules",
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("daily_new_words", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("reminder_hour", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("reminder_minute", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timezone", sa.String(length=50), nullable=False, server_default="Asia/Ho_Chi_Minh"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    """Revert Phase 3 schema additions."""
    op.drop_table("user_study_schedules")
    op.execute("DROP INDEX IF EXISTS ix_grammar_fts_gin")
    op.execute("DROP INDEX IF EXISTS ix_grammar_embedding_hnsw")
    op.drop_table("grammar_ground_truth")
    op.execute("DROP INDEX IF EXISTS ix_vocab_fts_gin")
    op.execute("DROP INDEX IF EXISTS ix_vocab_embedding_hnsw")
    op.drop_index("ix_vocab_ground_truth_status", table_name="vocab_ground_truth")
    op.drop_column("vocab_ground_truth", "embedding_model")
    op.drop_column("vocab_ground_truth", "report_count")
    op.drop_column("vocab_ground_truth", "usage_count")
    op.drop_column("vocab_ground_truth", "status")
    op.drop_column("vocab_ground_truth", "source")

