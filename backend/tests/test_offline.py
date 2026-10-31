"""Offline demo mode: new AI actions pause, cached results keep working, no coin moves.

Students starting an AI action get 503 `errors.offline` before anything is reserved; background
work (tagging, tips, plans, pools, indexing) is queued for the next live slot; a job caught by the
switch mid-way fails with a refund when a student waits, and waits for the slot otherwise."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

import app.gateway as gateway_module
from app.core import slot
from app.core.config import get_settings
from app.gateway import OfflineMode
from app.jobs.worker import Worker
from app.models import Job
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, pptx  # noqa: F401  (fixtures)


def go_offline(monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "on")
    get_settings.cache_clear()


async def coins(api, headers=OWL_FR) -> int:  # noqa: F811
    return (await api.get("/api/wallet", headers=headers)).json()["coins"]


async def test_status_reports_forced_offline(sm, api, monkeypatch):  # noqa: F811
    go_offline(monkeypatch)
    status = (await api.get("/api/system/status")).json()
    assert status["offline_demo_mode"] is True and status["reason"] == "forced"


async def test_paid_start_is_refused_before_any_reservation(api, sm, pptx, gw, monkeypatch):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    before = await coins(api)
    go_offline(monkeypatch)
    r = await api.post(
        "/api/tutor/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
    )
    assert r.status_code == 503 and r.json()["detail"] == "errors.offline"
    assert await coins(api) == before
    async with sm() as s:
        assert await s.scalar(select(Job).where(Job.kind == "TUTOR")) is None


async def test_cached_quiz_still_starts_offline(api, sm, pptx, gw, monkeypatch):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)  # the class's precomputed set exists
    go_offline(monkeypatch)
    r = await api.post(
        "/api/quiz/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
    )
    assert r.status_code == 200
    assert r.json()["attempt_id"] and r.json()["job_id"] is None


async def test_background_job_waits_for_the_next_slot(sm, api, monkeypatch):  # noqa: F811
    go_offline(monkeypatch)
    r = await api.post("/api/dev/demo-jobs", json={"lane": "background", "cache_key": "x"})
    assert r.status_code == 202
    async with sm() as s:
        job = await s.get(Job, r.json()["job_id"])
    nxt = slot.next_slot(datetime.now(UTC), get_settings().LLM_SLOT_GROUP)
    assert job.status == "queued" and job.not_before == nxt.start


async def offline_run(*_a, **_k):
    raise OfflineMode("outside_slot")


@pytest.mark.parametrize("lane", ["interactive", "background"])
async def test_job_caught_by_the_switch(sm, api, gw, monkeypatch, lane):  # noqa: F811
    r = await api.post("/api/dev/demo-jobs", json={"lane": lane, "cache_key": "y"})
    monkeypatch.setattr(gateway_module, "run", offline_run)
    await Worker(sm).drain(timeout_s=10)
    async with sm() as s:
        job = await s.get(Job, r.json()["job_id"])
    if lane == "interactive":  # a student is waiting: fail now (the refund hook runs)
        assert job.status == "failed" and job.error == "errors.offline"
    else:
        assert job.status == "queued" and job.error == "deferred:offline"
        assert job.not_before > datetime.now(UTC)


async def test_tutor_ends_without_a_summary_while_paused(api, sm, pptx, gw, monkeypatch):  # noqa: F811
    from tests.test_tutor import say, start

    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    await say(api, sm, sid, "on empile")
    go_offline(monkeypatch)
    r = await api.post(f"/api/tutor/{sid}/end", headers=OWL_FR)
    assert r.status_code == 200 and r.json()["job_id"] is None
    s = (await api.get(f"/api/tutor/{sid}", headers=OWL_FR)).json()
    assert s["status"] == "ended" and s["summary"] is None and s["pending_job_id"] is None
    async with sm() as db:
        summary_jobs = select(Job).where(
            Job.kind == "TUTOR", Job.payload["mode"].astext == "summary"
        )
        assert await db.scalar(summary_jobs) is None
