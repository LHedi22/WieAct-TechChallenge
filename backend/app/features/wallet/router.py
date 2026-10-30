"""GET /api/wallet (top bar, out-of-coins screen) and POST /api/wallet/demo-purchase."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core import economy
from app.core.db import get_session
from app.features.wallet import service

router = APIRouter(prefix="/api/wallet", tags=["wallet"])


class Wallet(BaseModel):
    coins: int
    free_today: int
    earned: int
    purchased: int
    earned_today: int
    points: int
    streak: int
    refill_at: datetime
    exam_pass_until: datetime | None
    exam_pass_left_today: int | None  # None when no pass is active


class PurchaseIn(BaseModel):
    product: Literal["coin_pack", "exam_pass"]


class PurchaseOut(BaseModel):
    demo: bool  # always true: no payment is taken in the hackathon build
    wallet: Wallet


async def wallet_for(s: AsyncSession, user_id) -> Wallet:
    now = datetime.now(UTC)
    b = await service.balances(s, user_id, now)
    active = b.pass_active(now)
    return Wallet(
        coins=b.coins,
        free_today=b.free,
        earned=b.earned,
        purchased=b.purchased,
        earned_today=b.earned_today,
        points=await service.points_total(s, user_id),
        streak=await service.current_streak(s, user_id, now),
        refill_at=economy.next_refill(now),
        exam_pass_until=b.pass_until if active else None,
        exam_pass_left_today=b.pass_left_today if active else None,
    )


@router.get("", response_model=Wallet)
async def get_wallet(user: CurrentUser, s: Annotated[AsyncSession, Depends(get_session)]) -> Wallet:
    w = await wallet_for(s, user.id)
    await s.commit()  # keeps today's daily grant
    return w


@router.post("/demo-purchase", response_model=PurchaseOut)
async def demo_purchase(
    body: PurchaseIn, user: CurrentUser, s: Annotated[AsyncSession, Depends(get_session)]
) -> PurchaseOut:
    try:
        await service.demo_purchase(s, user.id, body.product)
    except service.UnknownProduct as e:
        raise HTTPException(400, "errors.unknown_product") from e
    w = await wallet_for(s, user.id)
    await s.commit()
    return PurchaseOut(demo=True, wallet=w)
