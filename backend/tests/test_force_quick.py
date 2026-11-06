"""Audit F-VID-1 (Tier 3 #12): the demo video must show the fallback behaviour, but Quick mode only
appeared when the platform happened to be saturated, and the jury slot is the Widened tier.

An admin-only switch now forces it: while on, interactive mid tasks are answered by the compact
model as Quick mode (a real call, logged as `forced-fallback`, never cached as the class copy).
It is off by default, turns itself off after at most 30 minutes, needs the admin token (in
production a token must be configured), and production refuses to start with it switched on."""

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.gateway import Task, TaskKind, forcequick
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.service import Gateway
from app.main import create_app
from app.models import AICallLog
from tests.conftest import mock_transport

MESSAGES = [{"role": "system", "content": "Write notes."}, {"role": "user", "content": "Limits"}]
PROD = {
    "APP_ENV": "production",
    "LLM_PROVIDER": "cloud",
    "CLOUD_BASE_URL": "http://cloud.invalid/v1",
    "CLOUD_API_KEY": "test-only-not-a-key",
    "EMBED_PROVIDER": "local",
    "SECRET_KEY": "a-long-random-test-secret-for-production-mode",
}


@pytest.fixture(autouse=True)
def uploads(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def gateway(sm, mock_llm):
    return Gateway(
        Settings(),
        sm,
        client_factory=lambda p: LLMClient(
            p, timeout_s=5, disable_thinking=True, http_client=mock_transport(mock_llm)
        ),
        limiter=Limiter(6000, 2, burst=50),
    )


def api_for(sm):
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_off_by_default():
    assert Settings().FORCE_QUICK_MODE == "off"
    assert forcequick.active() is False


def test_production_refuses_to_start_with_it_on(monkeypatch):
    for k, v in {**PROD, "FORCE_QUICK_MODE": "on"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError, match="FORCE_QUICK_MODE"):
        Settings()


async def test_forced_interactive_mid_is_a_logged_quick_mode_compact_call(sm, mock_llm):
    gw = gateway(sm, mock_llm)
    forcequick.switch_on(minutes=5)
    res = await gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES))
    assert res.quick_mode and res.model_tier == "compact" and res.pattern == "forced-fallback"
    bg = await gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="background", messages=MESSAGES))
    assert bg.model_tier == "mid" and not bg.quick_mode  # background work is never forced
    async with sm() as s:
        rows = list(await s.scalars(select(AICallLog).where(AICallLog.cache_hit.is_(False))))
    assert [(r.model_tier, r.pattern, r.fallback) for r in rows] == [
        ("compact", "forced-fallback", True),
        ("mid", rows[1].pattern, False),
    ]
    forcequick.switch_off()
    again = await gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES))
    assert again.model_tier == "mid" and not again.quick_mode


def test_it_switches_itself_off():
    forcequick.switch_on(minutes=1, now=1_000.0)
    assert forcequick.active(now=1_030.0) is True
    assert forcequick.active(now=1_061.0) is False


async def test_admin_api_needs_the_token(sm, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t0ken")
    get_settings.cache_clear()
    async with api_for(sm) as api:
        assert (await api.post("/api/admin/force-quick", json={"minutes": 5})).status_code == 403
        r = await api.post(
            "/api/admin/force-quick", json={"minutes": 5}, headers={"X-Admin-Token": "t0ken"}
        )
        assert r.status_code == 200 and r.json()["active"] is True
        assert forcequick.active()
        too_long = await api.post(
            "/api/admin/force-quick", json={"minutes": 90}, headers={"X-Admin-Token": "t0ken"}
        )
        assert too_long.status_code == 422  # at most 30 minutes
        off = await api.delete("/api/admin/force-quick", headers={"X-Admin-Token": "t0ken"})
        assert off.json()["active"] is False and not forcequick.active()


async def test_production_without_a_token_refuses_the_switch(sm, monkeypatch):
    for k, v in PROD.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ADMIN_TOKEN", "")
    get_settings.cache_clear()
    async with api_for(sm) as api:
        r = await api.post("/api/admin/force-quick", json={"minutes": 5})
    assert r.status_code == 403 and not forcequick.active()
