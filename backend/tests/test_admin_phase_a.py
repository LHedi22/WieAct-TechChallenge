"""Admin side, phase A: who may use it, and the runtime switches (core/flags.py) that change the
API and the worker without a restart. Forced Quick mode is counted apart from real fallbacks."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.admin import auth
from app.core import flags
from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.gateway import Task, TaskKind
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.service import Gateway
from app.jobs import demo
from app.jobs.service import create_job
from app.jobs.worker import Worker
from app.main import create_app
from app.models import AdminAction, AICallLog, Job
from tests.admin_helpers import ACT, READ, TOKEN, enable_admin
from tests.conftest import mock_transport
from tests.test_jobs import gw  # noqa: F401  (fixture)

MESSAGES = [{"role": "system", "content": "Write notes."}, {"role": "user", "content": "Limits"}]
PROD = {
    "APP_ENV": "production",
    "LLM_PROVIDER": "cloud",
    "CLOUD_BASE_URL": "http://cloud.invalid/v1",
    "CLOUD_API_KEY": "test-only-not-a-key",
    "EMBED_PROVIDER": "local",
    "SECRET_KEY": "a-long-random-test-secret-for-production-mode",
}
DEV = {"X-Dev-User": "SwitchTester"}


@pytest.fixture(autouse=True)
def fresh_attempts(monkeypatch):
    monkeypatch.setattr(auth, "attempts", auth.AttemptLimiter())
    from app.admin import session  # noqa: PLC0415

    monkeypatch.setattr(session, "attempts", auth.attempts)


def api_for(sm):
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def api(sm):
    return api_for(sm)


def gateway(sm, mock_llm):
    """A second gateway, like the worker process's own."""
    return Gateway(
        Settings(),
        sm,
        client_factory=lambda p: LLMClient(
            p, timeout_s=5, disable_thinking=True, http_client=mock_transport(mock_llm)
        ),
        limiter=Limiter(6000, 2, burst=50),
        sleep=lambda _: asyncio.sleep(0),
    )


async def sign_in(api, label="Tester"):
    r = await api.post("/api/admin/session", json={"token": TOKEN, "label": label})
    assert r.status_code == 200, r.text
    return r


# --- auth -------------------------------------------------------------------------------------
async def test_blank_token_hides_every_admin_route(api):
    for method, path in [
        ("get", "/api/admin/me"),
        ("get", "/api/admin/stats"),
        ("get", "/api/admin/switches"),
        ("get", "/api/admin/force-quick"),
    ]:
        assert (await getattr(api, method)(path, headers=READ)).status_code == 404
    r = await api.post("/api/admin/session", json={"token": "anything"})
    assert r.status_code == 404


async def test_wrong_token_is_refused(api, monkeypatch):
    enable_admin(monkeypatch)
    assert (await api.get("/api/admin/me")).status_code == 401
    assert (await api.get("/api/admin/me", headers={"X-Admin-Token": "nope"})).status_code == 401
    r = await api.post("/api/admin/session", json={"token": TOKEN + "x"})
    assert r.status_code == 401 and "lw_admin" not in r.headers.get("set-cookie", "")
    me = await api.get("/api/admin/me", headers=READ)
    assert me.json() == {"actor": "script", "via": "token", "expires_at": None}


async def test_session_cookie(api, sm, monkeypatch):
    enable_admin(monkeypatch)
    r = await sign_in(api, "Hedi")
    cookie = r.headers["set-cookie"].lower()
    assert "lw_admin=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "max-age=28800" in cookie and "secure" not in cookie  # Secure only in production
    assert TOKEN not in r.text and TOKEN.lower() not in cookie  # the token never comes back
    me = await api.get("/api/admin/me")
    assert me.status_code == 200 and me.json()["actor"] == "Hedi" and me.json()["via"] == "cookie"
    async with sm() as s:
        assert [a.action for a in await s.scalars(select(AdminAction))] == ["admin.sign_in"]
    # a tampered cookie, an expired one, and one signed for a rotated token are all refused
    api.cookies.set("lw_admin", api.cookies["lw_admin"][:-2] + "xx")
    assert (await api.get("/api/admin/me")).status_code == 401
    old = auth.sign_admin("Hedi", now=datetime.now(UTC).timestamp() - auth.ADMIN_MAX_AGE_S - 5)
    api.cookies.set("lw_admin", old)
    assert (await api.get("/api/admin/me")).status_code == 401
    api.cookies.set("lw_admin", auth.sign_admin("Hedi"))
    assert (await api.get("/api/admin/me")).status_code == 200
    enable_admin(monkeypatch, TOKEN + "-rotated")
    assert (await api.get("/api/admin/me")).status_code == 401
    # signing out clears the cookie
    enable_admin(monkeypatch)
    api.cookies.clear()
    await sign_in(api)
    assert (await api.delete("/api/admin/session")).status_code == 403  # the CSRF header too
    r = await api.delete("/api/admin/session", headers={"X-Admin-Action": "1"})
    assert r.status_code == 204
    assert (await api.get("/api/admin/me")).status_code == 401


