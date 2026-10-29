"""Sign-in: argon2 passwords, the signed session cookie, signup/login/logout/me, and that the dev
header only works outside production."""

import time
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.core import security
from app.core.db import get_session, get_sessionmaker
from app.main import create_app


@pytest.fixture
def api(sm):
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# --- security units ------------------------------------------------------------------------------
def test_password_hash_roundtrip():
    stored = security.hash_password("olive-tree-42")
    assert stored.startswith("$argon2")
    assert security.verify_password(stored, "olive-tree-42")
    assert not security.verify_password(stored, "olive-tree-43")
    assert not security.verify_password(deps.UNUSABLE_PASSWORD, "anything")


def test_session_cookie_signed_and_expiring():
    uid = uuid.uuid4()
    token = security.sign_session(uid, now=1_000_000)
    assert security.read_session(token, now=1_000_100) == uid
    assert security.read_session(token, now=1_000_000 + security.SESSION_MAX_AGE_S + 1) is None
    forged = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    assert security.read_session(forged, now=1_000_100) is None
    other = security.sign_session(uuid.uuid4(), now=1_000_000)
    swapped = other.split(".")[0] + "." + ".".join(token.split(".")[1:])
    assert security.read_session(swapped, now=1_000_100) is None
    assert security.read_session("garbage", now=time.time()) is None
    assert security.read_session(None) is None


# --- API ---------------------------------------------------------------------------------------
SIGNUP = {"nickname": "SeaTurtle42", "password": "olive-tree-42", "ui_language": "fr"}


async def test_signup_sets_a_cookie_and_me_works(api):
    r = await api.post("/api/auth/signup", json=SIGNUP)
    assert r.status_code == 201
    me = r.json()
    assert me["nickname"] == "SeaTurtle42" and me["ui_language"] == "fr"
    assert not me["onboarded"] and not me["has_worlds"] and me["avatar"] is None
    cookie = r.headers["set-cookie"]
    assert (
        security.COOKIE_NAME in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    )
    assert (await api.get("/api/auth/me")).json()["id"] == me["id"]  # the client keeps the cookie


async def test_signup_rules(api):
    assert (await api.post("/api/auth/signup", json=SIGNUP)).status_code == 201
    api.cookies.clear()
    dup = await api.post("/api/auth/signup", json=SIGNUP | {"password": "another-pass"})
    assert dup.status_code == 409 and dup.json()["detail"] == "errors.nickname_taken"
    short = await api.post("/api/auth/signup", json=SIGNUP | {"nickname": "Owl_7", "password": "x"})
    assert short.json()["detail"] == "errors.password_short"
    bad = await api.post("/api/auth/signup", json=SIGNUP | {"nickname": "with space"})
    assert bad.json()["detail"] == "errors.nickname_invalid"


async def test_login_logout(api):
    await api.post("/api/auth/signup", json=SIGNUP)
    await api.post("/api/auth/logout")
    api.cookies.clear()  # the browser drops it on the delete-cookie header
    assert (await api.get("/api/auth/me")).status_code == 401
    wrong = await api.post("/api/auth/login", json={"nickname": "SeaTurtle42", "password": "nope"})
    unknown = await api.post("/api/auth/login", json={"nickname": "Nobody", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "errors.login_failed"
    ok = await api.post(
        "/api/auth/login", json={"nickname": "SeaTurtle42", "password": "olive-tree-42"}
    )
    assert ok.status_code == 200 and (await api.get("/api/auth/me")).status_code == 200


async def test_dev_users_cannot_log_in(api):
    assert (await api.get("/api/worlds", headers={"X-Dev-User": "demo"})).status_code == 200
    r = await api.post("/api/auth/login", json={"nickname": "demo", "password": "!"})
    assert r.status_code == 401


async def test_no_cookie_no_header_is_401(api):
    r = await api.get("/api/worlds")
    assert r.status_code == 401 and r.json()["detail"] == "errors.sign_in_required"


async def test_language_change_persists(api):
    await api.post("/api/auth/signup", json=SIGNUP)
    r = await api.patch("/api/auth/me", json={"ui_language": "ar-TN"})
    assert r.json()["ui_language"] == "ar-TN"
    assert (await api.get("/api/auth/me")).json()["ui_language"] == "ar-TN"


async def test_production_ignores_the_dev_header(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(APP_ENV="production"))
    user = await deps.optional_user(s=None, lw_session=None, x_dev_user="SeaTurtle42")
    assert user is None
    with pytest.raises(deps.HTTPException) as e:
        await deps.current_user(user)
    assert e.value.status_code == 401 and e.value.detail == "errors.sign_in_required"
