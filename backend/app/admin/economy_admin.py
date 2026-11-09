"""Admin economy actions. Every coin or point change is a ledger row (never a balance), written
with its admin_actions row in one transaction; a reason is required.

- coins: kind `admin` in the bucket the admin picks (free coins count on today only, like the
  daily refill); the daily earn cap doesn't apply (it counts `earned` rows only); a change that
  would make the bucket negative is refused.
- points: reason `admin_adjust`, a unique ref per action; the total may not go below zero.
- Exam Pass: a 0-coin `pass` row, kind `admin`, ref `pass_grant:…` (starts or extends one) or
  `pass_end:…` (stops the active one now).
- class pool: kind `admin`; the balance may not go below zero.
- overrides: core/economy_live.py; the invariant check reports and never fixes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.admin import audit
from app.admin import invariants as inv
from app.admin.auth import AdminActionDep, AdminDep
from app.admin.browse import wallets
from app.api.deps import Session
from app.core import db, economy_live
from app.core.wallet_rules import tunis_day
from app.features.wallet.service import PASS_END, PASS_GRANT, _lock, balances
from app.models import ClassPoolLedger, CoinLedger, PointsLedger, User, World

router = APIRouter()
Reason = Field(min_length=3, max_length=500)


class CoinsIn(BaseModel):
    bucket: Literal["free", "earned", "purchased"]
    delta: int = Field(ge=-100_000, le=100_000)
    reason: str = Reason


class PointsIn(BaseModel):
    world_id: uuid.UUID | None = None
    delta: int = Field(ge=-100_000, le=100_000)
    reason: str = Reason


class PassIn(BaseModel):
    action: Literal["grant", "end"]
    reason: str = Reason


class PoolIn(BaseModel):
    delta: int = Field(ge=-100_000, le=100_000)
    reason: str = Reason


async def _user(s, user_id: uuid.UUID) -> User:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Not Found")
    return user


def _ref() -> str:
    return f"admin:{uuid.uuid4().hex[:24]}"


@router.post("/users/{user_id}/coins")
async def adjust_coins(
    user_id: uuid.UUID, body: CoinsIn, admin: AdminActionDep, s: Session
) -> dict[str, Any]:
    if body.delta == 0:
        raise HTTPException(422, "delta must not be 0")
    await _user(s, user_id)
    await _lock(s, user_id)  # the same per-user lock as every wallet write
    before = await balances(s, user_id)
    have = getattr(before, body.bucket)
    if have + body.delta < 0:
        raise HTTPException(
            422,
            f"The {body.bucket} bucket has {have} coins; removing {-body.delta} would go negative",
        )
    ref = _ref()
    s.add(
        CoinLedger(
            user_id=user_id,
            day=tunis_day(),
            bucket=body.bucket,
            kind="admin",
            delta=body.delta,
            ref=ref,
        )
    )
    audit.record(
        s,
        admin,
        "coins.adjust",
        target_kind="user",
        target_id=user_id,
        before={body.bucket: have},
        after={body.bucket: have + body.delta, "ref": ref},
        reason=body.reason,
    )
    await s.commit()
    return (await wallets(s, [user_id]))[user_id]


@router.post("/users/{user_id}/points")
async def adjust_points(
    user_id: uuid.UUID, body: PointsIn, admin: AdminActionDep, s: Session
) -> dict[str, Any]:
    if body.delta == 0:
        raise HTTPException(422, "delta must not be 0")
    await _user(s, user_id)
    total = int(
        await s.scalar(
            select(func.coalesce(func.sum(PointsLedger.delta), 0)).where(
                PointsLedger.user_id == user_id
            )
        )
        or 0
    )
    if total + body.delta < 0:
        raise HTTPException(422, f"The student has {total} points; this would go below zero")
    if body.world_id and await s.get(World, body.world_id) is None:
        raise HTTPException(422, "world_id not found")
    ref = _ref()
    s.add(
        PointsLedger(
            user_id=user_id,
            world_id=body.world_id,
            delta=body.delta,
            reason="admin_adjust",
            ref=ref,
        )
    )
    audit.record(
        s,
        admin,
        "points.adjust",
        target_kind="user",
        target_id=user_id,
        before={"points": total},
        after={"points": total + body.delta, "world_id": body.world_id, "ref": ref},
        reason=body.reason,
    )
    await s.commit()
    return {"points": total + body.delta}


@router.post("/users/{user_id}/exam-pass")
async def exam_pass(
    user_id: uuid.UUID, body: PassIn, admin: AdminActionDep, s: Session
) -> dict[str, Any]:
    await _user(s, user_id)
    await _lock(s, user_id)
    before = await balances(s, user_id)
    now = datetime.now(UTC)
    if body.action == "end" and not before.pass_active(now):
        raise HTTPException(422, "No active Exam Pass to end")
    prefix = PASS_GRANT if body.action == "grant" else PASS_END
    row = CoinLedger(
        user_id=user_id,
        day=tunis_day(now),
        bucket="pass",
        kind="admin",
        delta=0,
        ref=f"{prefix}{uuid.uuid4().hex[:20]}",
    )
    row.created_at = now
    s.add(row)
    await s.flush()
    after = await balances(s, user_id)
    audit.record(
        s,
        admin,
        f"exam_pass.{body.action}",
        target_kind="user",
        target_id=user_id,
        before={"pass_until": before.pass_until},
        after={"pass_until": after.pass_until},
        reason=body.reason,
    )
    await s.commit()
    return {"pass_until": after.pass_until, "pass_active": after.pass_active(now)}


@router.post("/worlds/{world_id}/pool")
async def adjust_pool(
    world_id: uuid.UUID, body: PoolIn, admin: AdminActionDep, s: Session
) -> dict[str, Any]:
    if body.delta == 0:
        raise HTTPException(422, "delta must not be 0")
    if await s.get(World, world_id, with_for_update=True) is None:
        raise HTTPException(404, "Not Found")
    balance = int(
        await s.scalar(
            select(func.coalesce(func.sum(ClassPoolLedger.delta), 0)).where(
                ClassPoolLedger.world_id == world_id
            )
        )
        or 0
    )
    if balance + body.delta < 0:
        raise HTTPException(422, f"The class pool has {balance} coins; this would go negative")
    ref = _ref()
    s.add(ClassPoolLedger(world_id=world_id, user_id=None, kind="admin", delta=body.delta, ref=ref))
    audit.record(
        s,
        admin,
        "pool.adjust",
        target_kind="world",
        target_id=world_id,
        before={"pool": balance},
        after={"pool": balance + body.delta, "ref": ref},
        reason=body.reason,
    )
    await s.commit()
    return {"balance": balance + body.delta}


# --- live overrides ------------------------------------------------------------------------------
class OverrideIn(BaseModel):
    value: int | None  # None = back to the economy.py default
    reason: str = Reason


@router.get("/economy")
async def economy_view(_: AdminDep, s: Session) -> dict[str, Any]:
    stored = await economy_live.rows(s)
    defaults = economy_live.defaults()
    effective = economy_live.effective({k: r.value for k, r in stored.items()})
    items = []
    for key, default in defaults.items():
        row = stored.get(key)
        lo, hi = economy_live.bounds(key)
        items.append(
            {
                "key": key,
                "default": default,
                "effective": effective[key],
                "overridden": row is not None,
                "min": lo,
                "max": hi,
                "updated_at": row.updated_at if row else None,
                "updated_by": row.updated_by if row else None,
            }
        )
    return {"items": items}


@router.put("/economy/{key}")
async def set_override(key: str, body: OverrideIn, admin: AdminActionDep, s: Session):
    from app.models import EconomyOverride  # noqa: PLC0415

    if key not in economy_live.defaults():
        raise HTTPException(422, f"{key} is not a number in economy.py")
    stored = await economy_live.rows(s)
    before = stored[key].value if key in stored else None
    if body.value is None:
        if key in stored:
            await s.delete(stored[key])
    else:
        try:
            value = economy_live.validate(key, body.value)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if key in stored:
            stored[key].value, stored[key].updated_by = value, admin.actor
            stored[key].updated_at = datetime.now(UTC)
        else:
            s.add(EconomyOverride(key=key, value=value, updated_by=admin.actor))
    audit.record(
        s,
        admin,
        "economy.override",
        target_kind="economy",
        target_id=key,
        before=before,
        after=body.value,
        reason=body.reason,
    )
    await s.commit()
    await economy_live.refresh(db.get_sessionmaker(), fresh=True)
    return await economy_view(admin, s)


# --- invariant check (reports, never fixes) ------------------------------------------------------
@router.get("/invariants")
async def invariants(_: AdminDep, s: Session) -> dict[str, Any]:
    """Every check of admin/invariants.py over the whole app (the student inspector runs the same
    checks for one student)."""
    v = inv.flat(await inv.run(s))
    return {"ok": not v, "violations": v, "checked_at": datetime.now(UTC)}