async def test_mutations_need_the_action_header(api, monkeypatch):
    enable_admin(monkeypatch)
    await sign_in(api)
    body = {"value": True, "reason": "test"}
    r = await api.put("/api/admin/switches/pause_background_lane", json=body)
    assert r.status_code == 403 and r.json()["detail"] == "errors.admin_action_header"
    r = await api.put(
        "/api/admin/switches/pause_background_lane", json=body, headers={"X-Admin-Action": "1"}
    )
    assert r.status_code == 200
    # the script header needs it too
    r = await api.post("/api/admin/force-quick", json={"minutes": 5}, headers=READ)
    assert r.status_code == 403


async def test_sign_in_is_rate_limited_per_ip(api, monkeypatch):
    enable_admin(monkeypatch)
    for _ in range(5):
        assert (await api.post("/api/admin/session", json={"token": "guess"})).status_code == 401
    r = await api.post("/api/admin/session", json={"token": TOKEN})  # even the right token
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    other = await api.post(
        "/api/admin/session", json={"token": TOKEN}, headers={"X-Forwarded-For": "10.0.0.9"}
    )
    assert other.status_code == 200


def test_attempt_window_slides():
    clock = [0.0]
    lim = auth.AttemptLimiter(clock=lambda: clock[0])
    assert all(lim.hit(("ip", "peer")) == 0 for _ in range(5))
    assert lim.hit(("ip", "peer")) > 0
    clock[0] = 61.0
    assert lim.hit(("ip", "peer")) == 0


def test_rotating_forwarded_for_is_capped_per_peer():
    lim = auth.AttemptLimiter(clock=lambda: 0.0)
    allowed = sum(lim.hit((f"10.0.0.{i}", "proxy")) == 0 for i in range(100))
    assert allowed == auth.PEER_ATTEMPTS_PER_MIN


async def test_wrong_header_tokens_are_throttled(api, monkeypatch):
    enable_admin(monkeypatch)
    codes = [
        (await api.get("/api/admin/me", headers={"X-Admin-Token": f"guess-{i}"})).status_code
        for i in range(6)
    ]
    assert codes == [401] * 5 + [429]
    # the client-written first X-Forwarded-For entry doesn't give a fresh bucket
    r = await api.get(
        "/api/admin/me", headers={"X-Admin-Token": "guess", "X-Forwarded-For": "1.2.3.4, 127.0.0.1"}
    )
    assert r.status_code in (401, 429)
    assert (await api.get("/api/admin/me", headers=READ)).status_code == 200  # right token: ok


def test_production_refuses_a_short_token(monkeypatch):
    for k, v in PROD.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ADMIN_TOKEN", "short-token")
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        Settings()
    monkeypatch.setenv("ADMIN_TOKEN", "x" * 32)
    assert Settings().ADMIN_TOKEN.get_secret_value()
    monkeypatch.setenv("ADMIN_TOKEN", "")
    assert Settings()  # blank = admin off, allowed


def test_production_still_refuses_forced_quick_mode_in_env(monkeypatch):
    for k, v in {**PROD, "FORCE_QUICK_MODE": "on"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError, match="FORCE_QUICK_MODE"):
        Settings()


async def test_production_cookie_is_secure(sm, monkeypatch):
    for k, v in PROD.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)  # auto: Secure in production
    enable_admin(monkeypatch)
    async with api_for(sm) as api:
        r = await sign_in(api)
    assert "secure" in r.headers["set-cookie"].lower()


