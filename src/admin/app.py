"""
name: app
description: FastAPI application hosting the MVC Admin Dashboard, healthcheck, stats, and QLoRA dataset distillation management endpoints.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqladmin import Admin
from starlette.middleware.sessions import SessionMiddleware

from src.admin.auth import AdminAuth
from src.admin.controllers.auth_controller import router as auth_router
from src.admin.controllers.chat_controller import router as chat_router
from src.admin.controllers.dashboard_controller import router as dashboard_router
from src.admin.controllers.grammar_controller import router as grammar_router
from src.admin.controllers.learners_controller import router as learners_router
from src.admin.controllers.moderation_controller import router as moderation_router
from src.admin.controllers.vocab_controller import router as vocab_router
from src.admin.views import (
    ChatLogsAdmin,
    GrammarGroundTruthAdmin,
    QuizLogsAdmin,
    UserStudyScheduleAdmin,
    VocabGroundTruthAdmin,
)
from src.cli.export_dataset import export_training_dataset
from src.core.config import get_settings
from src.db.models import (
    ChatLogs,
    GrammarGroundTruth,
    UserStudySchedule,
    VocabGroundTruth,
)
from src.db.session import engine, get_db_session

logger = logging.getLogger(__name__)


def create_admin_app() -> FastAPI:
    """
    Construct and configure the FastAPI web application with MVC controllers,
    Jinja2 templates, and QLoRA dataset distillation utilities.

    Returns:
        FastAPI: Ready-to-serve application instance.
    """
    settings = get_settings()

    app = FastAPI(
        title="AI-Telegram Study Buddy Admin",
        description="Administrative MVC control hub for vocabulary, grammar, moderation, and QLoRA distillation.",
        version="2.0.0",
    )

    # 1. Mount Session Middleware for Cookie Authentication
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.admin_secret_key,
        max_age=86400 * 7,  # 7 days session
    )

    # 2. Mount Static Assets Directory
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 3. Mount Authentication Backend & SQLAdmin for Raw Table Explorer (Mounted at /admin/db)
    auth_backend = AdminAuth(
        secret_key=settings.admin_secret_key,
        username=settings.admin_username,
        password=settings.admin_password,
    )

    raw_admin = Admin(
        app=app,
        engine=engine,
        title="AI-Telegram Raw DB",
        base_url="/admin/db",
        authentication_backend=auth_backend,
    )
    raw_admin.add_view(VocabGroundTruthAdmin)
    raw_admin.add_view(GrammarGroundTruthAdmin)
    raw_admin.add_view(ChatLogsAdmin)
    raw_admin.add_view(UserStudyScheduleAdmin)
    raw_admin.add_view(QuizLogsAdmin)

    # 4. Include MVC Routers
    app.include_router(auth_router, prefix="/admin", tags=["Auth"])
    app.include_router(dashboard_router, prefix="/admin", tags=["Dashboard"])
    app.include_router(vocab_router, prefix="/admin/vocab", tags=["Vocabulary"])
    app.include_router(grammar_router, prefix="/admin/grammar", tags=["Grammar"])
    app.include_router(moderation_router, prefix="/admin/moderation", tags=["Moderation"])
    app.include_router(chat_router, prefix="/admin/chat", tags=["Chat & Distillation"])
    app.include_router(learners_router, prefix="/admin/learners", tags=["Learners"])

    # 5. Core Application Routes & APIs
    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        """Redirect root path to administrative dashboard."""
        return RedirectResponse(url="/admin")

    @app.get("/healthz", tags=["System"])
    async def healthcheck() -> Dict[str, Any]:
        """
        Service liveness and health status check.

        Returns:
            Dict[str, Any]: Health status details.
        """
        return {"status": "ok", "service": "ai-telegram-admin"}

    @app.get("/api/stats", tags=["Analytics"])
    async def get_system_stats() -> Dict[str, Any]:
        """
        Fetch real-time aggregate statistics from PostgreSQL.

        Returns:
            Dict[str, Any]: Aggregate metrics across ground truth and user learning activity.
        """
        async with get_db_session() as session:
            vocab_total = (await session.execute(select(func.count(VocabGroundTruth.id)))).scalar() or 0
            vocab_verified = (
                await session.execute(
                    select(func.count(VocabGroundTruth.id)).where(VocabGroundTruth.status == "verified")
                )
            ).scalar() or 0
            vocab_pending = (
                await session.execute(
                    select(func.count(VocabGroundTruth.id)).where(
                        VocabGroundTruth.status.in_(["pending", "quarantined"])
                    )
                )
            ).scalar() or 0

            grammar_total = (await session.execute(select(func.count(GrammarGroundTruth.id)))).scalar() or 0
            grammar_verified = (
                await session.execute(
                    select(func.count(GrammarGroundTruth.id)).where(GrammarGroundTruth.status == "verified")
                )
            ).scalar() or 0

            chat_logs_total = (await session.execute(select(func.count(ChatLogs.id)))).scalar() or 0
            active_learners = (
                await session.execute(
                    select(func.count(UserStudySchedule.telegram_user_id)).where(
                        UserStudySchedule.is_active.is_(True)
                    )
                )
            ).scalar() or 0

        return {
            "vocabulary": {
                "total": vocab_total,
                "verified": vocab_verified,
                "pending_review": vocab_pending,
            },
            "grammar": {
                "total": grammar_total,
                "verified": grammar_verified,
            },
            "chat_logs": {
                "total": chat_logs_total,
            },
            "learners": {
                "active_schedules": active_learners,
            },
        }

    @app.post("/api/export-dataset", tags=["Distillation"])
    async def trigger_dataset_export() -> Dict[str, Any]:
        """
        Execute QLoRA golden dataset export from strictly verified PostgreSQL records.

        Returns:
            Dict[str, Any]: Confirmation and target file paths.
        """
        output_dir = Path("datasets")
        await export_training_dataset(output_dir=output_dir, split_ratio=0.9)
        train_path = output_dir / "train.jsonl"
        eval_path = output_dir / "eval.jsonl"

        train_count = sum(1 for _ in open(train_path, "r", encoding="utf-8")) if train_path.exists() else 0
        eval_count = sum(1 for _ in open(eval_path, "r", encoding="utf-8")) if eval_path.exists() else 0

        return {
            "status": "success",
            "message": "Golden dataset exported successfully",
            "train_samples": train_count,
            "eval_samples": eval_count,
            "train_file": str(train_path),
            "eval_file": str(eval_path),
        }

    @app.get("/api/download-dataset/{filename}", tags=["Distillation"])
    async def download_dataset(filename: str) -> FileResponse:
        """
        Download exported dataset files (train.jsonl or eval.jsonl).

        Parameters:
            filename (str): Name of the file ('train.jsonl' or 'eval.jsonl').
        Returns:
            FileResponse: Streaming file response with attachment headers.
        """
        if filename not in ("train.jsonl", "eval.jsonl"):
            raise HTTPException(status_code=400, detail="Invalid dataset filename. Allowed: train.jsonl, eval.jsonl")

        file_path = Path("datasets") / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Dataset file '{filename}' not found. Run export first.")

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/jsonlines",
        )

    return app


app = create_admin_app()
