"""Jobs end to end: API → queue → worker → gateway (in-process mock) → result, plus deferral on
quota, lane priority, cancel, failures, stale recovery and SKIP LOCKED claiming."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

import app.gateway as gateway_module
from app.core.config import Settings
from app.core.db import get_session, get_sessionmaker
from app.gateway import BadOutput, Defer
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.service import Gateway
from app.jobs import demo
from app.jobs.service import create_job
from app.jobs.worker import Worker
from app.main import create_app
from app.models import Job
from tests.conftest import mock_transport


@pytest.fixture
def gw(sm, mock_llm, monkeypatch):
    """Route `gateway.run` (used by every handler) to a gateway talking to the in-process mock."""
    g = Gateway(
        Settings(),
        sm,
        limiter=Limiter(6000, 2, burst=50),
        client_factory=lambda p: LLMClient(
            p, timeout_s=5, disable_thinking=True, http_client=mock_transport(mock_llm)
        ),
    )
    monkeypatch.setattr(gateway_module, "run", g.run)
    return g


@pytest.fixture
def api(sm):
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def get(api, job_id):
    return (await api.get(f"/api/jobs/{job_id}")).json()


async def test_demo_job_runs_end_to_end(sm, gw, api):
    created = await api.post("/api/dev/demo-jobs", json={"lane": "interactive", "language": "fr"})
    assert created.status_code == 202 and created.json()["cost"] == 0
    job_id = created.json()["job_id"]
    queued = await get(api, job_id)
    assert queued["status"] == "queued" and queued["queue_position"] == 1 and queued["eta_s"] >= 1
    assert queued["stages"] == ["reading_chapter", "writing_summary"]

    await Worker(sm).drain()
    done = await get(api, job_id)
    assert done["status"] == "done" and done["stage"] == "writing_summary"
    assert "limite" in done["result"]["summary"]["summary"]  # French fixture
    assert done["result"]["model_tier"] == "mid" and not done["quick_mode"]
    assert done["queue_position"] is None and done["error"] is None


async def test_quick_mode_reaches_the_job(sm, gw, api, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    gw._sleep = lambda _: asyncio.sleep(0)
    job_id = (await api.post("/api/dev/demo-jobs", json={})).json()["job_id"]
    await Worker(sm).drain()
    done = await get(api, job_id)
    assert done["status"] == "done" and done["quick_mode"]
    assert done["result"]["model_tier"] == "compact"


async def test_interactive_jumps_the_background_queue(sm, api):
    bg = [
        (await api.post("/api/dev/demo-jobs", json={"lane": "background"})).json()["job_id"]
        for _ in range(2)
    ]
    fg = (await api.post("/api/dev/demo-jobs", json={"lane": "interactive"})).json()["job_id"]
    assert (await get(api, fg))["queue_position"] == 1
    assert [(await get(api, j))["queue_position"] for j in bg] == [2, 3]


async def test_quota_defers_the_job_then_it_completes(sm, gw, api, monkeypatch):
    calls = {"n": 0}
    real_run = gw.run

    async def flaky(task):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Defer(0.3, "quota")
        return await real_run(task)

    monkeypatch.setattr(gateway_module, "run", flaky)
    job_id = (await api.post("/api/dev/demo-jobs", json={})).json()["job_id"]
    worker = Worker(sm)
    await worker.tick()
    await asyncio.wait(list(worker.running["interactive"]))
    waiting = await get(api, job_id)
    assert waiting["status"] == "queued" and waiting["waiting_reason"] == "quota"
    assert waiting["error"] is None and waiting["eta_s"] >= 1
    await asyncio.sleep(0.35)
    await worker.drain()
    assert (await get(api, job_id))["status"] == "done"


async def test_gateway_error_fails_the_job_with_an_i18n_key(sm, api, monkeypatch):
    async def broken(task):
        raise BadOutput("nope")

    monkeypatch.setattr(gateway_module, "run", broken)
    job_id = (await api.post("/api/dev/demo-jobs", json={})).json()["job_id"]
    await Worker(sm).drain()
    failed = await get(api, job_id)
    assert failed["status"] == "failed" and failed["error"] == "errors.ai_failed"


async def test_cancel_only_while_queued(sm, gw, api):
    job_id = (await api.post("/api/dev/demo-jobs", json={})).json()["job_id"]
    r = await api.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    await Worker(sm).drain()  # a cancelled job never runs
    assert (await get(api, job_id))["status"] == "cancelled"
    assert (await api.post(f"/api/jobs/{job_id}/cancel")).status_code == 409


async def test_unknown_job_is_404(api):
    r = await api.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["detail"] == "errors.job_not_found"


async def test_stale_running_jobs_are_requeued(sm):
    async with sm() as s:
        job = await create_job(s, kind=demo.KIND, lane="background")
        await s.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(status="running", started_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()
    assert await Worker(sm).recover_stale() == 1


async def test_two_workers_never_claim_the_same_job(sm):
    async with sm() as s:
        for _ in range(6):
            await create_job(s, kind=demo.KIND, lane="background")
    a, b = Worker(sm), Worker(sm)
    claimed = await asyncio.gather(*[w.claim("background") for w in (a, b, a, b, a, b, a)])
    ids = [j.id for j in claimed if j]
    assert len(ids) == 6 and len(set(ids)) == 6 and claimed.count(None) == 1


async def test_background_jobs_are_capped_so_interactive_can_run(sm):
    async with sm() as s:
        for _ in range(4):
            await create_job(s, kind=demo.KIND, lane="background")
        await create_job(s, kind=demo.KIND, lane="interactive")
    w = Worker(sm, background_slots=2)
    w.execute = lambda job: asyncio.sleep(10)  # keep them "running"
    started = await w.tick()
    assert started == 3 and len(w.running["background"]) == 2
    assert len(w.running["interactive"]) == 1
    for ts in w.running.values():
        for t in ts:
            t.cancel()


async def test_admin_stats_and_system_status(sm, gw, api):
    for _ in range(2):
        await api.post("/api/dev/demo-jobs", json={"cache_key": "ch1:en"})
    await Worker(sm).drain()
    stats = (await api.get("/api/admin/stats", params={"provider": "mock"})).json()
    assert stats["calls"] == 1 and stats["cache_hits"] == 1 and stats["repeated_identical"] == 0
    assert stats["by_tier"]["mid"]["calls"] == 1 and stats["compact_share"] == 0.0
    assert (await api.get("/api/admin/stats")).json()["calls"] == 0  # defaults to cloud
    status = (await api.get("/api/system/status")).json()
    assert status["provider"] == "mock" and status["offline_demo_mode"] is False


async def test_admin_token_required_when_set(sm, api, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t0ken")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert (await api.get("/api/admin/stats")).status_code == 403
    ok = await api.get("/api/admin/stats", headers={"X-Admin-Token": "t0ken"})
    assert ok.status_code == 200


async def test_jobs_store_payload(sm):
    async with sm() as s:
        job = await create_job(s, kind=demo.KIND, lane="interactive", payload={"language": "ar"})
        row = await s.scalar(select(Job).where(Job.id == job.id))
    assert row.payload == {"language": "ar"} and row.stages == [
        "reading_chapter",
        "writing_summary",
    ]


def test_every_handler_is_known_even_after_one_feature_registered_itself():
    """Regression: the API imports app.rag.indexing first; spec_for must still find the rest."""
    import subprocess
    import sys

    code = (
        "import app.rag.indexing\n"
        "from app.jobs.registry import spec_for\n"
        "for k in ('DEV_SEARCH', 'QUIZ_POOL', 'DEMO_SUMMARY', 'INDEX_DOCUMENT'): spec_for(k)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr[-500:]
