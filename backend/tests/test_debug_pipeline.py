"""Debugger, phase A: calls linked to jobs, prompt traces (off by default, capped, redacted, 24 h),
the worker heartbeat, job timelines, replays (never cloud, never counted) and the routing check."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.admin import auth
from app.core import flags
from app.core.config import get_settings
from app.core.db import get_session, get_sessionmaker
from app.gateway import GatewayError, RequestRejected, Task, TaskKind, trace
from app.gateway.context import JobRef, current_job, debug_target
from app.jobs.worker import Worker
from app.main import create_app
from app.models import AICallLog, AICallTrace, Job, User, WorkerStatus
from tests import test_jobs
from tests.admin_helpers import ACT, READ, enable_admin

gw_mock = test_jobs.gw  # the shared fixture: a gateway on the in-process mock
DEV = {"X-Dev-User": "TraceTester"}
NOTES = [{"role": "system", "content": "Write notes."}, {"role": "user", "content": "Limits"}]
# Fake secrets, built at runtime so the repo's key guard doesn't mistake them for real ones.
FAKE_BEARER = "Bear" + "er " + "abcdef123456789"
FAKE_SK = "sk" + "-proj-" + "ABCDEFGHIJKLMNOP1234"


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


async def trace_on(sm, minutes: int = 30) -> None:
    async with sm() as s:
        until = (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()
        await flags.write(s, "trace_prompts_until", until, "test")
        await s.commit()
    flags.invalidate()


async def run_demo(api, sm, lane="interactive") -> str:
    r = await api.post("/api/dev/demo-jobs", headers=DEV, json={"lane": lane})
    job_id = r.json()["job_id"]
    await Worker(sm).drain()
    return job_id


# --- privacy helpers -----------------------------------------------------------------------------
def test_redaction_removes_keys_tokens_and_the_students_nickname():
    text = (
        f"Authorization: {FAKE_BEARER} and {FAKE_SK} "
        "api_key=s3cr3tvalue admin_token: hunter2hunter2 by Yasmine22 (yasmine22)"
    )
    out = trace.redact(text, ("Yasmine22",))
    for secret in ("abcdef123456789", "ABCDEFGHIJKLMNOP", "s3cr3tvalue", "hunter2hunter2"):
        assert secret not in out
    assert "yasmine22" not in out.lower() and out.count("[student]") == 2
    assert "api_key=[redacted]" in out
    assert trace.redact("The limit of (x^2-4)/(x-2) is 4.") == "The limit of (x^2-4)/(x-2) is 4."


def test_fields_are_capped():
    assert len(trace.cap("x" * 50_000)) < trace.FIELD_CAP + 40
    msgs = trace.cap_messages(
        [{"role": "system", "content": "s" * 100}, {"role": "user", "content": "u" * 40_000}]
    )
    assert msgs[0]["content"] == "s" * 100  # a short message keeps all of it
    total = sum(len(m["content"]) for m in msgs)
    assert total <= trace.FIELD_CAP + 40 and "truncated" in msgs[1]["content"]
    assert "_truncated" in trace.cap_json({"items": ["y" * 30_000]})


# --- traces --------------------------------------------------------------------------------------
async def test_no_trace_while_the_switch_is_off(sm, gw_mock, api):
    job_id = await run_demo(api, sm)
    async with sm() as s:
        rows = list(await s.scalars(select(AICallLog)))
        assert rows and all(str(r.job_id) == job_id and r.attempt == 1 for r in rows)
        assert await s.scalar(select(AICallTrace)) is None


async def test_trace_is_written_capped_and_redacted_while_on(sm, gw_mock, api):
    await trace_on(sm)
    async with sm() as s:
        user = User(nickname="NadiaTrace", password_hash="!", ui_language="en")
        s.add(user)
        await s.commit()
    token = current_job.set(JobRef(job_id=uuid.uuid4(), attempt=1, user_id=user.id))
    try:
        await gw_mock.run(
            Task(
                kind=TaskKind.DEMO_SUMMARY,
                lane="interactive",
                messages=[
                    {"role": "system", "content": f"{FAKE_BEARER} " + "z" * 30_000},
                    {"role": "user", "content": "NadiaTrace asks: limits?"},
                ],
            )
        )
    finally:
        current_job.reset(token)
    async with sm() as s:
        t = await s.scalar(select(AICallTrace))
        assert t is not None and t.reply
        blob = str(t.messages)
        assert "abcdef123456789" not in blob and "NadiaTrace" not in blob
        assert sum(len(m["content"]) for m in t.messages) <= trace.FIELD_CAP + 40


async def test_cleanup_deletes_traces_older_than_24h(sm, gw_mock, api):
    await trace_on(sm)
    await run_demo(api, sm)
    await run_demo(api, sm)
    async with sm() as s:
        ids = list(await s.scalars(select(AICallTrace.call_log_id)))
        assert len(ids) >= 2
        await s.execute(
            update(AICallTrace)
            .where(AICallTrace.call_log_id == ids[0])
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
        await s.commit()
    assert await trace.cleanup(sm) == 1
    async with sm() as s:
        left = list(await s.scalars(select(AICallTrace.call_log_id)))
    assert ids[0] not in left and len(left) == len(ids) - 1


async def test_trace_switch_takes_minutes_and_is_bounded(sm, api):
    r = await api.put("/api/admin/switches/trace_prompts", headers=ACT, json={"value": 999})
    assert r.status_code == 422
    r = await api.put("/api/admin/switches/trace_prompts", headers=ACT, json={"value": 15})
    sw = {x["key"]: x for x in r.json()["switches"]}
    assert r.status_code == 200 and sw["trace_prompts"]["effective"] is True
    r = await api.put("/api/admin/switches/trace_prompts", headers=ACT, json={"value": 0})
    assert {x["key"]: x for x in r.json()["switches"]}["trace_prompts"]["effective"] is False


# --- heartbeat + timeline ------------------------------------------------------------------------
async def test_worker_heartbeat_reaches_live(sm, gw_mock, api):
    w = Worker(sm)
    w.gateway = gw_mock
    await w.write_status()
    async with sm() as s:
        row = await s.scalar(select(WorkerStatus))
    assert row is not None
    for key in ("in_flight", "limiter", "provider", "slot_live", "quota", "flags", "job_ids"):
        assert key in row.data, key
    assert row.data["limiter"]["concurrency"] == 2 and row.data["provider"] == "mock"
    live = (await api.get("/api/admin/debug/live", headers=READ)).json()
    assert live["workers"][0]["fresh"] and live["queue"][0]["lane"] == "interactive"


async def test_job_timeline_has_stages_calls_and_attempts(sm, gw_mock, api):
    job_id = await run_demo(api, sm)
    tl = (await api.get(f"/api/admin/debug/jobs/{job_id}", headers=READ)).json()
    types = [e["type"] for e in tl["events"]]
    assert types[0] == "created" and "claimed" in types and types[-1] == "done"
    assert [e["stage"] for e in tl["events"] if e["type"] == "stage"] == [
        "reading_chapter",
        "writing_summary",
    ]
    assert tl["calls"] and tl["calls"][0]["tier"] == "mid" and tl["calls"][0]["attempt"] == 1


async def test_a_deferral_is_on_the_timeline(sm, gw_mock, api, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_quota": 1.0})
    r = await api.post("/api/dev/demo-jobs", headers=DEV, json={"lane": "background"})
    job_id = r.json()["job_id"]
    w = Worker(sm)
    await w.tick()
    await asyncio.wait([t for ts in w.running.values() for t in ts], timeout=5)
    async with sm() as s:
        job = await s.get(Job, uuid.UUID(job_id))
    deferred = [e for e in job.events if e["type"] == "deferred"]
    assert deferred and deferred[0]["reason"] == "deferred:quota" and deferred[0]["delay_s"] > 0


async def test_single_flight_follower_is_marked(sm, gw_mock):
    task = Task(kind=TaskKind.DEMO_SUMMARY, lane="interactive", messages=NOTES, cache_key="sf-1")
    await asyncio.gather(gw_mock.run(task), gw_mock.run(task))
    async with sm() as s:
        rows = list(await s.scalars(select(AICallLog).order_by(AICallLog.id)))
    assert [r.cache_hit for r in rows] == [False, True]
    assert rows[1].single_flight and not rows[0].single_flight


# --- replay --------------------------------------------------------------------------------------
async def test_gateway_refuses_a_replay_to_cloud_or_in_production(sm, gw_mock):
    task = Task(kind=TaskKind.DEMO_SUMMARY, lane="interactive", messages=NOTES)
    token = debug_target.set("cloud")
    try:
        with pytest.raises(RequestRejected):
            await gw_mock.run(task)
    finally:
        debug_target.reset(token)
    gw_mock.settings = gw_mock.settings.model_copy(update={"APP_ENV": "production"})
    token = debug_target.set("mock")
    try:
        with pytest.raises(RequestRejected):
            await gw_mock.run(task)
    finally:
        debug_target.reset(token)
    async with sm() as s:
        assert await s.scalar(select(AICallLog)) is None  # refused before any call


async def test_replay_runs_on_mock_and_stays_out_of_the_numbers(sm, gw_mock, api):
    await trace_on(sm)
    await run_demo(api, sm)
    before = (await api.get("/api/admin/stats?provider=all", headers=READ)).json()
    routing_before = (await api.get("/api/admin/debug/routing", headers=READ)).json()
    async with sm() as s:
        call_id = await s.scalar(select(AICallLog.id).order_by(AICallLog.id))
    detail = (await api.get(f"/api/admin/debug/calls/{call_id}", headers=READ)).json()
    assert detail["trace"]["messages"] and detail["replay"]["available"]

    edited = [{"role": "system", "content": "Summarise."}, {"role": "user", "content": "Stacks"}]
    r = await api.post(
        f"/api/admin/debug/calls/{call_id}/replay",
        headers=ACT,
        json={"target": "mock", "messages": edited},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    await Worker(sm).drain()
    out = (await api.get(f"/api/admin/debug/replays/{job_id}", headers=READ)).json()
    assert out["status"] == "done" and out["edited"] and out["result"]["content"]
    async with sm() as s:
        debug_rows = list(await s.scalars(select(AICallLog).where(AICallLog.debug.is_(True))))
        job = await s.get(Job, uuid.UUID(job_id))
    assert debug_rows and all(x.provider == "mock" for x in debug_rows)
    assert "messages" not in job.payload  # the prompt left the job row once read
    after = (await api.get("/api/admin/stats?provider=all", headers=READ)).json()
    assert after["calls"] == before["calls"] and after["by_task"] == before["by_task"]
    routing_after = (await api.get("/api/admin/debug/routing", headers=READ)).json()
    assert routing_after["kinds"] == routing_before["kinds"]


async def test_replay_is_unavailable_in_production(sm, api, monkeypatch):
    for k, v in {
        "APP_ENV": "production",
        "LLM_PROVIDER": "cloud",
        "CLOUD_BASE_URL": "http://cloud.invalid/v1",
        "CLOUD_API_KEY": "test-only-not-a-key",
        "EMBED_PROVIDER": "local",
        "SECRET_KEY": "a-long-random-test-secret-for-production-mode",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    async with sm() as s:
        row = AICallLog(
            task_kind="DEMO_SUMMARY",
            model_tier="mid",
            provider="cloud",
            model="m",
            pattern="plan-once",
            status_code=200,
        )
        s.add(row)
        await s.flush()
        s.add(AICallTrace(call_log_id=row.id, messages=NOTES, reply="x", parsed=None))
        await s.commit()
    detail = (await api.get(f"/api/admin/debug/calls/{row.id}", headers=READ)).json()
    assert detail["replay"]["available"] is False
    assert "repeated identical" in detail["replay"]["reason"]
    r = await api.post(f"/api/admin/debug/calls/{row.id}/replay", headers=ACT, json={})
    assert r.status_code == 409
    async with sm() as s:
        assert await s.scalar(select(Job).where(Job.kind == "DEBUG_REPLAY")) is None


# --- routing check -------------------------------------------------------------------------------
async def test_routing_flags_mid_where_compact_and_repeats(sm, api):
    common = dict(provider="mock", model="m", status_code=200)
    notes = dict(task_kind="NOTES_WRITE", model_tier="mid", pattern="plan-once", request_hash="h1")
    async with sm() as s:
        s.add_all(
            [
                AICallLog(task_kind="CHUNK_TAG", model_tier="mid", pattern="batch", **common),
                AICallLog(task_kind="TUTOR_TURN", model_tier="mid", pattern="escalation", **common),
                AICallLog(**notes, **common),
                AICallLog(**notes, **common),
                AICallLog(**notes, debug=True, **common),
            ]
        )
        await s.commit()
    r = (await api.get("/api/admin/debug/routing", headers=READ)).json()
    kinds = {k["task_kind"]: k for k in r["kinds"]}
    assert kinds["CHUNK_TAG"]["actual"][0]["flag"] == "mid_where_compact"
    assert kinds["TUTOR_TURN"]["actual"][0]["flag"] is None  # escalation is by design
    assert r["repeats"][0]["calls"] == 2 and not r["repeats"][0]["purge_between"]  # debug left out
    assert r["flags"] == 2


async def test_debug_routes_need_the_admin(sm, api, monkeypatch):
    assert (await api.get("/api/admin/debug/live")).status_code == 401
    monkeypatch.setenv("ADMIN_TOKEN", "")
    get_settings.cache_clear()
    assert (await api.get("/api/admin/debug/live", headers=READ)).status_code == 404


# --- fixes from the constraint audit -------------------------------------------------------------
def test_redaction_catches_the_configured_keys_and_whole_word_nicknames(monkeypatch):
    odd = "zz-odd-format-key-" + "9" * 12  # a key no pattern recognises
    monkeypatch.setenv("MOCK_API_KEY", odd)
    get_settings.cache_clear()
    assert odd not in trace.redact(f"key {odd} here")
    out = trace.redact("Sam is the same as sam.", ("Sam",))
    assert out == "[student] is the same as [student]."


async def test_a_replay_never_reroutes_to_cloud_on_401(sm, gw_mock, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"blocked": True})
    gw_mock.settings = gw_mock.settings.model_copy(
        update={
            "LLM_PROVIDER": "auto",
            "LLM_SLOT_FORCE": "live",
            "CLOUD_BASE_URL": "http://cloud.invalid/v1",
            "CLOUD_API_KEY": "test-only-not-a-key",
        }
    )
    token = debug_target.set("mock")
    try:
        with pytest.raises(GatewayError):
            await gw_mock.run(Task(kind=TaskKind.DEMO_SUMMARY, lane="interactive", messages=NOTES))
    finally:
        debug_target.reset(token)
    async with sm() as s:
        providers = set(await s.scalars(select(AICallLog.provider)))
    assert providers == {"mock"}  # one 401 from the mock, nothing sent to cloud


async def test_a_deferred_replay_fails_once_and_old_replays_are_deleted(sm, gw_mock, api, mock_llm):
    await trace_on(sm)
    await run_demo(api, sm)
    async with sm() as s:
        call_id = await s.scalar(select(AICallLog.id).order_by(AICallLog.id))
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_quota": 1.0})
    r = await api.post(f"/api/admin/debug/calls/{call_id}/replay", headers=ACT, json={})
    job_id = uuid.UUID(r.json()["job_id"])
    await Worker(sm).drain()
    async with sm() as s:
        job = await s.get(Job, job_id)
        assert job.status == "failed" and job.provider == "mock"
        assert "messages" not in job.payload
        stuck = Job(
            kind="DEBUG_REPLAY",
            lane="interactive",
            status="queued",
            payload={"messages": [{"role": "user", "content": "old prompt"}]},
            created_at=datetime.now(UTC) - timedelta(hours=25),
        )
        s.add(stuck)
        await s.commit()
    await trace.cleanup(sm)
    async with sm() as s:
        assert await s.get(Job, stuck.id) is None and await s.get(Job, job_id) is not None
