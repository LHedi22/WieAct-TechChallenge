"""Audit F-SEC-1 (Tier 2 #6): in production the session cookie was sent without `Secure` when
following DEPLOY.md (SESSION_COOKIE_SECURE defaulted to false). It now defaults to Secure whenever
APP_ENV=production; development stays plain-http friendly; an explicit value still wins."""

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.db import get_session, get_sessionmaker
from app.main import create_app

PROD = {
    "APP_ENV": "production",
    "LLM_PROVIDER": "cloud",
    "CLOUD_BASE_URL": "http://cloud.invalid/v1",
    "CLOUD_API_KEY": "test-only-not-a-key",
    "EMBED_PROVIDER": "local",
    "SECRET_KEY": "a-long-random-test-secret-for-production-mode",
    "OFFLINE_DEMO_MODE": "off",
}


def prod_env(monkeypatch, **extra):
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)  # a developer .env may set it
    for k, v in {**PROD, **extra}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("env", "secure"),
    [
        ({}, False),  # development default: plain http on localhost keeps working
        ({"SESSION_COOKIE_SECURE": ""}, False),
        ({"SESSION_COOKIE_SECURE": "auto"}, False),
        ({"SESSION_COOKIE_SECURE": "true"}, True),
    ],
)
def test_development_defaults(monkeypatch, env, secure):
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert Settings().session_cookie_secure is secure


@pytest.mark.parametrize(
    ("value", "secure"), [(None, True), ("", True), ("auto", True), ("false", False)]
)
def test_production_defaults_to_secure(monkeypatch, value, secure):
    prod_env(monkeypatch, **({} if value is None else {"SESSION_COOKIE_SECURE": value}))
    assert Settings().session_cookie_secure is secure


async def test_production_signup_sets_a_secure_cookie(monkeypatch, sm):
    prod_env(monkeypatch)
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as c:
        r = await c.post(
            "/api/auth/signup", json={"nickname": "SecureOwl1", "password": "long-enough-1"}
        )
        out = await c.post("/api/auth/logout")
    assert r.status_code == 201
    cookie = r.headers["set-cookie"].lower()
    assert "lw_session=" in cookie and "; secure" in cookie and "httponly" in cookie
    assert "; secure" in out.headers["set-cookie"].lower()  # the deletion matches the cookie
