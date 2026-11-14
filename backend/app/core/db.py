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

# Anything Postgres can raise: refused/DNS (OSError), asyncpg errors, SQLAlchemy's wrapper.
DB_ERRORS = (DBAPIError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)
# Of those, the ones that mean "the database is away" (restart, failover, dropped connection),
# as opposed to a bug such as a constraint violation (audit OPT-12).
_LOST = (
    OSError,
    asyncpg.InterfaceError,
    asyncpg.PostgresConnectionError,
    asyncpg.exceptions.OperatorInterventionError,  # 57P0x: shutting down / starting up
)
DB_RETRY_AFTER_S = 5  # what the API tells a client to wait while the database is away


def is_outage(e: BaseException) -> bool:
    """True when `e` (or what it wraps) is a lost or refused database connection."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [e]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, _LOST):
            return True
        if isinstance(cur, DBAPIError) and cur.connection_invalidated:
            return True
        stack += [getattr(cur, "orig", None), cur.__cause__, cur.__context__]
    return False


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
