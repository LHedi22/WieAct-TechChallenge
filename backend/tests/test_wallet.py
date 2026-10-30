"""The wallet on Postgres (ECONOMY.md): daily grant, reserve/refund around jobs, 402, earn cap,
Exam Pass limit, purchases that never expire, idempotent points and streaks."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

import app.gateway as gateway_module
from app.core import economy
from app.features.wallet import service as wallet
from app.gateway import BadOutput
from app.jobs import demo
from app.jobs.service import cancel, create_job
from app.jobs.worker import Worker
from app.main import create_app
from app.models import CoinLedger, Job, User
from tests.test_jobs import api  # noqa: F401  (fixture)

T0 = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)  # 10:00 in Tunis


async def make_user(sm, nickname="OliveOwl") -> uuid.UUID:
    async with sm() as s:
        u = User(nickname=nickname, password_hash="!", ui_language="en")
        s.add(u)
        await s.commit()
        return u.id


async def bal(sm, user_id, now=T0) -> wallet.Balances:
    async with sm() as s:
        b = await wallet.balances(s, user_id, now)
        await s.commit()
        return b


async def paid_job(sm, user_id, cost) -> uuid.UUID:
    async with sm() as s:
        job = await create_job(s, kind=demo.KIND, lane="interactive", user_id=user_id, cost=cost)
        return job.id


async def test_daily_free_coins_granted_once_even_concurrently(sm):
    uid = await make_user(sm)
    await asyncio.gather(*[bal(sm, uid) for _ in range(5)])
    async with sm() as s:
        grants = await s.scalar(
            select(func.count()).where(CoinLedger.user_id == uid, CoinLedger.kind == "daily")
        )
    assert grants == 1
    assert (await bal(sm, uid)).coins == economy.DAILY_FREE_COINS


async def test_unused_free_coins_do_not_carry_over_but_purchases_do(sm):
    uid = await make_user(sm)
    async with sm() as s:
        await wallet.demo_purchase(s, uid, "coin_pack", T0)
        await s.commit()
    tomorrow = await bal(sm, uid, T0 + timedelta(days=1))
    assert tomorrow.free == economy.DAILY_FREE_COINS  # a fresh 20, not 40
    assert tomorrow.purchased == economy.PRODUCTS["coin_pack"]["coins"]  # never expires


async def test_job_reserves_in_spending_order_and_refunds_the_same_buckets(sm, monkeypatch):
    uid = await make_user(sm)
    async with sm() as s:
        await wallet.earn(s, uid, 3, "challenge-1")
        await s.commit()
    # spend 18 of the free 20 first
    for _ in range(2):
        await paid_job(sm, uid, economy.COST["tutor_session"])
    await paid_job(sm, uid, 2)
    job_id = await paid_job(sm, uid, economy.COST["quiz"])  # 2 free left → 2 free + 3 earned
    b = await bal(sm, uid, datetime.now(UTC))
    assert (b.free, b.earned) == (0, 0)

    async def broken(task):
        raise BadOutput("nope")

    monkeypatch.setattr(gateway_module, "run", broken)
    await Worker(sm).drain()  # every job fails → every reservation comes back
    async with sm() as s:
        assert (await s.get(Job, job_id)).status == "failed"
    b = await bal(sm, uid, datetime.now(UTC))
    assert (b.free, b.earned) == (economy.DAILY_FREE_COINS, 3)


async def test_refund_is_idempotent_and_cancel_refunds(sm):
    uid = await make_user(sm)
    job_id = await paid_job(sm, uid, economy.COST["quiz"])
    async with sm() as s:
        job = await s.get(Job, job_id)
        await cancel(s, job)
        await wallet.refund(s, job)  # a second refund changes nothing
        await s.commit()
    assert (await bal(sm, uid, datetime.now(UTC))).coins == economy.DAILY_FREE_COINS


async def test_short_balance_raises_and_saves_nothing(sm, api):  # noqa: F811
    uid = await make_user(sm)
    with pytest.raises(wallet.InsufficientCoins):
        await paid_job(sm, uid, economy.DAILY_FREE_COINS + 1)
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(Job)) == 0


async def test_out_of_coins_is_a_402_with_an_i18n_key():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise wallet.InsufficientCoins()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/boom")
    assert r.status_code == 402 and r.json()["detail"] == "errors.insufficient_coins"


async def test_earn_cap_and_once_per_ref(sm):
    uid = await make_user(sm)
    async with sm() as s:
        got = [await wallet.earn(s, uid, 3, f"answer-{i}", T0) for i in range(5)]
        again = await wallet.earn(s, uid, 3, "answer-0", T0)
        await s.commit()
    assert got == [3, 3, 3, 1, 0] and sum(got) == economy.DAILY_EARN_CAP
    assert again == 0
    async with sm() as s:  # the cap is per Tunis day
        assert await wallet.earn(s, uid, 3, "answer-9", T0 + timedelta(days=1)) == 3


async def test_exam_pass_covers_up_to_the_daily_limit(sm):
    uid = await make_user(sm)
    async with sm() as s:
        await wallet.demo_purchase(s, uid, "exam_pass", datetime.now(UTC))
        await s.commit()
    for _ in range(economy.EXAM_PASS_DAILY_LIMIT):
        await paid_job(sm, uid, economy.COST["tutor_session"])
    b = await bal(sm, uid, datetime.now(UTC))
    assert b.pass_left_today == 0 and b.free == economy.DAILY_FREE_COINS
    await paid_job(sm, uid, economy.COST["quiz"])  # the 16th is paid in coins
    assert (await bal(sm, uid, datetime.now(UTC))).free == economy.DAILY_FREE_COINS - 5


async def test_exam_pass_expires_and_extends(sm):
    uid = await make_user(sm)
    days = economy.PRODUCTS["exam_pass"]["days"]
    async with sm() as s:
        await wallet.demo_purchase(s, uid, "exam_pass", T0)
        await wallet.demo_purchase(s, uid, "exam_pass", T0 + timedelta(days=1))
        await s.commit()
    b = await bal(sm, uid, T0)
    assert b.pass_until == T0 + timedelta(days=2 * days)
    assert not b.pass_active(T0 + timedelta(days=2 * days + 1))


async def test_points_are_idempotent_and_drive_the_streak(sm):
    uid = await make_user(sm)
    now = datetime.now(UTC)
    async with sm() as s:
        assert await wallet.add_points(s, uid, None, 20, "activity_completed", "attempt-1")
        assert not await wallet.add_points(s, uid, None, 20, "activity_completed", "attempt-1")
        assert not await wallet.add_points(s, uid, None, 0, "quiz", "attempt-2")
        await s.commit()
        assert await wallet.points_total(s, uid) == 20
        assert await wallet.current_streak(s, uid, now) == 1
        assert await wallet.current_streak(s, uid, now + timedelta(days=1)) == 1
        assert await wallet.current_streak(s, uid, now + timedelta(days=2)) == 0


async def test_wallet_endpoint_shows_real_balances(sm, api):  # noqa: F811
    headers = {"X-Dev-User": "SeaTurtle42"}
    w = (await api.get("/api/wallet", headers=headers)).json()
    assert w["coins"] == economy.DAILY_FREE_COINS and w["exam_pass_until"] is None
    r = await api.post("/api/wallet/demo-purchase", json={"product": "coin_pack"}, headers=headers)
    assert r.json()["demo"] is True
    assert r.json()["wallet"]["coins"] == economy.DAILY_FREE_COINS + 50
    bad = await api.post("/api/wallet/demo-purchase", json={"product": "gold"}, headers=headers)
    assert bad.status_code == 422