# --- switches ---------------------------------------------------------------------------------
async def test_switches_page_shows_state_and_who_changed_it(api, sm, monkeypatch):
    enable_admin(monkeypatch)
    await sign_in(api, "Hedi")
    view = (await api.get("/api/admin/switches")).json()
    by_key = {s["key"]: s for s in view["switches"]}
    assert set(by_key) == {
        "force_quick_mode",
        "offline_demo_mode",
        "pause_background_lane",
        "llm_max_rpm_override",
    }
    assert by_key["force_quick_mode"]["effective"] is False
    assert by_key["llm_max_rpm_override"]["effective"] == 18
    assert view["provider"] == "mock" and view["llm_max_rpm"] == 18
    r = await api.put(
        "/api/admin/switches/llm_max_rpm_override",
        json={"value": 6, "reason": "rehearsal"},
        headers={"X-Admin-Action": "1"},
    )
    rpm = {s["key"]: s for s in r.json()["switches"]}["llm_max_rpm_override"]
    assert rpm["value"] == 6 and rpm["effective"] == 6 and rpm["updated_by"] == "Hedi"
    assert rpm["updated_at"] is not None
    async with sm() as s:
        row = (await s.scalars(select(AdminAction).where(AdminAction.action == "switch.set"))).one()
    assert (row.actor, row.target_id, row.before, row.after, row.reason) == (
        "Hedi",
        "llm_max_rpm_override",
        None,
        6,
        "rehearsal",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("llm_max_rpm_override", 19),  # may only lower LLM_MAX_RPM (18)
        ("llm_max_rpm_override", 0),
        ("force_quick_mode", 61),
        ("force_quick_mode", True),
        ("offline_demo_mode", "maybe"),
        ("pause_background_lane", "yes"),
    ],
)
async def test_switch_values_are_validated(api, monkeypatch, key, value):
    enable_admin(monkeypatch)
    r = await api.put(f"/api/admin/switches/{key}", json={"value": value}, headers=ACT)
    assert r.status_code == 422


async def test_unknown_switch_is_422(api, monkeypatch):
    enable_admin(monkeypatch)
    r = await api.put("/api/admin/switches/llm_provider", json={"value": "local"}, headers=ACT)
    assert r.status_code == 422  # provider switching never appears on the admin side


async def test_forced_quick_mode_is_counted_apart(api, sm, mock_llm, monkeypatch):
    enable_admin(monkeypatch)
    worker_gw = gateway(sm, mock_llm)  # the worker's own process and limiter
    r = await api.put("/api/admin/switches/force_quick_mode", json={"value": 10}, headers=ACT)
    assert r.status_code == 200
    res = await worker_gw.run(
        Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES)
    )
    assert res.quick_mode and res.model_tier == "compact" and res.pattern == "forced-fallback"
    bg = await worker_gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="background", messages=MESSAGES))
    assert bg.model_tier == "mid" and not bg.quick_mode  # background work is never forced
    await api.put("/api/admin/switches/force_quick_mode", json={"value": 0}, headers=ACT)
    # a real fallback: mid saturated twice → compact
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    real = await worker_gw.run(
        Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES[:1])
    )
    assert real.quick_mode and real.pattern == "fallback"
    stats = (await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)).json()
    assert stats["fallbacks"] == 1 and stats["forced_fallbacks"] == 1
    # the forced compact call is left out of the compact/mid split
    tiers = stats["by_tier"]
    split_compact = tiers["compact"]["calls"] - 1
    assert stats["compact_share"] == round(
        split_compact / (split_compact + tiers["mid"]["calls"]), 3
    )
    async with sm() as s:
        forced = list(await s.scalars(select(AICallLog).where(AICallLog.forced.is_(True))))
    assert [(r.model_tier, r.pattern, r.fallback) for r in forced] == [
        ("compact", "forced-fallback", True)
    ]


async def test_forced_quick_mode_turns_itself_off():
    end = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    f = flags.Flags(force_quick_until=end)
    assert f.force_quick_active(end - timedelta(seconds=1))
    assert not f.force_quick_active(end)


async def test_legacy_force_quick_endpoints_use_the_switch(api, monkeypatch):
    enable_admin(monkeypatch)
    r = await api.post("/api/admin/force-quick", json={"minutes": 5}, headers=ACT)
    assert r.status_code == 200 and r.json()["active"] is True
    view = (await api.get("/api/admin/switches", headers=READ)).json()
    assert {s["key"]: s for s in view["switches"]}["force_quick_mode"]["effective"] is True
    assert (await api.get("/api/system/status")).json()["quick_mode_forced"] is True
    off = await api.delete("/api/admin/force-quick", headers=ACT)
    assert off.json()["active"] is False


