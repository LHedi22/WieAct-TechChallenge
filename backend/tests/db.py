"""A separate `<name>_test` database, so tests never touch dev data. Skipped if Postgres is down."""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command

BACKEND = Path(__file__).resolve().parents[1]


def test_url(dev_url: str) -> str:
    url = make_url(dev_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


async def _ensure_database(url: str) -> bool:
    u = make_url(url)
    try:
        conn = await asyncpg.connect(
            user=u.username,
            password=u.password,
            host=u.host,
            port=u.port or 5432,
            database="postgres",
            timeout=2,
        )
    except (OSError, asyncpg.PostgresError, TimeoutError):
        return False
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", u.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()
    return True


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def prepare(url: str) -> bool:
    """Create the test database if needed and migrate it to head. False if Postgres is down."""
    if not asyncio.run(_ensure_database(url)):
        return False
    command.upgrade(alembic_config(url), "head")
    return True
