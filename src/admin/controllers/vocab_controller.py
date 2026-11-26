"""
name: vocab_controller
description: Controller managing vocabulary ground truth CRUD, CEFR filtering, pagination, and batch actions.
"""

import logging
import math
from pathlib import Path
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select, update

from src.admin.auth import require_admin
from src.db.models import VocabGroundTruth
from src.db.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_SIZE = 15


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_vocab(
    request: Request,
    q: Optional[str] = Query(None),
    cefr: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
) -> Any:
    """
    Render paginated vocabulary list with keyword search and filtering.

    Parameters:
        request (Request): HTTP request context.
        q (Optional[str]): Keyword query.
        cefr (Optional[str]): CEFR level.
        status (Optional[str]): Verification status.
        page (int): Current page index (1-based).
    Returns:
        HTMLResponse: Rendered list page.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    offset = (page - 1) * PAGE_SIZE
    items: List[VocabGroundTruth] = []
    total_count = 0

    async with get_db_session() as session:
        base_query = select(VocabGroundTruth)
        count_query = select(func.count(VocabGroundTruth.id))

        if q:
            keyword = f"%{q.strip().lower()}%"
            filter_clause = or_(
                func.lower(VocabGroundTruth.word).like(keyword),
                func.lower(VocabGroundTruth.definition_vi).like(keyword),
            )
            base_query = base_query.where(filter_clause)
            count_query = count_query.where(filter_clause)

        if cefr:
            base_query = base_query.where(VocabGroundTruth.cefr_level == cefr.strip().upper())
            count_query = count_query.where(VocabGroundTruth.cefr_level == cefr.strip().upper())

        if status:
            base_query = base_query.where(VocabGroundTruth.status == status.strip().lower())
            count_query = count_query.where(VocabGroundTruth.status == status.strip().lower())

        total_count = (await session.execute(count_query)).scalar() or 0

        paginated_query = (
            base_query.order_by(VocabGroundTruth.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        result = await session.execute(paginated_query)
        items = list(result.scalars().all())

    total_pages = max(1, math.ceil(total_count / PAGE_SIZE))
    user = request.session.get("admin_user", "Admin")

    return templates.TemplateResponse(
        request=request,
        name="vocab/list.html",
        context={
            "active_page": "vocab",
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


@router.get("/create", response_class=HTMLResponse)
async def create_vocab_form(request: Request) -> Any:
    """
    Render form for creating a new vocabulary record.

    Parameters:
        request (Request): HTTP request context.
    Returns:
        HTMLResponse: Form page.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    user = request.session.get("admin_user", "Admin")
    return templates.TemplateResponse(
        request=request,
        name="vocab/edit.html",
        context={"active_page": "vocab", "user": user, "item": None},
    )


@router.post("/create")
async def create_vocab_action(
    request: Request,
    word: str = Form(...),
    phonetic: Optional[str] = Form(""),
    part_of_speech: Optional[str] = Form(""),
    cefr_level: str = Form("B1"),
    definition_vi: str = Form(...),
    definition_en: Optional[str] = Form(""),
    example_sentence: Optional[str] = Form(""),
    example_translation: Optional[str] = Form(""),
    quiz_question: Optional[str] = Form(""),
    quiz_option_0: Optional[str] = Form(""),
    quiz_option_1: Optional[str] = Form(""),
    quiz_option_2: Optional[str] = Form(""),
    quiz_option_3: Optional[str] = Form(""),
    quiz_correct_index: int = Form(0),
    status: str = Form("verified"),
) -> RedirectResponse:
    """
    Persist new vocabulary entry into PostgreSQL.

    Returns:
        RedirectResponse: Redirect to vocabulary list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    quiz_options = [
        opt for opt in [quiz_option_0, quiz_option_1, quiz_option_2, quiz_option_3] if opt
    ]

    new_vocab = VocabGroundTruth(
        id=uuid.uuid4(),
        word=word.strip(),
        phonetic=phonetic.strip() if phonetic else "",
        part_of_speech=part_of_speech.strip() if part_of_speech else "n/a",
        cefr_level=cefr_level.strip().upper(),
        definition_vi=definition_vi.strip(),
        definition_en=definition_en.strip() if definition_en else "",
        example_sentence=example_sentence.strip() if example_sentence else "",
        example_translation=example_translation.strip() if example_translation else "",
        quiz_question=quiz_question.strip() if quiz_question else "",
        quiz_options=quiz_options,
        quiz_correct_index=quiz_correct_index,
        status=status.strip().lower(),
        source="admin_manual",
    )

    async with get_db_session() as session:
        session.add(new_vocab)
        await session.commit()

    return RedirectResponse(url="/admin/vocab", status_code=303)


@router.get("/{vocab_id}/edit", response_class=HTMLResponse)
async def edit_vocab_form(request: Request, vocab_id: uuid.UUID) -> Any:
    """
    Render form for modifying an existing vocabulary record.

    Parameters:
        request (Request): HTTP request context.
        vocab_id (uuid.UUID): Target record UUID.
    Returns:
        HTMLResponse: Edit form view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        vocab = await session.get(VocabGroundTruth, vocab_id)

    if not vocab:
        return RedirectResponse(url="/admin/vocab", status_code=303)

    user = request.session.get("admin_user", "Admin")
    return templates.TemplateResponse(
        request=request,
        name="vocab/edit.html",
        context={"active_page": "vocab", "user": user, "item": vocab},
    )