async def test_a_change_reaches_another_process_within_the_ttl(sm, monkeypatch):
    """The worker is a separate process: it sees a switch written by the API once its ~3 s cache
    expires, with no restart (here the row is written behind this process's back)."""
    assert (await flags.load(sm)).pause_background_lane is False
    async with sm() as s:
        await s.execute(
            text("INSERT INTO runtime_flags (key, value) VALUES ('pause_background_lane', 'true')")
        )
        await s.commit()
    assert (await flags.load(sm)).pause_background_lane is False  # cached
    monkeypatch.setattr(flags, "TTL_S", 0.0)
    assert (await flags.load(sm)).pause_background_lane is True


async def test_pause_background_lane_in_the_worker(sm, gw, api, monkeypatch):  # noqa: F811
    enable_admin(monkeypatch)
    async with sm() as s:
        bg = await create_job(s, kind=demo.KIND, lane="background")
        fg = await create_job(s, kind=demo.KIND, lane="interactive")
    await api.put("/api/admin/switches/pause_background_lane", json={"value": True}, headers=ACT)
    worker = Worker(sm)
    await worker.drain()
    async with sm() as s:
        assert (await s.get(Job, fg.id)).status == "done"
        assert (await s.get(Job, bg.id)).status == "queued"
    await api.put("/api/admin/switches/pause_background_lane", json={"value": False}, headers=ACT)
    await worker.drain()
    async with sm() as s:
        assert (await s.get(Job, bg.id)).status == "done"
    status = (await api.get("/api/system/status")).json()
    assert status["background_paused"] is False


async def test_offline_switch(api, sm, gw, monkeypatch):  # noqa: F811
    enable_admin(monkeypatch)
    await api.put("/api/admin/switches/offline_demo_mode", json={"value": "on"}, headers=ACT)
    status = (await api.get("/api/system/status")).json()
    assert status["offline_demo_mode"] is True and status["reason"] == "forced"
    r = await api.post("/api/dev/demo-jobs", headers=DEV, json={})
    assert r.status_code == 503 and r.json()["detail"] == "errors.offline"
    await api.put("/api/admin/switches/offline_demo_mode", json={"value": "auto"}, headers=ACT)
    assert (await api.get("/api/system/status")).json()["offline_demo_mode"] is False
    assert (await api.post("/api/dev/demo-jobs", headers=DEV, json={})).status_code == 202
    # "off" never hides a pause the guards impose
    from app.api import system  # noqa: PLC0415
    from app.gateway.providers import Resolution  # noqa: PLC0415

    async def paused(settings, sm, now=None):
        return Resolution(settings.llm, offline=True, reason="outside_slot")

    monkeypatch.setattr(system, "resolve", paused)
    await api.put("/api/admin/switches/offline_demo_mode", json={"value": "off"}, headers=ACT)
    assert (await api.get("/api/system/status")).json()["offline_demo_mode"] is True
    from app.gateway import providers  # noqa: PLC0415

    monkeypatch.setattr(system, "resolve", providers.resolve)
    # OFFLINE_DEMO_MODE=on in the environment wins over the switch
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "on")
    get_settings.cache_clear()
    await api.put("/api/admin/switches/offline_demo_mode", json={"value": "off"}, headers=ACT)
    assert (await api.get("/api/system/status")).json()["offline_demo_mode"] is True


async def test_rpm_override_only_lowers_the_limiter(sm, mock_llm, monkeypatch):
    lim = Limiter(18, 2)
    lim.cap_rpm(6)
    assert lim.buckets["chat"].rate == pytest.approx(6 / 60)
    lim.cap_rpm(600)
    assert lim.buckets["chat"].rate == pytest.approx(18 / 60)  # never above the configured rate
    lim.cap_rpm(None)
    assert lim.buckets["chat"].rate == pytest.approx(18 / 60)
    # the gateway applies the switch on its next call
    worker_gw = gateway(sm, mock_llm)
    async with sm() as s:
        await flags.write(s, "llm_max_rpm_override", 12, "test")
        await s.commit()
    await worker_gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES))
    assert worker_gw.limiter.buckets["chat"].rate == pytest.approx(12 / 60)
