"""
name: views
description: SQLAdmin ModelView declarations for VocabGroundTruth, GrammarGroundTruth, ChatLogs, QuizLogs, and UserStudySchedule with custom batch moderation actions.
"""

import logging
import uuid
from typing import Any, List

from sqladmin import ModelView, action
from sqlalchemy import select, update
from starlette.requests import Request
from starlette.responses import RedirectResponse

from src.db.models import (
    ChatLogs,
    GrammarGroundTruth,
    QuizLogs,
    UserStudySchedule,
    VocabGroundTruth,
)
from src.services.ai.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class VocabGroundTruthAdmin(ModelView, model=VocabGroundTruth):
    """
    Administrative management view for vocabulary ground truth records and SM-2 schedules.
    """

    name = "Từ Vựng"
    name_plural = "Kho Từ Vựng (Ground Truth)"
    icon = "fa-solid fa-book-bookmark"

    # Columns displayed in tabular list
    column_list = [
        VocabGroundTruth.word,
        VocabGroundTruth.cefr_level,
        VocabGroundTruth.status,
        VocabGroundTruth.source,
        VocabGroundTruth.usage_count,
        VocabGroundTruth.report_count,
        VocabGroundTruth.next_review_at,
        VocabGroundTruth.created_at,
    ]

    # Search & Filters
    column_searchable_list = [
        VocabGroundTruth.word,
        VocabGroundTruth.definition_vi,
        VocabGroundTruth.definition_en,
    ]
    column_sortable_list = [
        VocabGroundTruth.word,
        VocabGroundTruth.cefr_level,
        VocabGroundTruth.status,
        VocabGroundTruth.usage_count,
        VocabGroundTruth.report_count,
        VocabGroundTruth.next_review_at,
        VocabGroundTruth.created_at,
    ]
    column_filters = [
        "status",
        "cefr_level",
        "source",
    ]

    # Form / Details customization
    column_details_exclude_list = [VocabGroundTruth.embedding]
    form_excluded_columns = [
        VocabGroundTruth.embedding,
        VocabGroundTruth.created_at,
        VocabGroundTruth.updated_at,
        VocabGroundTruth.quiz_logs,
    ]

    page_size = 25
    can_export = True

    @action(
        name="approve_vocab",
        label="Phê duyệt (Verified)",
        confirmation_message="Chuyển các bản ghi đã chọn sang trạng thái 'verified'?",
    )
    async def approve_vocab(self, request: Request) -> RedirectResponse:
        """
        Batch approve selected vocabulary items to verified status.

        Parameters:
            request (Request): Incoming action request containing comma-separated pks.
        Returns:
            RedirectResponse: Redirects back to vocabulary list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(VocabGroundTruth)
                    .where(VocabGroundTruth.id.in_(pks))
                    .values(status="verified")
                )
                await session.commit()
                logger.info("Admin approved %d vocabulary records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="quarantine_vocab",
        label="Cách ly (Quarantine)",
        confirmation_message="Chuyển các bản ghi đã chọn sang trạng thái 'quarantined'?",
    )
    async def quarantine_vocab(self, request: Request) -> RedirectResponse:
        """
        Batch quarantine selected vocabulary items pending review.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(VocabGroundTruth)
                    .where(VocabGroundTruth.id.in_(pks))
                    .values(status="quarantined")
                )
                await session.commit()
                logger.info("Admin quarantined %d vocabulary records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="reject_vocab",
        label="Từ chối (Reject)",
        confirmation_message="Chuyển các bản ghi đã chọn sang trạng thái 'rejected'?",
    )
    async def reject_vocab(self, request: Request) -> RedirectResponse:
        """
        Batch reject selected vocabulary items.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(VocabGroundTruth)
                    .where(VocabGroundTruth.id.in_(pks))
                    .values(status="rejected")
                )
                await session.commit()
                logger.info("Admin rejected %d vocabulary records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="reembed_vocab",
        label="Nhúng lại Vector (768-dim)",
        confirmation_message="Tính toán lại vector embedding 768 chiều nomic-embed-text cho các từ đã chọn?",
    )
    async def reembed_vocab(self, request: Request) -> RedirectResponse:
        """
        Batch recompute 768-dimensional vector embeddings for selected vocabulary records.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            embedding_service = EmbeddingService()
            async with self.session_maker() as session:
                stmt = select(VocabGroundTruth).where(VocabGroundTruth.id.in_(pks))
                res = await session.execute(stmt)
                records = list(res.scalars().all())

                for rec in records:
                    text_to_embed = f"search_document: {rec.word}: {rec.definition_en} | {rec.definition_vi} | Example: {rec.example_sentence}"
                    vec = await embedding_service.embed_document(text_to_embed)
                    if vec:
                        rec.embedding = vec
                        rec.embedding_model = embedding_service.get_model_name()
                await session.commit()
                logger.info("Admin re-embedded %d vocabulary records", len(records))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)


