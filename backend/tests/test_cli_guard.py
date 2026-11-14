"""Audit OPT-19: the gateway's limiter (2 in flight, 20 per minute) is process-local, and the eval
and reindex CLIs build their own gateway. Run against the platform beside a live worker, the key
could see 4 calls in flight and twice the rate. They now refuse to start on the cloud provider
while a worker heartbeat is fresh (worker_status is rewritten every 2 s).

Synchronous tests: the CLIs run their own event loop (asyncio.run)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import cli_guard
from app.core.config import get_settings
from app.evals.__main__ import main as evals_main
from app.models import WorkerStatus
from app.rag.reindex import main as reindex_main


def beat(pg_url, age_s: float):
    async def go():
        engine = create_async_engine(pg_url)
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE worker_status"))
        async with async_sessionmaker(engine)() as s:
            when = datetime.now(UTC) - timedelta(seconds=age_s)
            s.add(WorkerStatus(worker_id="w1", updated_at=when, data={}))
            await s.commit()
        await engine.dispose()

    asyncio.run(go())


def test_cloud_clis_refuse_beside_a_live_worker(pg_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    get_settings.cache_clear()
    beat(pg_url, age_s=1)
    called = []
    monkeypatch.setattr("app.evals.quiz_keys.run", lambda *a, **k: called.append(a))
    assert evals_main(["quiz-keys", "--cloud"]) == 2
    assert reindex_main(["--provider", "cloud"]) == 2
    assert called == []
    assert "docker compose stop worker" in capsys.readouterr().out


def test_a_stale_heartbeat_or_another_provider_is_fine(pg_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    get_settings.cache_clear()
    beat(pg_url, age_s=60)
    assert cli_guard.refuse_beside_worker("cloud") is None
    beat(pg_url, age_s=1)
    assert cli_guard.refuse_beside_worker("mock") is None
