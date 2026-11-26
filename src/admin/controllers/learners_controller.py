"""
name: learners_controller
description: Controller managing learner profiles, SM-2 daily goal schedules, and active reminder toggles.
"""

import logging
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update

from src.admin.auth import require_admin
from src.db.models import UserStudySchedule
from src.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_learners(request: Request) -> Any:
    """
    Render list of student SM-2 learning schedules and reminder preferences.

    Parameters:
        request (Request): HTTP request context.
    Returns:
        HTMLResponse: Learners management view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    schedules: List[UserStudySchedule] = []
    async with get_db_session() as session:
        query = select(UserStudySchedule).order_by(UserStudySchedule.created_at.desc())
        result = await session.execute(query)
        schedules = list(result.scalars().all())

    user = request.session.get("admin_user", "Admin")
    return templates.TemplateResponse(
        request=request,
        name="learners/list.html",
        context={
            "active_page": "learners",
            "user": user,
            "schedules": schedules,
        },
    )


@router.post("/{user_id}/toggle")
async def toggle_learner_schedule(request: Request, user_id: int) -> RedirectResponse:
    """
    Toggle is_active reminder state for a student schedule.

    Parameters:
        request (Request): HTTP request context.
        user_id (int): Telegram user ID.
    Returns:
        RedirectResponse: Redirection back to learners list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        schedule = await session.get(UserStudySchedule, user_id)
        if schedule:
            await session.execute(
                update(UserStudySchedule)
                .where(UserStudySchedule.telegram_user_id == user_id)
                .values(is_active=not schedule.is_active)
            )
            await session.commit()

    return RedirectResponse(url="/admin/learners", status_code=303)
