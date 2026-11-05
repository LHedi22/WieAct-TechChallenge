"""Audit F-SEC-4 (Tier 2 #7): sign-out only deleted the cookie in the browser; a copied cookie kept
working for 30 days. Logout now bumps `users.session_epoch`, and a cookie signed for an older epoch
is refused. Cookies issued before this change (no epoch in them) count as epoch 0."""

import time

from sqlalchemy import select

from app.core import security
from app.models import User
from tests.test_auth import api  # noqa: F401  (fixture)

CREDS = {"nickname": "RevokeOwl1", "password": "long-enough-1"}


def cookie_of(r) -> str:
    return r.headers["set-cookie"].split(";")[0].split("=", 1)[1]


async def me(api, token):  # noqa: F811
    return await api.get("/api/auth/me", cookies={security.COOKIE_NAME: token})


async def test_a_copied_cookie_stops_working_after_logout(api):  # noqa: F811
    signup = await api.post("/api/auth/signup", json=CREDS)
    stolen = cookie_of(signup)
    assert (await me(api, stolen)).status_code == 200
    out = await api.post("/api/auth/logout", cookies={security.COOKIE_NAME: stolen})
    assert out.status_code == 204
    assert (await me(api, stolen)).status_code == 401  # revoked on the server

    again = await api.post("/api/auth/login", json=CREDS)
    fresh = cookie_of(again)
    assert (await me(api, fresh)).status_code == 200  # signing in again works
    assert (await me(api, stolen)).status_code == 401  # the old one stays dead


async def test_logout_without_a_cookie_is_harmless(api):  # noqa: F811
    assert (await api.post("/api/auth/logout")).status_code == 204


async def test_cookies_from_before_the_change_still_work_until_logout(api, sm):  # noqa: F811
    await api.post("/api/auth/signup", json={**CREDS, "nickname": "OldCookie2"})
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "OldCookie2"))
    payload = f"{user.id.hex}.{int(time.time())}"  # the pre-epoch format: id.issued.sig
    legacy = f"{payload}.{security._sig(payload)}"
    assert (await me(api, legacy)).status_code == 200
    await api.post("/api/auth/logout", cookies={security.COOKIE_NAME: legacy})
    assert (await me(api, legacy)).status_code == 401


def test_a_tampered_epoch_is_refused():
    token = security.sign_session(__import__("uuid").uuid4(), epoch=3, now=1_000_000)
    uid, issued, epoch, sig = token.split(".")
    forged = f"{uid}.{issued}.9.{sig}"
    assert security.read_claims(token, now=1_000_100) is not None
    assert security.read_claims(forged, now=1_000_100) is None
