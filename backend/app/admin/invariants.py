"""Economy invariants: the one copy of the checks behind /api/admin/invariants (whole app) and the
student inspector (/api/admin/debug/students/{id}, `user_id` set). Reports, never fixes.

Each check returns its violations; `run()` returns {check: [rows]} with every check present, so a
page can show pass / fail per check. Checks marked "per student" only run with `user_id`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Integer, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy
from app.core.wallet_rules import tunis_day
from app.models import ClassPoolLedger, CoinLedger, Job, PeerAnswer, PointsLedger

Rows = list[dict[str, Any]]

# check → what it means (shown next to pass / fail)
DESCRIPTIONS = {
    "wallet_matches_ledger": "the wallet endpoint's balances equal the ledger sums (per student)",
    "negative_bucket": "no bucket below zero (free per day, earned and purchased overall)",
    "daily_once": "one daily refill row per day",
    "duplicate_reward": "earned coins paid once per ref",
    "duplicate_points": "points awarded once per (reason, ref)",
    "over_refund": "a job never refunded more than it spent",
    "unrefunded_job": "failed or cancelled paid jobs gave their coins back",
    "earned_cap": f"earned coins per day ≤ DAILY_EARN_CAP ({economy.DAILY_EARN_CAP})",
    "pending_review_rewarded": "no coins or points for an answer still in pending_review",
    "pass_over_limit": f"Exam Pass uses today ≤ {economy.EXAM_PASS_DAILY_LIMIT}",
    "negative_pool": "class pools never below zero (whole app)",
    "pool_double_refund": "class pool refunds at most once per ref (whole app)",
}


def _mine(user_id: uuid.UUID | None, col=CoinLedger.user_id) -> list:
    return [] if user_id is None else [col == user_id]


async def negative_bucket(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    v: Rows = []
    for bucket in ("earned", "purchased"):
        rows = (
            await s.execute(
                select(CoinLedger.user_id, func.sum(CoinLedger.delta))
                .where(CoinLedger.bucket == bucket, *_mine(user_id))
                .group_by(CoinLedger.user_id)
                .having(func.sum(CoinLedger.delta) < 0)
            )
        ).all()
        v += [{"user_id": u, "bucket": bucket, "balance": int(n)} for u, n in rows]
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.day, func.sum(CoinLedger.delta))
            .where(CoinLedger.bucket == "free", *_mine(user_id))
            .group_by(CoinLedger.user_id, CoinLedger.day)
            .having(func.sum(CoinLedger.delta) < 0)
        )
    ).all()
    v += [{"user_id": u, "bucket": "free", "day": d, "balance": int(n)} for u, d, n in rows]
    return v


async def daily_once(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.day, func.count())
            .where(CoinLedger.kind == "daily", *_mine(user_id))
            .group_by(CoinLedger.user_id, CoinLedger.day)
            .having(func.count() > 1)
        )
    ).all()
    return [{"user_id": u, "day": d, "rows": n} for u, d, n in rows]


async def duplicate_reward(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.ref, func.count())
            .where(CoinLedger.kind == "earned", CoinLedger.ref.is_not(None), *_mine(user_id))
            .group_by(CoinLedger.user_id, CoinLedger.ref)
            .having(func.count() > 1)
        )
    ).all()
    return [{"user_id": u, "ref": r, "rows": n} for u, r, n in rows]


async def duplicate_points(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    rows = (
        await s.execute(
            select(PointsLedger.user_id, PointsLedger.reason, PointsLedger.ref, func.count())
            .where(*_mine(user_id, PointsLedger.user_id))
            .group_by(PointsLedger.user_id, PointsLedger.reason, PointsLedger.ref)
            .having(func.count() > 1)
        )
    ).all()
    return [{"user_id": u, "reason": why, "ref": r, "rows": n} for u, why, r, n in rows]


async def over_refund(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    spent = func.sum(case((CoinLedger.kind == "spend", -CoinLedger.delta), else_=0))
    refunded = func.sum(case((CoinLedger.kind == "refund", CoinLedger.delta), else_=0))
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.ref, spent, refunded)
            .where(
                CoinLedger.kind.in_(("spend", "refund")),
                CoinLedger.ref.is_not(None),
                *_mine(user_id),
            )
            .group_by(CoinLedger.user_id, CoinLedger.ref)
            .having(refunded > spent)
        )
    ).all()
    return [{"user_id": u, "ref": r, "spent": int(a), "refunded": int(b)} for u, r, a, b in rows]


async def unrefunded_job(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    spend_rows = (
        select(CoinLedger.ref)
        .where(CoinLedger.kind == "spend", CoinLedger.bucket != "pass")
        .subquery()
    )
    refund_rows = select(CoinLedger.ref).where(CoinLedger.kind == "refund").subquery()
    rows = (
        await s.execute(
            select(Job.id, Job.user_id, Job.status, Job.cost)
            .where(
                Job.status.in_(("failed", "cancelled")),
                Job.cost > 0,
                cast(Job.id, CoinLedger.ref.type).in_(select(spend_rows.c.ref)),
                ~cast(Job.id, CoinLedger.ref.type).in_(select(refund_rows.c.ref)),
                *_mine(user_id, Job.user_id),
            )
            .limit(200)
        )
    ).all()
    return [{"job_id": j, "user_id": u, "status": st, "cost": c} for j, u, st, c in rows]


async def earned_cap(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    total = func.sum(CoinLedger.delta)
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.day, total)
            .where(CoinLedger.kind == "earned", *_mine(user_id))
            .group_by(CoinLedger.user_id, CoinLedger.day)
            .having(total > economy.DAILY_EARN_CAP)
        )
    ).all()
    return [{"user_id": u, "day": d, "earned": int(n)} for u, d, n in rows]


async def pending_review_rewarded(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    ref = func.concat("answer:", cast(PeerAnswer.id, CoinLedger.ref.type))
    coin = select(CoinLedger.id).where(CoinLedger.ref == ref, CoinLedger.kind == "earned")
    pts = select(PointsLedger.id).where(PointsLedger.ref == ref, PointsLedger.reason == "answer")
    rows = (
        await s.execute(
            select(PeerAnswer.id, PeerAnswer.author_id, PeerAnswer.rewarded).where(
                PeerAnswer.status == "pending_review",
                or_(PeerAnswer.rewarded.is_(True), coin.exists(), pts.exists()),
                *_mine(user_id, PeerAnswer.author_id),
            )
        )
    ).all()
    return [{"answer_id": a, "user_id": u, "rewarded_flag": r} for a, u, r in rows]


async def pass_over_limit(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    uses = func.sum(
        case((CoinLedger.kind == "spend", 1), (CoinLedger.kind == "refund", -1), else_=0)
    )
    rows = (
        await s.execute(
            select(CoinLedger.user_id, cast(uses, Integer))
            .where(
                and_(CoinLedger.bucket == "pass", CoinLedger.day == tunis_day()), *_mine(user_id)
            )
            .group_by(CoinLedger.user_id)
            .having(uses > economy.EXAM_PASS_DAILY_LIMIT)
        )
    ).all()
    return [{"user_id": u, "uses": n} for u, n in rows]


async def negative_pool(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    rows = (
        await s.execute(
            select(ClassPoolLedger.world_id, func.sum(ClassPoolLedger.delta))
            .group_by(ClassPoolLedger.world_id)
            .having(func.sum(ClassPoolLedger.delta) < 0)
        )
    ).all()
    return [{"world_id": w, "balance": int(n)} for w, n in rows]


async def pool_double_refund(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    rows = (
        await s.execute(
            select(ClassPoolLedger.ref, func.count())
            .where(ClassPoolLedger.kind == "refund")
            .group_by(ClassPoolLedger.ref)
            .having(func.count() > 1)
        )
    ).all()
    return [{"ref": r, "rows": n} for r, n in rows]


async def wallet_matches_ledger(s: AsyncSession, user_id: uuid.UUID | None) -> Rows:
    """Per student: the wallet endpoint's own function (`wallet.service.balances`, run in a
    savepoint that is rolled back, since it writes today's refill) against the raw ledger sums
    the admin pages show (`browse.wallets`)."""
    if user_id is None:
        return []
    from app.admin.browse import wallets  # noqa: PLC0415  (browse imports this module's users)
    from app.features.wallet.service import balances  # noqa: PLC0415

    raw = (await wallets(s, [user_id]))[user_id]
    nested = await s.begin_nested()
    try:
        b = await balances(s, user_id)
    finally:
        await nested.rollback()
    got = {"free": b.free, "earned": b.earned, "purchased": b.purchased}
    return [
        {"bucket": k, "wallet_endpoint": got[k], "ledger_sum": raw[k]}
        for k in got
        if got[k] != raw[k]
    ]


CHECKS: dict[str, Callable[[AsyncSession, uuid.UUID | None], Awaitable[Rows]]] = {
    "wallet_matches_ledger": wallet_matches_ledger,
    "negative_bucket": negative_bucket,
    "daily_once": daily_once,
    "duplicate_reward": duplicate_reward,
    "duplicate_points": duplicate_points,
    "over_refund": over_refund,
    "unrefunded_job": unrefunded_job,
    "earned_cap": earned_cap,
    "pending_review_rewarded": pending_review_rewarded,
    "pass_over_limit": pass_over_limit,
    "negative_pool": negative_pool,
    "pool_double_refund": pool_double_refund,
}
WORLD_ONLY = {"negative_pool", "pool_double_refund"}  # not about one student


async def run(s: AsyncSession, user_id: uuid.UUID | None = None) -> dict[str, Rows]:
    names = [n for n in CHECKS if user_id is None or n not in WORLD_ONLY]
    return {n: await CHECKS[n](s, user_id) for n in names}


def flat(results: dict[str, Rows]) -> Rows:
    """The /api/admin/invariants shape: one list of {check, …} rows."""
    return [{"check": name, **row} for name, rows in results.items() for row in rows]
