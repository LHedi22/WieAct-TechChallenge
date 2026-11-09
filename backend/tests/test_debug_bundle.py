"""Debugger, phase C: the debug bundle (GET /api/admin/debug/bundle + scripts/debug_bundle.py) is
redacted: no nickname, key or token, while the timeline, calls, traces, heartbeat and invariants
are there."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.admin import auth
from app.core import flags
from app.core.db import get_session, get_sessionmaker
from app.jobs.worker import Worker
from app.main import create_app
from app.models import AICallLog, AICallTrace, Job, User
from tests import test_jobs
from tests.admin_helpers import READ, enable_admin

gw_mock = test_jobs.gw  # the shared fixture: a gateway on the in-process mock
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("debug_bundle", ROOT / "scripts" / "debug_bundle.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
FAKE_BEARER = "Bear" + "er " + "zyxwvu987654321"
NICK = "SalmaBundle"


@pytest.fixture(autouse=True)
def fresh_attempts(monkeypatch):
    monkeypatch.setattr(auth, "attempts", auth.AttemptLimiter())


@pytest.fixture
def api(sm, monkeypatch):
    enable_admin(monkeypatch)
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_bundle_has_the_story_and_no_secrets(sm, gw_mock, api):
    async with sm() as s:
        until = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        await flags.write(s, "trace_prompts_until", until, "test")
        await s.commit()
    flags.invalidate()
    r = await api.post("/api/dev/demo-jobs", headers={"X-Dev-User": NICK}, json={})
    job_id = r.json()["job_id"]
    w = Worker(sm)
    w.gateway = gw_mock
    await w.write_status()  # one heartbeat snapshot
    await w.drain()
    async with sm() as s:  # plant a secret and the nickname in the stored trace and result
        t = await s.scalar(select(AICallTrace))
        t.reply = f"{t.reply} {FAKE_BEARER} written for {NICK}"
        job = await s.get(Job, uuid.UUID(job_id))
        job.result = {**(job.result or {}), "note": f"api_key=abcdef12345 {NICK}"}
        await s.commit()
        user_id = await s.scalar(select(User.id).where(User.nickname == NICK))

    out = (await api.get("/api/admin/debug/bundle", headers=READ, params={"job_id": job_id})).json()
    md = out["markdown"]
    assert out["name"].startswith(f"bundle-job-{job_id[:8]}") and out["name"].endswith(".md")
    for part in (
        "## Job DEMO_SUMMARY",
        "### Timeline",
        "claimed",
        "### Model calls (1)",
        "#### Trace of call",
        "## Worker heartbeat",
        "## Invariants for student",
    ):
        assert part in md, part
    assert "zyxwvu987654321" not in md and "abcdef12345" not in md
    assert NICK.lower() not in md.lower() and f"student {str(user_id)[:8]}" in md

    by_user = await api.get("/api/admin/debug/bundle", headers=READ, params={"user": str(user_id)})
    assert by_user.status_code == 200 and job_id in by_user.json()["markdown"]
    assert (await api.get("/api/admin/debug/bundle", headers=READ)).status_code == 422
    async with sm() as s:  # building a bundle makes no call
        assert len(list(await s.scalars(select(AICallLog)))) == 1


async def test_bundle_by_since_lists_failed_and_deferred_jobs(sm, api):
    async with sm() as s:
        s.add_all(
            [
                Job(
                    kind="QUIZ_POOL", lane="interactive", status="failed", error="errors.ai_failed"
                ),
                Job(kind="CHUNK_TAG", lane="background", status="queued", error="deferred:quota"),
                Job(kind="DEMO_SUMMARY", lane="interactive", status="done"),
            ]
        )
        await s.commit()
    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    md = (await api.get("/api/admin/debug/bundle", headers=READ, params={"since": since})).json()[
        "markdown"
    ]
    assert "Jobs: 2" in md and "QUIZ_POOL" in md and "CHUNK_TAG" in md and "DEMO_SUMMARY" not in md


def test_script_redacts_log_lines(tmp_path):
    log = tmp_path / "w.log"
    log.write_text(
        "\n".join(
            [
                "2026-11-09 INFO job aaaa-1111 deferred 30s (quota)",
                f"2026-11-09 WARNING gateway {FAKE_BEARER}",
                "2026-11-09 INFO unrelated line",
                "2026-11-09 ERROR worker password=hunter2hunter2",
            ]
        ),
        encoding="utf-8",
    )
    lines = script.log_lines(str(log), ["aaaa-1111"], None)
    assert len(lines) == 3 and not any("unrelated" in x for x in lines)
    joined = "\n".join(lines)
    assert "zyxwvu987654321" not in joined and "hunter2hunter2" not in joined
