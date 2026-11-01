"""Class Pool: gifts move coins from a wallet to the pool (both ledgers); a pool-paid job is
refunded to the pool when it fails; nicknames only."""

import uuid

from sqlalchemy import select

from app.core import economy
from app.features.pool import service as pool
from app.features.wallet.service import LedgerCoins
from app.jobs.service import create_job
from app.models import ClassPoolLedger, Job, User
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import OWL, SEA, api, make_world  # noqa: F401  (fixtures)


async def test_gifts_move_coins_from_the_wallet_to_the_pool(api, sm):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL)
    url = f"/api/worlds/{world['id']}/pool"
    assert (await api.get(url, headers=OWL)).json() == {
        "balance": 0,
        "max_contribution": pool.MAX_CONTRIBUTION,
        "recent": [],
    }
    r = await api.post(url, json={"amount": 6}, headers=OWL)
    assert r.status_code == 200
    await api.post(url, json={"amount": 4}, headers=SEA)
    out = (await api.get(url, headers=SEA)).json()
    assert out["balance"] == 10
    assert out["recent"] == [
        {"nickname": "SeaTurtle42", "coins": 4},
        {"nickname": "NightOwl7", "coins": 6},
    ]
    wallet = (await api.get("/api/wallet", headers=OWL)).json()
    assert wallet["coins"] == economy.DAILY_FREE_COINS - 6

    too_much = await api.post(url, json={"amount": 15}, headers=OWL)  # 14 left
    assert too_much.status_code == 402 and too_much.json()["detail"] == "errors.insufficient_coins"
    bad = await api.post(url, json={"amount": 0}, headers=OWL)
    assert bad.status_code == 400 and bad.json()["detail"] == "errors.pool_amount_invalid"
    stranger = await api.get(url, headers={"X-Dev-User": "Stranger9"})
    assert stranger.status_code == 404


async def test_a_failed_pool_paid_job_is_refunded_to_the_pool_once(api, sm):  # noqa: F811
    world = await make_world(api)
    world_id = uuid.UUID(world["id"])
    await api.post(f"/api/worlds/{world['id']}/pool", json={"amount": 20}, headers=SEA)
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "SeaTurtle42"))
        job = await create_job(s, kind="DEMO_SUMMARY", lane="background", user_id=user.id)
        await pool.reserve(s, job, world_id, 15)
        await s.commit()
        assert await pool.balance(s, world_id) == 5
    async with sm() as s:
        job = await s.get(Job, job.id)
        try:
            await pool.reserve(s, job, world_id, 15)
            raise AssertionError("expected InsufficientPool")
        except pool.InsufficientPool:
            pass
    async with sm() as s:
        job = await s.get(Job, job.id)
        await LedgerCoins().refund(s, job)
        await LedgerCoins().refund(s, job)  # idempotent
        await s.commit()
        assert await pool.balance(s, world_id) == 20
        kinds = sorted(r.kind for r in await s.scalars(select(ClassPoolLedger)))
    assert kinds == ["contribute", "refund", "spend"]
