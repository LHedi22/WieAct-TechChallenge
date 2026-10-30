"""GET /api/daily (daily return screen + map side panel) and POST /api/daily/seen."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.core import economy
from app.core.wallet_rules import tunis_day
from app.features.daily import service
from app.features.wallet import service as wallet
from app.models import DailyState, Profile

router = APIRouter(prefix="/api/daily", tags=["daily"])


class Challenge(BaseModel):
    type: str  # quiz_questions | quiz_score | teachback | tutor_session
    target: int
    progress: int
    done: bool
    why: str | None
    world_id: uuid.UUID | None
    course_id: uuid.UUID | None
    chapter_id: uuid.UUID | None
    course: str | None
    chapter: str | None


class Daily(BaseModel):
    date: date
    challenges: list[Challenge]
    all_done: bool
    planned_by: str  # rule | ai
    plan_job_id: uuid.UUID | None
    message: str | None
    first_open_today: bool
    returning: bool  # signed up before today: the daily return screen is for them
    reminder_due: bool
    coins: int
    free_today: int
    streak: int
    refill_at: datetime


async def _view(s: Session, user, state: DailyState, now: datetime) -> Daily:
    b = await wallet.balances(s, user.id, now)
    profile = await s.get(Profile, user.id)
    return Daily(
        date=state.date,
        challenges=[Challenge(**c) for c in state.challenges],
        all_done=all(c["done"] for c in state.challenges),
        planned_by=state.planned_by,
        plan_job_id=state.plan_job_id,
        message=(state.plan or {}).get("message"),
        first_open_today=state.seen_at is None,
        returning=tunis_day(user.created_at) < state.date,
        reminder_due=service.reminder_due(profile, state, now),
        coins=b.coins,
        free_today=b.free,
        streak=await wallet.current_streak(s, user.id, now),
        refill_at=economy.next_refill(now),
    )


@router.get("", response_model=Daily)
async def get_daily(s: Session, user: CurrentUser) -> Daily:
    now = datetime.now(UTC)
    state, _ = await service.today_state(s, user, now)
    view = await _view(s, user, state, now)
    await s.commit()  # keeps today's free-coin grant
    return view


@router.post("/seen", response_model=Daily)
async def seen(s: Session, user: CurrentUser) -> Daily:
    now = datetime.now(UTC)
    state, _ = await service.today_state(s, user, now)
    if state.seen_at is None:
        state.seen_at = now
    view = await _view(s, user, state, now)
    await s.commit()
    return view
