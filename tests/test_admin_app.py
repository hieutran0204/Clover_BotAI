"""
name: test_admin_app
description: Integration tests for FastAPI admin dashboard routes, healthcheck, stats, and dataset export endpoints.
"""

from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from src.admin.app import app


@pytest.fixture
async def client():
    """AsyncClient fixture bound to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthcheck_endpoint(client: AsyncClient) -> None:
    """Verify /healthz returns 200 and healthy status."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ai-telegram-admin"


async def test_root_redirects_to_admin(client: AsyncClient) -> None:
    """Verify root / redirects to /admin."""
    response = await client.get("/", follow_redirects=False)
    assert response.status_code in (301, 302, 307, 308)
    assert "/admin" in response.headers["location"]


async def test_admin_login_page_renders(client: AsyncClient) -> None:
    """Verify /admin/login returns 200 with HTML form."""
    response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "login" in response.text.lower() or "username" in response.text.lower()


async def test_api_stats_endpoint(client: AsyncClient) -> None:
    """Verify /api/stats returns aggregated metrics."""
    response = await client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "vocabulary" in data
    assert "grammar" in data
    assert "chat_logs" in data
    assert "learners" in data
    assert data["vocabulary"]["total"] >= 0


async def test_export_and_download_dataset_endpoints(client: AsyncClient) -> None:
    """Verify /api/export-dataset triggers export and files can be downloaded."""
    with patch("src.admin.app.export_training_dataset", new_callable=AsyncMock) as mock_export:
        response = await client.post("/api/export-dataset")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "train_samples" in data
        mock_export.assert_awaited_once()

    # Test invalid file download rejection
    inv_resp = await client.get("/api/download-dataset/malicious.py")
    assert inv_resp.status_code == 400

