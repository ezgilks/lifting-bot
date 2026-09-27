"""Shared fixtures. The suite never touches Postgres, Telegram or Groq."""

from __future__ import annotations

import os

# Settings are read at import time, so the environment must be complete first.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("GROQ_MODEL", "test-model")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_SECRET", "test-secret-that-is-long-enough-for-hs256")

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base  # noqa: E402
from app.models import Unit, User  # noqa: E402
from app.seed import seed_exercises  # noqa: E402


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def seeded_session(session: AsyncSession) -> AsyncSession:
    await seed_exercises(session)
    return session


@pytest.fixture
async def user(session: AsyncSession) -> User:
    record = User(telegram_chat_id=4242, display_name="Test Lifter", unit=Unit.lb)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record
