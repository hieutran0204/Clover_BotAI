"""
name: session
description: Async SQLAlchemy 2.0 engine, DeclarativeBase, and session factory for PostgreSQL.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def create_engine_from_settings() -> AsyncEngine:
    """
    Create an async SQLAlchemy engine configured from application settings.

    Returns:
        AsyncEngine: Configured PostgreSQL async engine with connection pooling.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


engine = create_engine_from_settings()
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an async transactional database session context manager.

    Yields:
        AsyncSession: Active database session that commits on clean exit or rolls back on error.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

