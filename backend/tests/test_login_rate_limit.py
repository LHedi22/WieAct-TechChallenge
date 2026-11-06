"""Audit F-SEC-5 (Tier 2 #8): 60 wrong passwords in a row all got a plain 401; nothing slowed an
online guessing run against a nickname seen on the leaderboard.

Now: after 5 failed sign-ins for a nickname within the window, that nickname is locked for the lock
time (even the right password gets 429 + Retry-After, or the guessing would just go on); a client IP
has a looser cap across nicknames; a successful sign-in clears the nickname's count."""

import pytest

from app.features.auth import ratelimit
from tests.test_auth import api  # noqa: F401  (fixture)

GOOD = {"nickname": "GuardedOwl1", "password": "the-right-one-1"}


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    clock = {"t": 1_000.0}
    lim = ratelimit.LoginLimiter(clock=lambda: clock["t"])
    monkeypatch.setattr(ratelimit, "limiter", lim)
    return clock


async def login(api, password, nickname=GOOD["nickname"], ip=None):  # noqa: F811
    headers = {"X-Forwarded-For": ip} if ip else {}
    return await api.post(
        "/api/auth/login", json={"nickname": nickname, "password": password}, headers=headers
    )


async def test_a_nickname_is_locked_after_five_failures(api, fresh_limiter):  # noqa: F811
    await api.post("/api/auth/signup", json=GOOD)
    codes = [(await login(api, f"wrong-{i}")).status_code for i in range(5)]
    assert codes == [401] * 5
    locked = await login(api, GOOD["password"])  # even the right password waits
    assert locked.status_code == 429
    assert locked.json()["detail"] == "errors.too_many_attempts"
    assert 0 < int(locked.headers["retry-after"]) <= ratelimit.LOCK_S

    fresh_limiter["t"] += ratelimit.LOCK_S + 1  # the lock ends
    assert (await login(api, GOOD["password"])).status_code == 200


async def test_success_clears_the_count(api):  # noqa: F811
    await api.post("/api/auth/signup", json=GOOD)
    for i in range(4):
        assert (await login(api, f"wrong-{i}")).status_code == 401
    assert (await login(api, GOOD["password"])).status_code == 200
    for i in range(4):  # a fresh budget after a success
        assert (await login(api, f"wrong-again-{i}")).status_code == 401


async def test_unknown_nicknames_count_too(api):  # noqa: F811
    codes = [(await login(api, "x", nickname="NoSuchUser9")).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429  # no account probing either


async def test_one_ip_spraying_many_nicknames_is_capped(api):  # noqa: F811
    codes = []
    for i in range(ratelimit.IP_MAX_FAILURES + 1):
        r = await login(api, "x", nickname=f"Spray{i:03d}", ip="203.0.113.7")
        codes.append(r.status_code)
    assert set(codes[:-1]) == {401} and codes[-1] == 429
    other_ip = await login(api, "x", nickname="Spray999", ip="198.51.100.2")
    assert other_ip.status_code == 401  # another client isn't punished


async def test_nickname_case_does_not_reset_the_count(api):  # noqa: F811
    for i, nick in enumerate(
        ["guardedowl1", "GUARDEDOWL1", "GuardedOwl1", "gUaRdEdOwL1", "GuardedOWL1"]
    ):
        assert (await login(api, f"w{i}", nickname=nick)).status_code == 401
    assert (await login(api, "w9", nickname="GuardedOwl1")).status_code == 429