@router.post("/{vocab_id}/edit")
async def update_vocab_action(
    request: Request,
    vocab_id: uuid.UUID,
    word: str = Form(...),
    phonetic: Optional[str] = Form(""),
    part_of_speech: Optional[str] = Form(""),
    cefr_level: str = Form("B1"),
    definition_vi: str = Form(...),
    definition_en: Optional[str] = Form(""),
    example_sentence: Optional[str] = Form(""),
    example_translation: Optional[str] = Form(""),
    quiz_question: Optional[str] = Form(""),
    quiz_option_0: Optional[str] = Form(""),
    quiz_option_1: Optional[str] = Form(""),
    quiz_option_2: Optional[str] = Form(""),
    quiz_option_3: Optional[str] = Form(""),
    quiz_correct_index: int = Form(0),
    status: str = Form("verified"),
) -> RedirectResponse:
    """
    Update attributes of existing vocabulary record.

    Returns:
        RedirectResponse: Redirect to vocabulary list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    quiz_options = [
        opt for opt in [quiz_option_0, quiz_option_1, quiz_option_2, quiz_option_3] if opt
    ]

    async with get_db_session() as session:
        stmt = (
            update(VocabGroundTruth)
            .where(VocabGroundTruth.id == vocab_id)
            .values(
                word=word.strip(),
                phonetic=phonetic.strip() if phonetic else "",
                part_of_speech=part_of_speech.strip() if part_of_speech else "n/a",
                cefr_level=cefr_level.strip().upper(),
                definition_vi=definition_vi.strip(),
                definition_en=definition_en.strip() if definition_en else "",
                example_sentence=example_sentence.strip() if example_sentence else "",
                example_translation=example_translation.strip() if example_translation else "",
                quiz_question=quiz_question.strip() if quiz_question else "",
                quiz_options=quiz_options,
                quiz_correct_index=quiz_correct_index,
                status=status.strip().lower(),
            )
        )
        await session.execute(stmt)
        await session.commit()

    return RedirectResponse(url="/admin/vocab", status_code=303)


@router.post("/{vocab_id}/approve")
async def approve_vocab(request: Request, vocab_id: uuid.UUID) -> RedirectResponse:
    """
    Set status of vocabulary record to 'verified'.

    Returns:
        RedirectResponse: Redirection back to previous view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        await session.execute(
            update(VocabGroundTruth)
            .where(VocabGroundTruth.id == vocab_id)
            .values(status="verified")
        )
        await session.commit()

    referer = request.headers.get("referer", "/admin/vocab")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/{vocab_id}/reject")
@router.post("/{vocab_id}/delete")
async def delete_vocab(request: Request, vocab_id: uuid.UUID) -> RedirectResponse:
    """
    Delete vocabulary record from PostgreSQL.

    Returns:
        RedirectResponse: Redirection back to previous view.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    async with get_db_session() as session:
        await session.execute(delete(VocabGroundTruth).where(VocabGroundTruth.id == vocab_id))
        await session.commit()

    referer = request.headers.get("referer", "/admin/vocab")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/batch-action")
async def batch_action_vocab(
    request: Request,
    selected_ids: str = Form(""),
    action: str = Form(...),
) -> RedirectResponse:
    """
    Apply batch action (approve or reject/delete) to multiple vocabulary records.

    Parameters:
        request (Request): HTTP request context.
        selected_ids (str): Comma-separated list of UUID strings.
        action (str): Action identifier ('approve' or 'reject').
    Returns:
        RedirectResponse: Redirect back to vocabulary list.
    """
    auth_redirect = require_admin(request)
    if auth_redirect:
        return auth_redirect

    if selected_ids:
        raw_ids = [s.strip() for s in selected_ids.split(",") if s.strip()]
        parsed_uuids = []
        for raw in raw_ids:
            try:
                parsed_uuids.append(uuid.UUID(raw))
            except ValueError:
                continue

        if parsed_uuids:
            async with get_db_session() as session:
                if action == "approve":
                    await session.execute(
                        update(VocabGroundTruth)
                        .where(VocabGroundTruth.id.in_(parsed_uuids))
                        .values(status="verified")
                    )
                elif action == "reject":
                    await session.execute(
                        delete(VocabGroundTruth).where(VocabGroundTruth.id.in_(parsed_uuids))
                    )
                await session.commit()

    return RedirectResponse(url="/admin/vocab", status_code=303)
