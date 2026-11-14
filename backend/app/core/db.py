from collections.abc import AsyncIterator
from functools import lru_cache

import asyncpg
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

# Postgres unreachable or restarting: refused/DNS (OSError), asyncpg errors, SQLAlchemy wrapper.
DB_ERRORS = (DBAPIError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)
DB_RETRY_AFTER_S = 5  # what the API tells a client to wait while the database is away (OPT-12)


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_sessionmaker()() as session:
        yield session
