"""Worker liveness without a schema change (audit F-DOS-1).

The worker keeps one Postgres connection open and, every HEARTBEAT_S, sets that session's
`application_name` to `lw-worker hb=<unix time>`. Postgres shows it in `pg_stat_activity`, so the
API can tell three states apart:
- ok: a recent beat (the worker's event loop is running),
- stale: the connection is open but the beats stopped (a frozen worker),
- down: no worker connection at all (the process is gone)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

log = logging.getLogger("worker")

PREFIX = "lw-worker hb="
HEARTBEAT_S = 10
STALE_AFTER_S = 60


async def beat(conn: AsyncConnection) -> None:
    name = f"{PREFIX}{int(time.time())}"
    await conn.execute(text("SELECT set_config('application_name', :n, false)"), {"n": name})
    await conn.commit()


async def run_forever(database_url: str) -> None:
    """The worker's heartbeat task; reconnects if the database restarts.

    Its own engine without a pool: when the task stops, the connection really closes, so the
    beat disappears from pg_stat_activity instead of lingering on a pooled connection."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    while True:
        try:
            async with engine.connect() as conn:
                while True:
                    await beat(conn)
                    await asyncio.sleep(HEARTBEAT_S)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - database restart: try again shortly
            log.warning("heartbeat connection lost (%s); retrying", type(e).__name__)
            await asyncio.sleep(HEARTBEAT_S)


def status_from(names: Iterable[str], now: float) -> tuple[str, int | None]:
    beats = []
    for n in names:
        if n and n.startswith(PREFIX):
            try:
                beats.append(int(n[len(PREFIX) :]))
            except ValueError:
                continue
    if not beats:
        return "down", None
    age = int(now - max(beats))
    return ("ok" if age <= STALE_AFTER_S else "stale"), age


async def worker_status(session: AsyncSession) -> tuple[str, int | None]:
    rows = await session.scalars(
        # pg_stat_activity is server-wide: only this database's worker counts
        text(
            "SELECT application_name FROM pg_stat_activity"
            " WHERE application_name LIKE :p AND datname = current_database()"
        ),
        {"p": PREFIX + "%"},
    )
    return status_from(list(rows), time.time())