class GrammarGroundTruthAdmin(ModelView, model=GrammarGroundTruth):
    """
    Administrative management view for English grammar formulas, patterns, and RAG embeddings.
    """

    name = "Cấu Trúc Ngữ Pháp"
    name_plural = "Kho Ngữ Pháp (Ground Truth)"
    icon = "fa-solid fa-graduation-cap"

    column_list = [
        GrammarGroundTruth.pattern_key,
        GrammarGroundTruth.title,
        GrammarGroundTruth.cefr_level,
        GrammarGroundTruth.status,
        GrammarGroundTruth.source,
        GrammarGroundTruth.usage_count,
        GrammarGroundTruth.report_count,
        GrammarGroundTruth.created_at,
    ]

    column_searchable_list = [
        GrammarGroundTruth.pattern_key,
        GrammarGroundTruth.title,
        GrammarGroundTruth.formula,
        GrammarGroundTruth.usage_vi,
    ]
    column_sortable_list = [
        GrammarGroundTruth.pattern_key,
        GrammarGroundTruth.title,
        GrammarGroundTruth.cefr_level,
        GrammarGroundTruth.status,
        GrammarGroundTruth.usage_count,
        GrammarGroundTruth.report_count,
        GrammarGroundTruth.created_at,
    ]
    column_filters = [
        "status",
        "cefr_level",
        "source",
    ]

    column_details_exclude_list = [GrammarGroundTruth.embedding]
    form_excluded_columns = [
        GrammarGroundTruth.embedding,
        GrammarGroundTruth.created_at,
        GrammarGroundTruth.updated_at,
    ]

    page_size = 25
    can_export = True

    @action(
        name="approve_grammar",
        label="Phê duyệt (Verified)",
        confirmation_message="Chuyển các công thức ngữ pháp đã chọn sang trạng thái 'verified'?",
    )
    async def approve_grammar(self, request: Request) -> RedirectResponse:
        """
        Batch approve selected grammar patterns to verified status.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(GrammarGroundTruth)
                    .where(GrammarGroundTruth.id.in_(pks))
                    .values(status="verified")
                )
                await session.commit()
                logger.info("Admin approved %d grammar records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="quarantine_grammar",
        label="Cách ly (Quarantine)",
        confirmation_message="Chuyển các công thức đã chọn sang trạng thái 'quarantined'?",
    )
    async def quarantine_grammar(self, request: Request) -> RedirectResponse:
        """
        Batch quarantine selected grammar patterns.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(GrammarGroundTruth)
                    .where(GrammarGroundTruth.id.in_(pks))
                    .values(status="quarantined")
                )
                await session.commit()
                logger.info("Admin quarantined %d grammar records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="reject_grammar",
        label="Từ chối (Reject)",
        confirmation_message="Chuyển các công thức đã chọn sang trạng thái 'rejected'?",
    )
    async def reject_grammar(self, request: Request) -> RedirectResponse:
        """
        Batch reject selected grammar patterns.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(GrammarGroundTruth)
                    .where(GrammarGroundTruth.id.in_(pks))
                    .values(status="rejected")
                )
                await session.commit()
                logger.info("Admin rejected %d grammar records", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)

    @action(
        name="reembed_grammar",
        label="Nhúng lại Vector (768-dim)",
        confirmation_message="Tính toán lại vector embedding 768 chiều cho các công thức ngữ pháp đã chọn?",
    )
    async def reembed_grammar(self, request: Request) -> RedirectResponse:
        """
        Batch recompute 768-dimensional embeddings for selected grammar patterns.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            embedding_service = EmbeddingService()
            async with self.session_maker() as session:
                stmt = select(GrammarGroundTruth).where(GrammarGroundTruth.id.in_(pks))
                res = await session.execute(stmt)
                records = list(res.scalars().all())

                for rec in records:
                    text_to_embed = f"search_document: {rec.title} ({rec.cefr_level}): Formula: {rec.formula} | Usage: {rec.usage_vi}"
                    vec = await embedding_service.embed_document(text_to_embed)
                    if vec:
                        rec.embedding = vec
                        rec.embedding_model = embedding_service.get_model_name()
                await session.commit()
                logger.info("Admin re-embedded %d grammar records", len(records))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)


