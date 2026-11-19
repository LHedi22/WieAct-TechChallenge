"""CLIs that call the platform refuse to start beside a live worker (audit OPT-19).

The gateway's limiter (2 in flight, 20 per minute) lives in one process. The eval and reindex CLIs
build their own gateway, so beside the worker the key could see twice the calls in flight and
twice the rate. The worker rewrites its worker_status row every 2 s; a row younger than FRESH_S
means it is running."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import WorkerStatus

FRESH_S = 10.0


async def live_worker() -> str | None:
    """The id of a worker whose heartbeat is fresh, if any (its own short-lived engine: CLIs)."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine)() as s:
            return await s.scalar(
                select(WorkerStatus.worker_id).where(
                    WorkerStatus.updated_at > datetime.now(UTC) - timedelta(seconds=FRESH_S)
                )
            )
    finally:
        await engine.dispose()


def refuse_beside_worker(provider: str) -> int | None:
    """Exit code 2 (with a message) when `provider` is cloud and a worker is running."""
    if provider != "cloud":
        return None
    worker = asyncio.run(live_worker())
    if worker is None:
        return None
    print(
        f"A worker is running ({worker}) with its own limiter; together the platform would see "
        "more than 2 calls in flight. Stop it first: docker compose stop worker"
    )
    return 2
