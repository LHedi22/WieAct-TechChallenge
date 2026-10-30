"""The wallet (docs/ECONOMY.md): coin and point ledgers. Balances are always sums of rows.

- free coins: a `daily` row (+DAILY_FREE_COINS) is written lazily on the first read of a Tunis day;
  only rows of the current day count, so unused free coins don't carry over.
- reserve when a paid job is created (spending order free → earned → purchased, or a 0-coin `pass`
  use while an Exam Pass is active), refund by reversing exactly those rows; commit is a no-op.
- earned coins are capped per day; points are idempotent per (reason, ref).
Every write for one user runs under a per-user advisory lock so two tabs can't overspend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy
from app.core.wallet_rules import capped_earn, split_spend, streak, tunis_day
from app.models import CoinLedger, Job, PointsLedger


class InsufficientCoins(Exception):
    key = "errors.insufficient_coins"


class UnknownProduct(Exception):
    pass


@dataclass
class Balances:
    free: int
    earned: int
    purchased: int
    earned_today: int
    pass_until: datetime | None
    pass_used_today: int

    @property
    def coins(self) -> int:
        return self.free + self.earned + self.purchased

    def pass_active(self, now: datetime) -> bool:
        return self.pass_until is not None and self.pass_until > now

    @property
    def pass_left_today(self) -> int:
        return max(0, economy.EXAM_PASS_DAILY_LIMIT - self.pass_used_today)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def _lock(s: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialises wallet writes per user until the transaction ends."""
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"wallet:{user_id}"}
    )


async def ensure_daily(s: AsyncSession, user_id: uuid.UUID, today: date) -> None:
    await s.execute(
        insert(CoinLedger)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            day=today,
            bucket="free",
            kind="daily",
            delta=economy.DAILY_FREE_COINS,
            ref=None,
        )
        .on_conflict_do_nothing(
            index_elements=["user_id", "day"], index_where=text("kind = 'daily'")
        )
    )


def _pass_until(purchases: list[datetime]) -> datetime | None:
    """Each Exam Pass lasts PRODUCTS days; buying one while active extends it."""
    until: datetime | None = None
    days = timedelta(days=economy.PRODUCTS["exam_pass"]["days"])
    for bought in sorted(purchases):
        until = max(until or bought, bought) + days
    return until


