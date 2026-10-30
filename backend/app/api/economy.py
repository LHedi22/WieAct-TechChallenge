"""GET /api/economy: every price and reward the UI shows (the wallet is app/features/wallet)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import economy

router = APIRouter(prefix="/api", tags=["economy"])


class BuildingCost(BaseModel):
    cost: int
    free_if_cached: bool = False
    answer_cost: int | None = None


class CoinPack(BaseModel):
    coins: int
    price_tnd: int


class ExamPass(BaseModel):
    days: int
    price_tnd: int


class Products(BaseModel):
    coin_pack: CoinPack
    exam_pass: ExamPass


class EconomyOut(BaseModel):
    daily_free_coins: int
    daily_earn_cap: int
    exam_pass_daily_limit: int
    cost: dict[str, int]
    earn: dict[str, int]
    points: dict[str, int]
    peer_answer_threshold: int
    products: Products
    cosmetics: dict[str, int]
    buildings: dict[str, BuildingCost]


@router.get("/economy", response_model=EconomyOut)
async def get_economy() -> dict[str, Any]:
    return economy.as_dict()
