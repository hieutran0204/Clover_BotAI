"""
name: test_mvc_admin
description: Comprehensive integration and functional test suite for the MVC Admin Dashboard controllers and views.
"""

from typing import AsyncGenerator
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.admin.app import app
from src.core.config import get_settings
from src.db.models import GrammarGroundTruth, UserStudySchedule, VocabGroundTruth
from src.db.session import get_db_session


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    """Ensure async engine pool connections are cleanly disposed between test event loops."""
    yield
    from src.db.session import engine
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient configured for testing FastAPI endpoints with session support."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def authenticated_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an authenticated AsyncClient with signed session cookie."""
    transport = ASGITransport(app=app)
    settings = get_settings()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Perform login to establish session cookie
        login_resp = await ac.post(
            "/admin/login",
            data={"username": settings.admin_username, "password": settings.admin_password},
            follow_redirects=False,
        )
        assert login_resp.status_code == 303
        yield ac


async def test_unauthenticated_access_redirects_to_login(client: AsyncClient) -> None:
    """Verify unauthenticated requests to protected admin routes redirect to /admin/login."""
    routes = ["/admin", "/admin/vocab", "/admin/grammar", "/admin/moderation", "/admin/chat", "/admin/learners"]
    for route in routes:
        resp = await client.get(route, follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]


async def test_invalid_login_credentials_rejected(client: AsyncClient) -> None:
    """Verify invalid login submission returns 400 status with error alert."""
    resp = await client.post(
        "/admin/login",
        data={"username": "wrong_user", "password": "wrong_password"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "Tên đăng nhập hoặc mật khẩu không chính xác" in resp.text


async def test_dashboard_renders_metrics_and_health(authenticated_client: AsyncClient) -> None:
    """Verify dashboard loads with real metrics and infrastructure indicators."""
    resp = await authenticated_client.get("/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Bảng Điều Khiển Tổng Quan" in resp.text
    assert "Tổng Kho Từ Vựng" in resp.text
    assert "PostgreSQL 16" in resp.text
    assert "Redis Cache" in resp.text


async def test_vocab_crud_and_moderation_flow(authenticated_client: AsyncClient) -> None:
    """Verify creating, listing, approving, and deleting a vocabulary record via MVC controllers."""
    unique_word = f"testword_{uuid.uuid4().hex[:6]}"

    # 1. Create new word
    create_resp = await authenticated_client.post(
        "/admin/vocab/create",
        data={
            "word": unique_word,
            "phonetic": "/test/",
            "part_of_speech": "noun",
            "cefr_level": "C1",
            "definition_vi": "từ kiểm tra tự động",
            "definition_en": "automated test word",
            "example_sentence": "This is a test sentence.",
            "example_translation": "Đây là câu ví dụ.",
            "status": "pending",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303

    # 2. Check word in list view
    list_resp = await authenticated_client.get(f"/admin/vocab?q={unique_word}")
    assert list_resp.status_code == 200
    assert unique_word in list_resp.text

    # 3. Fetch created ID from DB
    async with get_db_session() as session:
        vocab = (
            await session.execute(
                select(VocabGroundTruth).where(VocabGroundTruth.word == unique_word)
            )
        ).scalar_one_or_none()
        assert vocab is not None
        assert vocab.status == "pending"
        vocab_id = vocab.id

    # 4. Check word appears in Moderation Queue
    mod_resp = await authenticated_client.get("/admin/moderation")
    assert mod_resp.status_code == 200
    assert unique_word in mod_resp.text

    # 5. Approve word via moderation endpoint
    approve_resp = await authenticated_client.post(
        f"/admin/vocab/{vocab_id}/approve",
        follow_redirects=False,
    )
    assert approve_resp.status_code == 303

    # 6. Verify status updated to verified
    async with get_db_session() as session:
        updated_vocab = await session.get(VocabGroundTruth, vocab_id)
        assert updated_vocab is not None
        assert updated_vocab.status == "verified"

    # 7. Delete word cleanup
    del_resp = await authenticated_client.post(
        f"/admin/vocab/{vocab_id}/delete",
        follow_redirects=False,
    )
    assert del_resp.status_code == 303


async def test_grammar_list_and_detail(authenticated_client: AsyncClient) -> None:
    """Verify grammar list view renders correctly with formula and CEFR badge."""
    resp = await authenticated_client.get("/admin/grammar")
    assert resp.status_code == 200
    assert "Kho Ngữ Pháp Ground Truth" in resp.text


async def test_chat_logs_and_learners_views(authenticated_client: AsyncClient) -> None:
    """Verify chat logs history and SM-2 learner schedules views render without errors."""
    chat_resp = await authenticated_client.get("/admin/chat")
    assert chat_resp.status_code == 200
    assert "Nhật Ký Hội Thoại & Chưng Cất QLoRA" in chat_resp.text

    learners_resp = await authenticated_client.get("/admin/learners")
    assert learners_resp.status_code == 200
    assert "Quản Lý Học Viên & Lịch Học SM-2" in learners_resp.text


async def test_logout_flow(authenticated_client: AsyncClient) -> None:
    """Verify logout terminates session and redirects back to login."""
    logout_resp = await authenticated_client.get("/admin/logout", follow_redirects=False)
    assert logout_resp.status_code == 303
    assert "/admin/login" in logout_resp.headers["location"]

    # Verify protected route is now blocked
    subsequent_resp = await authenticated_client.get("/admin", follow_redirects=False)
    assert subsequent_resp.status_code == 303
    assert "/admin/login" in subsequent_resp.headers["location"]