async def balances(s: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> Balances:
    today = tunis_day(_now(now))
    await ensure_daily(s, user_id, today)
    mine = CoinLedger.user_id == user_id
    sums = dict(
        (
            await s.execute(
                select(CoinLedger.bucket, func.sum(CoinLedger.delta))
                .where(mine, (CoinLedger.bucket != "free") | (CoinLedger.day == today))
                .group_by(CoinLedger.bucket)
            )
        ).all()
    )
    earned_today = await s.scalar(
        select(func.coalesce(func.sum(CoinLedger.delta), 0)).where(
            mine, CoinLedger.kind == "earned", CoinLedger.day == today
        )
    )
    purchases = (
        await s.scalars(
            select(CoinLedger.created_at).where(
                mine, CoinLedger.kind == "purchased", CoinLedger.bucket == "pass"
            )
        )
    ).all()
    # Exam Pass uses today: 0-coin spend rows minus their refunds
    pass_uses = await s.scalar(
        select(
            func.coalesce(
                func.sum(case((CoinLedger.kind == "spend", 1), (CoinLedger.kind == "refund", -1))),
                0,
            )
        ).where(mine, CoinLedger.bucket == "pass", CoinLedger.day == today)
    )
    return Balances(
        free=int(sums.get("free") or 0),
        earned=int(sums.get("earned") or 0),
        purchased=int(sums.get("purchased") or 0),
        earned_today=int(earned_today or 0),
        pass_until=_pass_until(list(purchases)),
        pass_used_today=int(pass_uses or 0),
    )


def _row(user_id: uuid.UUID, day: date, bucket: str, kind: str, delta: int, ref: str | None):
    return CoinLedger(
        id=uuid.uuid4(), user_id=user_id, day=day, bucket=bucket, kind=kind, delta=delta, ref=ref
    )


async def reserve(s: AsyncSession, job: Job, now: datetime | None = None) -> None:
    """Debit a paid job when it is created (same transaction). Raises InsufficientCoins."""
    if job.cost <= 0 or job.user_id is None:
        return
    now = _now(now)
    await _lock(s, job.user_id)
    b = await balances(s, job.user_id, now)
    today, ref = tunis_day(now), str(job.id)
    if b.pass_active(now) and b.pass_left_today > 0:
        s.add(_row(job.user_id, today, "pass", "spend", 0, ref))
        return
    _debit(job.user_id, b, job.cost, today, ref, s)
    await s.flush()


def _debit(user_id: uuid.UUID, b: Balances, amount: int, today: date, ref: str, s) -> None:
    split = split_spend(amount, free=b.free, earned=b.earned, purchased=b.purchased)
    if split is None:
        raise InsufficientCoins()
    for bucket, n in split.items():
        s.add(_row(user_id, today, bucket, "spend", -n, ref))


async def spend(
    s: AsyncSession, user_id: uuid.UUID, amount: int, ref: str, now: datetime | None = None
) -> None:
    """Spend coins outside a job (a Class Pool contribution): never paid by an Exam Pass.
    Raises InsufficientCoins."""
    now = _now(now)
    await _lock(s, user_id)
    b = await balances(s, user_id, now)
    _debit(user_id, b, amount, tunis_day(now), ref, s)
    await s.flush()


async def refund(s: AsyncSession, job: Job) -> None:
    """Reverse exactly what the job spent, bucket by bucket and on the same day (idempotent)."""
    if job.user_id is None:
        return
    await _lock(s, job.user_id)
    spent = (
        await s.scalars(
            select(CoinLedger).where(CoinLedger.ref == str(job.id), CoinLedger.kind == "spend")
        )
    ).all()
    for row in spent:
        await s.execute(
            insert(CoinLedger)
            .values(
                id=uuid.uuid4(),
                user_id=row.user_id,
                day=row.day,
                bucket=row.bucket,
                kind="refund",
                delta=-row.delta,
                ref=row.ref,
            )
            .on_conflict_do_nothing(
                index_elements=["ref", "bucket"], index_where=text("kind = 'refund'")
            )
        )


async def earn(
    s: AsyncSession, user_id: uuid.UUID, amount: int, ref: str, now: datetime | None = None
) -> int:
    """Credit earned coins once per ref, within the daily cap. Returns the coins credited."""
    now = _now(now)
    await _lock(s, user_id)
    already = await s.scalar(
        select(CoinLedger.id).where(
            CoinLedger.user_id == user_id, CoinLedger.kind == "earned", CoinLedger.ref == ref
        )
    )
    if already:
        return 0
    b = await balances(s, user_id, now)
    n = capped_earn(amount, earned_today=b.earned_today)
    if n:
        s.add(_row(user_id, tunis_day(now), "earned", "earned", n, ref))
        await s.flush()
    return n


async def add_points(
    s: AsyncSession,
    user_id: uuid.UUID,
    world_id: uuid.UUID | None,
    delta: int,
    reason: str,
    ref: str,
) -> bool:
    """Award points once per (user, reason, ref). Returns False if already awarded."""
    if delta <= 0:
        return False
    res = await s.execute(
        insert(PointsLedger)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            world_id=world_id,
            delta=delta,
            reason=reason,
            ref=ref,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "reason", "ref"])
        .returning(PointsLedger.id)
    )
    return res.scalar() is not None


async def points_total(s: AsyncSession, user_id: uuid.UUID) -> int:
    total = await s.scalar(
        select(func.coalesce(func.sum(PointsLedger.delta), 0)).where(
            PointsLedger.user_id == user_id
        )
    )
    return int(total or 0)


async def current_streak(s: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> int:
    """Consecutive Tunis days on which the student earned points (any finished activity)."""
    now = _now(now)
    local_day = func.date(func.timezone(str(economy.TZ), PointsLedger.created_at))
    days = (
        await s.scalars(
            select(local_day)
            .distinct()
            .where(
                PointsLedger.user_id == user_id, PointsLedger.created_at > now - timedelta(days=400)
            )
        )
    ).all()
    return streak(set(days), tunis_day(now))


async def demo_purchase(
    s: AsyncSession, user_id: uuid.UUID, product: str, now: datetime | None = None
) -> None:
    """Simulated purchase (clearly labelled in the UI): no payment is taken."""
    if product not in economy.PRODUCTS:
        raise UnknownProduct(product)
    now = _now(now)
    await _lock(s, user_id)
    if product == "coin_pack":
        coins = economy.PRODUCTS["coin_pack"]["coins"]
        s.add(_row(user_id, tunis_day(now), "purchased", "purchased", coins, product))
    else:
        row = _row(user_id, tunis_day(now), "pass", "purchased", 0, product)
        row.created_at = now
        s.add(row)
    await s.flush()


class LedgerCoins:
    """The job coin hooks (app/jobs/coins.py) backed by the ledger."""

    async def reserve(self, s: AsyncSession, job: Job) -> None:
        await reserve(s, job)

    async def commit(self, s: AsyncSession, job: Job) -> None:
        return None  # coins were debited at reserve time

    async def refund(self, s: AsyncSession, job: Job) -> None:
        from app.features.pool import service as pool  # noqa: PLC0415  (pool builds on wallet)

        await refund(s, job)
        await pool.refund(s, job)
