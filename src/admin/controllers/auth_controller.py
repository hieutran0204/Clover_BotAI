"""
name: auth_controller
description: Controller handling administrative login, authentication validation, and logout flows.
"""

import logging
from pathlib import Path
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: Optional[str] = "/admin") -> HTMLResponse:
    """
    Render administrator login page.

    Parameters:
        request (Request): HTTP request context.
        next (Optional[str]): Target path to redirect upon successful login.
    Returns:
        HTMLResponse: Rendered login page.
    """
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def process_login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: Optional[str] = Form("/admin"),
) -> Any:
    """
    Validate admin credentials and initiate session.

    Parameters:
        request (Request): HTTP request context.
        username (str): Submitted username.
        password (str): Submitted password.
        next (Optional[str]): Redirect target on success.
    Returns:
        Response: RedirectResponse on success, or HTMLResponse on failure.
    """
    settings = get_settings()
    is_valid_user = secrets.compare_digest(username.strip(), settings.admin_username)
    is_valid_pass = secrets.compare_digest(password.strip(), settings.admin_password)

    if is_valid_user and is_valid_pass:
        request.session["admin_user"] = settings.admin_username
        logger.info("Admin user '%s' logged in successfully", username)
        target = next if next and next.startswith("/admin") else "/admin"
        return RedirectResponse(url=target, status_code=303)

    logger.warning("Failed login attempt for username '%s'", username)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "next": next,
            "error": "Tên đăng nhập hoặc mật khẩu không chính xác.",
        },
        status_code=400,
    )


@router.get("/logout")
async def process_logout(request: Request) -> RedirectResponse:
    """
    Terminate administrative session and redirect to login.

    Parameters:
        request (Request): HTTP request context.
    Returns:
        RedirectResponse: Redirection to /admin/login.
    """
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)
