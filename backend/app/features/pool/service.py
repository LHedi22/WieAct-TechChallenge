"""The Class Pool (ECONOMY.md): members give coins so shared study material (study packs, audio)
can be generated for the whole class. Every change is a `class_pool_ledger` row; the balance is
their sum. A contribution is also a spend row in the giver's own wallet (it is never given back).
A pool-paid job writes a `spend` row with the job id as ref; a failed job reverses it once."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.wallet import service as wallet
from app.models import ClassPoolLedger, Job, User

MAX_CONTRIBUTION = 50  # per gift; keeps a misclick from emptying a wallet


class InsufficientPool(Exception):
    key = "errors.pool_insufficient"


class BadAmount(Exception):
    key = "errors.pool_amount_invalid"


async def _lock(s: AsyncSession, world_id: uuid.UUID) -> None:
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"pool:{world_id}"}
    )


async def balance(s: AsyncSession, world_id: uuid.UUID) -> int:
    total = await s.scalar(
        select(func.coalesce(func.sum(ClassPoolLedger.delta), 0)).where(
            ClassPoolLedger.world_id == world_id
        )
    )
    return int(total or 0)


async def contribute(
    s: AsyncSession, user: User, world_id: uuid.UUID, amount: int, now: datetime | None = None
) -> uuid.UUID:
    """Move coins from the student's wallet to the pool (same transaction). Does not commit."""
    if not 1 <= amount <= MAX_CONTRIBUTION:
        raise BadAmount()
    gift = uuid.uuid4()
    await wallet.spend(s, user.id, amount, f"pool:{gift}", now)  # raises InsufficientCoins
    await _lock(s, world_id)
    s.add(
        ClassPoolLedger(
            id=gift, world_id=world_id, user_id=user.id, kind="contribute", delta=amount
        )
    )
    await s.flush()
    return gift


async def reserve(s: AsyncSession, job: Job, world_id: uuid.UUID, amount: int) -> None:
    """Pay a job from the pool (same transaction as the job). Raises InsufficientPool."""
    await _lock(s, world_id)
    if await balance(s, world_id) < amount:
        raise InsufficientPool()
    s.add(
        ClassPoolLedger(
            world_id=world_id, user_id=job.user_id, kind="spend", delta=-amount, ref=str(job.id)
        )
    )
    await s.flush()


async def refund(s: AsyncSession, job: Job) -> None:
    """Give a failed or cancelled pool-paid job's coins back to the pool (idempotent)."""
    spent = (
        await s.scalars(
            select(ClassPoolLedger).where(
                ClassPoolLedger.ref == str(job.id), ClassPoolLedger.kind == "spend"
            )
        )
    ).all()
    for row in spent:
        await _lock(s, row.world_id)
        await s.execute(
            insert(ClassPoolLedger)
            .values(
                id=uuid.uuid4(),
                world_id=row.world_id,
                user_id=row.user_id,
                kind="refund",
                delta=-row.delta,
                ref=row.ref,
            )
            .on_conflict_do_nothing(index_elements=["ref"], index_where=text("kind = 'refund'"))
        )


async def recent(s: AsyncSession, world_id: uuid.UUID, limit: int = 5) -> list[tuple[str, int]]:
    """The last contributions: (nickname, coins). Nicknames only."""
    rows = await s.execute(
        select(User.nickname, ClassPoolLedger.delta)
        .join(User, User.id == ClassPoolLedger.user_id)
        .where(ClassPoolLedger.world_id == world_id, ClassPoolLedger.kind == "contribute")
        .order_by(ClassPoolLedger.created_at.desc())
        .limit(limit)
    )
    return [(n, d) for n, d in rows]
