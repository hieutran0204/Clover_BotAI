"""
name: dashboard_controller
description: Controller rendering the primary MVC Admin Dashboard with KPI cards, health checks, and recent items.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text

from src.admin.auth import require_admin
from src.core.config import get_settings
from src.db.models import (
    ChatLogs,
    GrammarGroundTruth,
    UserStudySchedule,
    VocabGroundTruth,
)
from src.db.session import get_db_session
from src.services.redis_service import RedisService

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _check_ollama_health() -> Dict[str, Any]:
    """
    Ping Host Ollama server to inspect loaded models and operational status.

    Returns:
        Dict[str, Any]: Health status and list of discovered model tags.
    """
    settings = get_settings()
    ollama_url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(ollama_url)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return {"online": True, "models": models}
    except Exception as exc:
        logger.debug("Ollama healthcheck offline or timed out: %s", exc)
    return {"online": False, "models": []}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> Any:
    """
    Render administrator dashboard home view.

    Parameters:
        request (Request): HTTP request context.
    Returns:
        Response: HTML dashboard view or redirect to login.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    health_status: Dict[str, Any] = {
        "postgres": False,
        "redis": False,
        "ollama": False,
        "ollama_models": [],
    }

    stats: Dict[str, Any] = {
        "vocabulary": {"total": 0, "verified": 0, "pending_review": 0},
        "grammar": {"total": 0, "verified": 0},
        "chat_logs": {"total": 0},
        "learners": {"active_schedules": 0},
    }
    pending_items: List[VocabGroundTruth] = []

    try:
        async with get_db_session() as session:
            # 1. DB ping
            await session.execute(text("SELECT 1"))
            health_status["postgres"] = True

            # 2. Vocabulary stats
            stats["vocabulary"]["total"] = (
                await session.execute(select(func.count(VocabGroundTruth.id)))
            ).scalar() or 0
            stats["vocabulary"]["verified"] = (
                await session.execute(
                    select(func.count(VocabGroundTruth.id)).where(VocabGroundTruth.status == "verified")
                )
            ).scalar() or 0
            stats["vocabulary"]["pending_review"] = (
                await session.execute(
                    select(func.count(VocabGroundTruth.id)).where(
                        VocabGroundTruth.status.in_(["pending", "quarantined"])
                    )
                )
            ).scalar() or 0

            # 3. Grammar stats
            stats["grammar"]["total"] = (
                await session.execute(select(func.count(GrammarGroundTruth.id)))
            ).scalar() or 0
            stats["grammar"]["verified"] = (
                await session.execute(
                    select(func.count(GrammarGroundTruth.id)).where(GrammarGroundTruth.status == "verified")
                )
            ).scalar() or 0

            # 4. Chat & Learners
            stats["chat_logs"]["total"] = (
                await session.execute(select(func.count(ChatLogs.id)))
            ).scalar() or 0
            stats["learners"]["active_schedules"] = (
                await session.execute(
                    select(func.count(UserStudySchedule.telegram_user_id)).where(
                        UserStudySchedule.is_active.is_(True)
                    )
                )
            ).scalar() or 0

            # 5. Pending moderation sample
            pending_query = (
                select(VocabGroundTruth)
                .where(VocabGroundTruth.status.in_(["pending", "quarantined"]))
                .order_by(VocabGroundTruth.created_at.desc())
                .limit(5)
            )
            result = await session.execute(pending_query)
            pending_items = list(result.scalars().all())
    except Exception as exc:
        logger.error("Error gathering dashboard DB stats: %s", exc)

    # Redis Ping
    try:
        redis_service = RedisService()
        health_status["redis"] = await redis_service.ping()
        await redis_service.close()
    except Exception as exc:
        logger.debug("Redis ping failed: %s", exc)

    # Ollama Ping
    ollama_info = await _check_ollama_health()
    health_status["ollama"] = ollama_info["online"]
    health_status["ollama_models"] = ollama_info["models"]

    user = request.session.get("admin_user", "Admin")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_page": "dashboard",
            "user": user,
            "stats": stats,
            "health": health_status,
            "pending_count": stats["vocabulary"]["pending_review"],
            "pending_items": pending_items,
        },
    )
