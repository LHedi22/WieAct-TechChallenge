"""GET /api/leaderboard?scope=world|global&period=week|all&world_id=…"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.db import get_session
from app.features.leaderboard.service import Board, Period, Scope, board
from app.features.worlds.service import NotFound, member_world

router = APIRouter(prefix="/api", tags=["leaderboard"])


@router.get("/leaderboard", response_model=Board)
async def get_leaderboard(
    user: CurrentUser,
    s: Annotated[AsyncSession, Depends(get_session)],
    scope: Scope = "world",
    period: Period = "week",
    world_id: uuid.UUID | None = None,
) -> Board:
    if scope == "world":
        if world_id is None:
            raise HTTPException(400, "errors.world_required")
        try:
            await member_world(s, user, world_id)
        except NotFound as e:
            raise HTTPException(404, "errors.world_not_found") from e
    return await board(s, user, scope, period, world_id)
