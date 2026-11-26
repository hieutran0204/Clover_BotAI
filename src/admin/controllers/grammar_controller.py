"""
name: grammar_controller
description: Controller managing grammar patterns ground truth, formulas, examples JSON formatting, and review.
"""

import json
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
from src.db.models import GrammarGroundTruth
from src.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 15


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_grammar(
    request: Request,
    q: Optional[str] = Query(None),
    cefr: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
) -> Any:
    """
    Render paginated grammar pattern records with search and CEFR filtering.

    Parameters:
        request (Request): HTTP request context.
        q (Optional[str]): Keyword search filter.
        cefr (Optional[str]): CEFR proficiency level filter.
        status (Optional[str]): Verification status filter.
        page (int): Page index.
    Returns:
        HTMLResponse: Rendered grammar list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    offset = (page - 1) * PAGE_SIZE
    items: List[GrammarGroundTruth] = []
    total_count = 0

    async with get_db_session() as session:
        base_query = select(GrammarGroundTruth)
        count_query = select(func.count(GrammarGroundTruth.id))

        if q:
            keyword = f"%{q.strip().lower()}%"
            filter_clause = or_(
                func.lower(GrammarGroundTruth.title).like(keyword),
                func.lower(GrammarGroundTruth.pattern_key).like(keyword),
                func.lower(GrammarGroundTruth.formula).like(keyword),
                func.lower(GrammarGroundTruth.usage_vi).like(keyword),
            )
            base_query = base_query.where(filter_clause)
            count_query = count_query.where(filter_clause)

        if cefr:
            base_query = base_query.where(GrammarGroundTruth.cefr_level == cefr.strip().upper())
            count_query = count_query.where(GrammarGroundTruth.cefr_level == cefr.strip().upper())

        if status:
            base_query = base_query.where(GrammarGroundTruth.status == status.strip().lower())
            count_query = count_query.where(GrammarGroundTruth.status == status.strip().lower())

        total_count = (await session.execute(count_query)).scalar() or 0

        paginated_query = (
            base_query.order_by(GrammarGroundTruth.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        result = await session.execute(paginated_query)
        items = list(result.scalars().all())

    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))
    user = request.session.get("admin_user", "Admin")

    return templates.TemplateResponse(
        request=request,
        name="grammar/list.html",
        context={
            "active_page": "grammar",
            "user": user,
            "items": items,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "q": q,
            "cefr": cefr,
            "status": status,
        },
    )


@router.get("/{grammar_id}/edit", response_class=HTMLResponse)
async def edit_grammar_form(request: Request, grammar_id: uuid.UUID) -> Any:
    """
    Render edit form for a grammar pattern record.

    Parameters:
        request (Request): HTTP request context.
        grammar_id (uuid.UUID): Target grammar record UUID.
    Returns:
        HTMLResponse: Form view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        grammar = await session.get(GrammarGroundTruth, grammar_id)

    if not grammar:
        return RedirectResponse(url="/admin/grammar", status_code=303)

    examples_pretty = json.dumps(grammar.examples_json or [], indent=2, ensure_ascii=False)
    user = request.session.get("admin_user", "Admin")

    return templates.TemplateResponse(
        request=request,
        name="grammar/edit.html",
        context={
            "active_page": "grammar",
            "user": user,
            "item": grammar,
            "examples_json_pretty": examples_pretty,
        },
    )


@router.post("/{grammar_id}/edit")
async def update_grammar_action(
    request: Request,
    grammar_id: uuid.UUID,
    title: str = Form(...),
    pattern_key: str = Form(...),
    cefr_level: str = Form("B1"),
    formula: str = Form(...),
    usage_vi: str = Form(...),
    examples_json_raw: str = Form("[]"),
    common_mistakes_vi: Optional[str] = Form(""),
    status: str = Form("verified"),
) -> RedirectResponse:
    """
    Persist modifications to a grammar pattern record.

    Returns:
        RedirectResponse: Redirection to grammar list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    try:
        parsed_examples = json.loads(examples_json_raw)
        if not isinstance(parsed_examples, list):
            parsed_examples = []
    except Exception:
        parsed_examples = []

    async with get_db_session() as session:
        stmt = (
            update(GrammarGroundTruth)
            .where(GrammarGroundTruth.id == grammar_id)
            .values(
                title=title.strip(),
                pattern_key=pattern_key.strip(),
                cefr_level=cefr_level.strip().upper(),
                formula=formula.strip(),
                usage_vi=usage_vi.strip(),
                examples_json=parsed_examples,
                common_mistakes_vi=common_mistakes_vi.strip() if common_mistakes_vi else "",
                status=status.strip().lower(),
            )
        )
        await session.execute(stmt)
        await session.commit()

    return RedirectResponse(url="/admin/grammar", status_code=303)


@router.post("/{grammar_id}/approve")
async def approve_grammar(request: Request, grammar_id: uuid.UUID) -> RedirectResponse:
    """
    Set status of grammar pattern record to 'verified'.

    Returns:
        RedirectResponse: Redirection back to previous view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        await session.execute(
            update(GrammarGroundTruth)
            .where(GrammarGroundTruth.id == grammar_id)
            .values(status="verified")
        )
        await session.commit()

    referer = request.headers.get("referer", "/admin/grammar")
    return RedirectResponse(url=referer, status_code=303)
