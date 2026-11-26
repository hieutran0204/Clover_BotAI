"""
name: chat_controller
description: Controller managing conversational chat logs review, ChatML inspection, and QLoRA dataset tagging.
"""

import logging
import math
from pathlib import Path
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, update

from src.admin.auth import require_admin
from src.db.models import ChatLogs
from src.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 15


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_chats(
    request: Request,
    q: Optional[str] = Query(None),
    backend: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
) -> Any:
    """
    Render paginated chat interactions with AI backend and verification status filters.

    Parameters:
        request (Request): HTTP request context.
        q (Optional[str]): Keyword search filter.
        backend (Optional[str]): Model backend filter ('ollama' or 'gemini').
        status (Optional[str]): Distillation verification status filter.
        page (int): Current page index.
    Returns:
        HTMLResponse: Rendered chat logs list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    offset = (page - 1) * PAGE_SIZE
    items: List[ChatLogs] = []
    total_count = 0

    async with get_db_session() as session:
        base_query = select(ChatLogs)
        count_query = select(func.count(ChatLogs.id))

        if q:
            keyword = f"%{q.strip().lower()}%"
            filter_clause = or_(
                func.lower(ChatLogs.prompt).like(keyword),
                func.lower(ChatLogs.response).like(keyword),
            )
            base_query = base_query.where(filter_clause)
            count_query = count_query.where(filter_clause)

        if backend:
            base_query = base_query.where(ChatLogs.ai_backend == backend.strip().lower())
            count_query = count_query.where(ChatLogs.ai_backend == backend.strip().lower())

        if status:
            base_query = base_query.where(ChatLogs.status == status.strip().lower())
            count_query = count_query.where(ChatLogs.status == status.strip().lower())

        total_count = (await session.execute(count_query)).scalar() or 0

        paginated_query = (
            base_query.order_by(ChatLogs.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        result = await session.execute(paginated_query)
        items = list(result.scalars().all())

    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))
    user = request.session.get("admin_user", "Admin")

    return templates.TemplateResponse(
        request=request,
        name="chat_logs/list.html",
        context={
            "active_page": "chat",
            "user": user,
            "items": items,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "q": q,
            "backend": backend,
            "status": status,
        },
    )


@router.get("/{chat_id}", response_class=HTMLResponse)
async def view_chat_detail(request: Request, chat_id: uuid.UUID) -> Any:
    """
    Render detailed speech-bubble inspection for a specific interaction log.

    Parameters:
        request (Request): HTTP request context.
        chat_id (uuid.UUID): Target chat log UUID.
    Returns:
        HTMLResponse: Rendered conversation bubble view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        log = await session.get(ChatLogs, chat_id)

    if not log:
        return RedirectResponse(url="/admin/chat", status_code=303)

    user = request.session.get("admin_user", "Admin")
    return templates.TemplateResponse(
        request=request,
        name="chat_logs/detail.html",
        context={"active_page": "chat", "user": user, "log": log},
    )


@router.post("/{chat_id}/status")
async def update_chat_status(
    request: Request,
    chat_id: uuid.UUID,
    status: str = Form(...),
) -> RedirectResponse:
    """
    Update verification status ('verified' or 'rejected') of a chat log for distillation.

    Returns:
        RedirectResponse: Redirection back to chat detail view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        await session.execute(
            update(ChatLogs)
            .where(ChatLogs.id == chat_id)
            .values(status=status.strip().lower())
        )
        await session.commit()

    return RedirectResponse(url=f"/admin/chat/{chat_id}", status_code=303)