class ChatLogsAdmin(ModelView, model=ChatLogs):
    """
    Administrative log viewer inspecting user prompts, bot responses, and ShareGPT distillation turns.
    """

    name = "Nhật Ký Trò Chuyện"
    name_plural = "Lịch Sử Chat (Distillation)"
    icon = "fa-solid fa-comments"

    can_create = False
    can_delete = False

    column_list = [
        ChatLogs.id,
        ChatLogs.telegram_user_id,
        ChatLogs.ai_backend,
        ChatLogs.model_name,
        ChatLogs.status,
        ChatLogs.created_at,
    ]

    column_searchable_list = [
        ChatLogs.prompt,
        ChatLogs.response,
    ]
    column_sortable_list = [
        ChatLogs.created_at,
        ChatLogs.status,
        ChatLogs.ai_backend,
        ChatLogs.telegram_user_id,
    ]
    column_filters = [
        "status",
        "ai_backend",
        "model_name",
    ]

    page_size = 25
    can_export = True

    @action(
        name="mark_golden_turn",
        label="Duyệt Dữ Liệu Vàng (Verified)",
        confirmation_message="Đánh dấu các lượt chat đã chọn là 'verified' để xuất vào tập train QLoRA?",
    )
    async def mark_golden_turn(self, request: Request) -> RedirectResponse:
        """
        Mark selected chat turns as verified golden data for model fine-tuning.

        Parameters:
            request (Request): Action request containing pks.
        Returns:
            RedirectResponse: Redirects to list view.
        """
        pks = [uuid.UUID(pk.strip()) for pk in request.query_params.get("pks", "").split(",") if pk.strip()]
        if pks:
            async with self.session_maker() as session:
                await session.execute(
                    update(ChatLogs)
                    .where(ChatLogs.id.in_(pks))
                    .values(status="verified")
                )
                await session.commit()
                logger.info("Admin verified %d chat log records for distillation", len(pks))
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), status_code=303)


class UserStudyScheduleAdmin(ModelView, model=UserStudySchedule):
    """
    Administrative viewer and editor for student SM-2 learning goals and automated reminder times.
    """

    name = "Lịch Học"
    name_plural = "Lịch Học Của Học Viên (SM-2)"
    icon = "fa-solid fa-calendar-check"

    column_list = [
        UserStudySchedule.telegram_user_id,
        UserStudySchedule.daily_new_words,
        UserStudySchedule.reminder_hour,
        UserStudySchedule.reminder_minute,
        UserStudySchedule.is_active,
        UserStudySchedule.last_enrolled_at,
        UserStudySchedule.created_at,
    ]

    column_searchable_list = [
        UserStudySchedule.telegram_user_id,
    ]
    column_sortable_list = [
        UserStudySchedule.telegram_user_id,
        UserStudySchedule.daily_new_words,
        UserStudySchedule.is_active,
        UserStudySchedule.created_at,
    ]
    column_filters = [
        "is_active",
    ]

    page_size = 25


class QuizLogsAdmin(ModelView, model=QuizLogs):
    """
    Read-only event log recording interactive quiz answer results and SM-2 quality scores.
    """

    name = "Nhật Ký Quiz"
    name_plural = "Lịch Sử Trắc Nghiệm (SM-2)"
    icon = "fa-solid fa-circle-check"

    can_create = False
    can_edit = False

    column_list = [
        QuizLogs.id,
        QuizLogs.vocab_id,
        QuizLogs.telegram_user_id,
        QuizLogs.is_correct,
        QuizLogs.quality_score,
        QuizLogs.answered_at,
    ]

    column_sortable_list = [
        QuizLogs.answered_at,
        QuizLogs.is_correct,
        QuizLogs.quality_score,
        QuizLogs.telegram_user_id,
    ]
    column_filters = [
        "is_correct",
        "quality_score",
    ]

    page_size = 25

