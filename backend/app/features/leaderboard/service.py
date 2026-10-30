"""Leaderboards from the points ledger (PRODUCT.md §Leaderboards): per world or global, this week
(Monday 00:00 Tunis) or all time. Opting out is respected: a hidden student stays in their class
board as "Hidden explorer" (ranks stay honest) and is left out of the global board."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy
from app.core.wallet_rules import tunis_day
from app.models import PointsLedger, Profile, User, WorldMember

TOP = 20

Scope = Literal["world", "global"]
Period = Literal["week", "all"]


class Entry(BaseModel):
    rank: int
    nickname: str | None  # None = "Hidden explorer"
    avatar: dict[str, Any] | None
    points: int
    is_me: bool


class Board(BaseModel):
    scope: Scope
    period: Period
    since: datetime | None
    entries: list[Entry]
    me: Entry | None  # also given when outside the top; None when hidden from the global board
    opted_in: bool


def week_start(now: datetime) -> datetime:
    day = tunis_day(now)
    monday = day - timedelta(days=day.weekday())
    return datetime.combine(monday, time(0), tzinfo=economy.TZ).astimezone(UTC)


async def board(
    s: AsyncSession,
    me: User,
    scope: Scope,
    period: Period,
    world_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Board:
    since = week_start(now or datetime.now(UTC)) if period == "week" else None
    pts = select(PointsLedger.user_id, func.sum(PointsLedger.delta).label("points"))
    if scope == "world":
        pts = pts.where(PointsLedger.world_id == world_id)
    if since is not None:
        pts = pts.where(PointsLedger.created_at >= since)
    pts = pts.group_by(PointsLedger.user_id).subquery()

    opted_in = func.coalesce(Profile.leaderboard_opt_in, True)
    q = (
        select(User.id, User.nickname, Profile.avatar, opted_in, pts.c.points)
        .join(pts, pts.c.user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
    )
    if scope == "world":
        q = q.join(
            WorldMember, (WorldMember.user_id == User.id) & (WorldMember.world_id == world_id)
        )
    else:
        q = q.where(opted_in.is_(True))
    rows = (await s.execute(q.order_by(pts.c.points.desc(), User.nickname))).all()

    entries = []
    mine = None
    for i, (uid, nickname, avatar, visible, points) in enumerate(rows, start=1):
        e = Entry(
            rank=i,
            nickname=nickname if visible else None,
            avatar=avatar if visible else None,
            points=int(points),
            is_me=uid == me.id,
        )
        if e.is_me:
            mine = e
        if i <= TOP:
            entries.append(e)
    my_profile = await s.get(Profile, me.id)
    return Board(
        scope=scope,
        period=period,
        since=since,
        entries=entries,
        me=mine,
        opted_in=my_profile.leaderboard_opt_in if my_profile else True,
    )
