"""
name: auth
description: Session-based authentication backend and helper utilities for the MVC Admin Dashboard.
"""

import logging
import secrets
from typing import Optional

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from src.core.config import get_settings

logger = logging.getLogger(__name__)


def is_authenticated(request: Request) -> bool:
    """
    Check if the current request has an active authenticated admin session.

    Parameters:
        request (Request): Starlette HTTP request.
    Returns:
        bool: True if authenticated admin, False otherwise.
    """
    settings = get_settings()
    user = request.session.get("admin_user")
    if not user:
        return False
    return secrets.compare_digest(str(user), settings.admin_username)


def require_admin(request: Request) -> Optional[RedirectResponse]:
    """
    Verify administrative authentication and return a redirect response if unauthorized.

    Parameters:
        request (Request): Starlette HTTP request.
    Returns:
        Optional[RedirectResponse]: Redirect to login page if unauthorized, None if valid.
    """
    if not is_authenticated(request):
        next_path = request.url.path
        return RedirectResponse(url=f"/admin/login?next={next_path}", status_code=303)
    return None


class AdminAuth(AuthenticationBackend):
    """
    Session-based authentication provider securing admin routes.
    """

    def __init__(
        self,
        secret_key: str,
        username: str,
        password: str,
    ) -> None:
        """
        Initialize the authentication backend with secure secret key and credentials.

        Parameters:
            secret_key (str): Cryptographic key used to sign session cookies.
            username (str): Authorized administrative username.
            password (str): Authorized administrative password.
        """
        super().__init__(secret_key=secret_key)
        self._username = username
        self._password = password

    async def login(self, request: Request) -> bool:
        """
        Validate incoming admin login form credentials.

        Parameters:
            request (Request): Starlette HTTP request containing submitted form data.
        Returns:
            bool: True if credentials match, False otherwise.
        """
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))

        is_valid_user = secrets.compare_digest(username, self._username)
        is_valid_pass = secrets.compare_digest(password, self._password)

        if is_valid_user and is_valid_pass:
            request.session.update({"admin_user": username})
            logger.info("Admin user '%s' logged in successfully from %s", username, request.client)
            return True

        logger.warning("Failed admin login attempt for user '%s'", username)
        return False

    async def logout(self, request: Request) -> bool:
        """
        Clear active administrative session on logout.

        Parameters:
            request (Request): Starlette HTTP request.
        Returns:
            bool: Always True indicating session cleanup.
        """
        user = request.session.get("admin_user")
        request.session.clear()
        logger.info("Admin user '%s' logged out", user)
        return True

    async def authenticate(self, request: Request) -> bool:
        """
        Verify whether the current request holds a valid signed session.

        Parameters:
            request (Request): Starlette HTTP request.
        Returns:
            bool: True if session cookie contains a valid admin identifier, False otherwise.
        """
        admin_user = request.session.get("admin_user")
        if not admin_user or not secrets.compare_digest(str(admin_user), self._username):
            return False
        return True
