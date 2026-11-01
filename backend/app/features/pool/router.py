"""GET/POST /api/worlds/{id}/pool — the Class Pool's balance, recent gifts, and giving coins."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.features.pool import service
from app.features.worlds.service import NotFound, member_world

router = APIRouter(prefix="/api/worlds", tags=["pool"])


class Gift(BaseModel):
    nickname: str
    coins: int


class PoolOut(BaseModel):
    balance: int
    max_contribution: int
    recent: list[Gift]


class GiveIn(BaseModel):
    amount: int


async def _view(s: Session, world_id: uuid.UUID) -> PoolOut:
    return PoolOut(
        balance=await service.balance(s, world_id),
        max_contribution=service.MAX_CONTRIBUTION,
        recent=[Gift(nickname=n, coins=c) for n, c in await service.recent(s, world_id)],
    )


async def _member(s: Session, user, world_id: uuid.UUID) -> None:
    try:
        await member_world(s, user, world_id)
    except NotFound as e:
        raise HTTPException(404, e.key) from e


@router.get("/{world_id}/pool", response_model=PoolOut)
async def get_pool(world_id: uuid.UUID, s: Session, user: CurrentUser) -> PoolOut:
    await _member(s, user, world_id)
    return await _view(s, world_id)


@router.post("/{world_id}/pool", response_model=PoolOut)
async def give(world_id: uuid.UUID, body: GiveIn, s: Session, user: CurrentUser) -> PoolOut:
    await _member(s, user, world_id)
    try:
        await service.contribute(s, user, world_id, body.amount)
    except service.BadAmount as e:
        raise HTTPException(400, e.key) from e
    out = await _view(s, world_id)
    await s.commit()
    return out
