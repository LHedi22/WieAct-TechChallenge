"""GET /api/economy (every price and reward the UI shows) and GET /api/wallet.

The wallet is a placeholder until M5 adds the coin and point ledgers: today's free coins, 0 points,
no streak, and the real next refill time (Tunis midnight)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core import economy

router = APIRouter(prefix="/api", tags=["economy"])


class Wallet(BaseModel):
    coins: int
    free_today: int
    earned: int
    purchased: int
    points: int
    streak: int
    refill_at: datetime
    placeholder: bool  # true until the ledgers exist (M5)


@router.get("/economy")
async def get_economy() -> dict[str, Any]:
    return economy.as_dict()


@router.get("/wallet", response_model=Wallet)
async def get_wallet(user: CurrentUser) -> Wallet:
    _ = user  # per-user balances come with the ledgers (M5)
    return Wallet(
        coins=economy.DAILY_FREE_COINS,
        free_today=economy.DAILY_FREE_COINS,
        earned=0,
        purchased=0,
        points=0,
        streak=0,
        refill_at=economy.next_refill(),
        placeholder=True,
    )
