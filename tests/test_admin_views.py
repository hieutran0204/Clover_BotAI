"""
name: test_admin_views
description: Unit tests for SQLAdmin ModelView batch moderation actions (approve, quarantine, reject, re-embed).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.requests import Request
from starlette.datastructures import QueryParams

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.admin.views import (
    ChatLogsAdmin,
    GrammarGroundTruthAdmin,
    VocabGroundTruthAdmin,
)
from src.core.config import get_settings
from src.db.models import ChatLogs, GrammarGroundTruth, VocabGroundTruth


@pytest.fixture
def test_session_maker():
    """Create a fresh async session maker with NullPool to avoid event loop reuse issues in pytest."""
    settings = get_settings()
    test_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    test_engine.sync_engine.dispose()


@pytest.fixture
def mock_request() -> Request:
    """Fixture providing a mock Starlette Request with active admin session."""
    settings = get_settings()
    req = MagicMock(spec=Request)
    req.url_for = MagicMock(return_value="/admin/vocab-ground-truth/list")
    req.session = {"admin_user": settings.admin_username}
    req.scope = {"session": req.session, "type": "http"}
    req.state = MagicMock()
    return req


async def test_vocab_admin_batch_actions(mock_request: Request, test_session_maker) -> None:
    """Verify approve, quarantine, and reject batch actions modify status in database."""
    vocab_admin = VocabGroundTruthAdmin()
    vocab_admin.session_maker = test_session_maker
    vocab_admin.identity = "vocab-ground-truth"

    test_id = uuid.uuid4()
    test_word = f"test_{uuid.uuid4().hex[:6]}"

    async with test_session_maker() as session:
        vocab = VocabGroundTruth(
            id=test_id,
            word=test_word,
            definition_vi="kiểm tra",
            definition_en="test",
            example_sentence="Test sentence",
            quiz_question="What is this?",
            quiz_options=["A", "B", "C", "D"],
            quiz_correct_index=0,
            status="pending",
        )
        session.add(vocab)
        await session.commit()

    try:
        # 1. Test approve_vocab
        mock_request.query_params = QueryParams(f"pks={test_id}")
        resp = await vocab_admin.approve_vocab(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            v = await session.get(VocabGroundTruth, test_id)
            assert v is not None
            assert v.status == "verified"

        # 2. Test quarantine_vocab
        resp = await vocab_admin.quarantine_vocab(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            v = await session.get(VocabGroundTruth, test_id)
            assert v is not None
            assert v.status == "quarantined"

        # 3. Test reject_vocab
        resp = await vocab_admin.reject_vocab(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            v = await session.get(VocabGroundTruth, test_id)
            assert v is not None
            assert v.status == "rejected"

    finally:
        # Cleanup test record
        async with test_session_maker() as session:
            v = await session.get(VocabGroundTruth, test_id)
            if v:
                await session.delete(v)
                await session.commit()


async def test_grammar_admin_batch_actions(mock_request: Request, test_session_maker) -> None:
    """Verify grammar admin approve and quarantine batch actions."""
    grammar_admin = GrammarGroundTruthAdmin()
    grammar_admin.session_maker = test_session_maker
    grammar_admin.identity = "grammar-ground-truth"

    test_id = uuid.uuid4()
    pattern_key = f"pattern_{uuid.uuid4().hex[:6]}"

    async with test_session_maker() as session:
        grammar = GrammarGroundTruth(
            id=test_id,
            pattern_key=pattern_key,
            title="Test Grammar",
            formula="S + V",
            usage_vi="Cách dùng thử nghiệm",
            examples_json=[{"en": "He runs", "vi": "Anh ấy chạy"}],
            status="pending",
        )
        session.add(grammar)
        await session.commit()

    try:
        mock_request.query_params = QueryParams(f"pks={test_id}")
        resp = await grammar_admin.approve_grammar(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            g = await session.get(GrammarGroundTruth, test_id)
            assert g is not None
            assert g.status == "verified"

        resp = await grammar_admin.quarantine_grammar(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            g = await session.get(GrammarGroundTruth, test_id)
            assert g is not None
            assert g.status == "quarantined"

    finally:
        async with test_session_maker() as session:
            g = await session.get(GrammarGroundTruth, test_id)
            if g:
                await session.delete(g)
                await session.commit()


async def test_chat_logs_admin_mark_golden(mock_request: Request, test_session_maker) -> None:
    """Verify chat logs admin mark_golden_turn action."""
    chat_admin = ChatLogsAdmin()
    chat_admin.session_maker = test_session_maker
    chat_admin.identity = "chat-logs"

    test_id = uuid.uuid4()
    async with test_session_maker() as session:
        chat = ChatLogs(
            id=test_id,
            telegram_user_id=12345,
            prompt="Hello",
            response="Hi there",
            turns_json=[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there"}],
            status="raw",
        )
        session.add(chat)
        await session.commit()

    try:
        mock_request.query_params = QueryParams(f"pks={test_id}")
        resp = await chat_admin.mark_golden_turn(mock_request)
        assert resp.status_code in (302, 303)

        async with test_session_maker() as session:
            c = await session.get(ChatLogs, test_id)
            assert c is not None
            assert c.status == "verified"
    finally:
        async with test_session_maker() as session:
            c = await session.get(ChatLogs, test_id)
            if c:
                await session.delete(c)
                await session.commit()
