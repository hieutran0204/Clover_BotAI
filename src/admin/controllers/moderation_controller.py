"""
name: moderation_controller
description: Controller managing the dedicated Moderation Queue for rapid 1-click review of OCR and Teacher AI extractions.
"""

import logging
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update

from src.admin.auth import require_admin
from src.db.models import VocabGroundTruth
from src.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def moderation_queue(request: Request) -> Any:
    """
    Render dedicated moderation queue cards for unverified OCR and Teacher AI entries.

    Parameters:
        request (Request): HTTP request context.
    Returns:
        HTMLResponse: Moderation queue interface.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    pending_items: List[VocabGroundTruth] = []
    async with get_db_session() as session:
        query = (
            select(VocabGroundTruth)
            .where(VocabGroundTruth.status.in_(["pending", "quarantined"]))
            .order_by(VocabGroundTruth.created_at.desc())
        )
        result = await session.execute(query)
        pending_items = list(result.scalars().all())

    user = request.session.get("admin_user", "Admin")
    return templates.TemplateResponse(
        request=request,
        name="moderation/queue.html",
        context={
            "active_page": "moderation",
            "user": user,
            "pending_items": pending_items,
            "pending_count": len(pending_items),
        },
    )


@router.post("/batch-approve")
async def batch_approve_all(request: Request) -> RedirectResponse:
    """
    Approve all currently pending records in the moderation queue in a single transaction.

    Returns:
        RedirectResponse: Redirection back to moderation queue.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        await session.execute(
            update(VocabGroundTruth)
            .where(VocabGroundTruth.status.in_(["pending", "quarantined"]))
            .values(status="verified")
        )
        await session.commit()

    return RedirectResponse(url="/admin/moderation", status_code=303)
