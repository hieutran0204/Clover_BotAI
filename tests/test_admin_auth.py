"""
name: test_admin_auth
description: Unit tests for SQLAdmin session-based authentication backend.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.requests import Request

from src.admin.auth import AdminAuth


@pytest.fixture
def auth_backend() -> AdminAuth:
    """Fixture providing an AdminAuth instance configured with test credentials."""
    return AdminAuth(
        secret_key="test_secret_key_1234567890_test_test",
        username="admin_test",
        password="secure_password_999",
    )


def _build_mock_request(form_data: dict, session_data: dict | None = None) -> Request:
    """Helper creating a mock Starlette Request with form data and session dict."""
    req = MagicMock(spec=Request)
    req.form = AsyncMock(return_value=form_data)
    req.session = session_data if session_data is not None else {}
    req.client = "127.0.0.1"
    return req


async def test_admin_auth_login_success(auth_backend: AdminAuth) -> None:
    """Verify login succeeds and session is populated when correct credentials are provided."""
    req = _build_mock_request({"username": "admin_test", "password": "secure_password_999"})
    result = await auth_backend.login(req)
    assert result is True
    assert req.session.get("admin_user") == "admin_test"


async def test_admin_auth_login_invalid_password(auth_backend: AdminAuth) -> None:
    """Verify login fails when password is incorrect."""
    req = _build_mock_request({"username": "admin_test", "password": "wrong_password"})
    result = await auth_backend.login(req)
    assert result is False
    assert "admin_user" not in req.session


async def test_admin_auth_authenticate_valid_and_invalid(auth_backend: AdminAuth) -> None:
    """Verify authenticate inspects session correctly."""
    # Valid session
    valid_req = _build_mock_request({}, session_data={"admin_user": "admin_test"})
    assert await auth_backend.authenticate(valid_req) is True

    # Empty session
    empty_req = _build_mock_request({}, session_data={})
    assert await auth_backend.authenticate(empty_req) is False

    # Impersonated session
    impersonate_req = _build_mock_request({}, session_data={"admin_user": "hacker"})
    assert await auth_backend.authenticate(impersonate_req) is False


async def test_admin_auth_logout_clears_session(auth_backend: AdminAuth) -> None:
    """Verify logout clears the session storage."""
    req = _build_mock_request({}, session_data={"admin_user": "admin_test"})
    result = await auth_backend.logout(req)
    assert result is True
    assert len(req.session) == 0

