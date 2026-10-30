"""Daily challenges: 3 per student per Tunis day. The first read writes an instant rule plan and
enqueues ONE DAILY_PLAN job (mid, plan-once, background) that may replace it while no progress
has been made. Progress comes from real events (`record`); each done challenge earns coins
(within the daily cap) + points, all 3 a bonus — idempotent through the ledger refs."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.core.wallet_rules import tunis_day
from app.features.daily import plan
from app.features.wallet import service as wallet
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import (
    Chapter,
    ChapterMastery,
    Course,
    DailyState,
    Flashcard,
    Job,
    Mistake,
    Profile,
    User,
    WorldMember,
)

KIND = "DAILY_PLAN"
MAX_CANDIDATES = 12  # chapters shown to the model
MISTAKE_DAYS = 14


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def candidates(s: AsyncSession, user_id: uuid.UUID) -> list[plan.Candidate]:
    rows = (
        await s.execute(
            select(Course, Chapter, ChapterMastery.mastery, ChapterMastery.weak)
            .join(WorldMember, WorldMember.world_id == Course.world_id)
            .join(Chapter, Chapter.course_id == Course.id)
            .outerjoin(
                ChapterMastery,
                (ChapterMastery.chapter_id == Chapter.id) & (ChapterMastery.user_id == user_id),
            )
            .where(WorldMember.user_id == user_id)
            .order_by(Course.world_id, Course.color_key, Course.name, Chapter.idx)
        )
    ).all()
    return [
        plan.Candidate(
            world_id=course.world_id,
            course_id=course.id,
            chapter_id=chapter.id,
            course=course.name,
            chapter=chapter.title,
            mastery=mastery,
            weak=bool(weak),
            exam_date=course.exam_date,
        )
        for course, chapter, mastery, weak in rows
    ]


async def today_state(
    s: AsyncSession, user: User, now: datetime | None = None
) -> tuple[DailyState, bool]:
    """Today's row, created with the rule plan (+ one DAILY_PLAN job) on the first read.
    Returns (state, created). Commits."""
    now = _now(now)
    day = tunis_day(now)
    state = await s.get(DailyState, (user.id, day))
    if state is not None:
        return state, False
    profile = await s.get(Profile, user.id)
    cands = await candidates(s, user.id)
    rule = plan.rule_plan(cands, day, profile.style_teaching if profile else 25)
    res = await s.execute(
        insert(DailyState)
        .values(user_id=user.id, date=day, challenges=rule, planned_by="rule")
        .on_conflict_do_nothing(index_elements=["user_id", "date"])
        .returning(DailyState.user_id)
    )
    created = res.scalar() is not None
    state = await s.get(DailyState, (user.id, day), populate_existing=True)
    if created and cands:  # nothing to plan without chapters: the rule plan stands
        j = await create_job(
            s,
            kind=KIND,
            lane="background",
            payload={"date": day.isoformat()},
            user_id=user.id,
        )
        state.plan_job_id = j.id
    await s.commit()
    return state, created


def reminder_due(profile: Profile | None, state: DailyState, now: datetime) -> bool:
    if profile is None or profile.reminder_time is None:
        return False
    local = now.astimezone(economy.TZ)
    return local.time() >= profile.reminder_time and not all(c["done"] for c in state.challenges)


# --- the plan-once job -------------------------------------------------------------------------
def _chapters_text(cands: list[plan.Candidate], today: date) -> str:
    lines = []
    for i, c in enumerate(cands, 1):
        mastery = f"{c.mastery}%" if c.mastery is not None else "not quizzed yet"
        exam = (
            f", exam in {(c.exam_date - today).days} days"
            if c.exam_date and c.exam_date >= today
            else ""
        )
        weak = ", weak spot" if c.weak else ""
        lines.append(f"{i}. {c.course} · {c.chapter} (mastery {mastery}{weak}{exam})")
    return "\n".join(lines)


FLASHCARDS_LINE = (
    '- "flashcards": review {} flashcards in the Study Studio ("chapter" may be null).'
)


async def _has_cards(s: AsyncSession, user_id: uuid.UUID, chapter_ids: list[uuid.UUID]) -> bool:
    """Flashcards can be planned only for a student with cards: their own, or a class deck."""
    found = await s.scalar(
        select(Flashcard.id)
        .where(
            or_(
                Flashcard.user_id == user_id,
                Flashcard.chapter_id.in_(chapter_ids) & Flashcard.asset_id.is_not(None),
            )
        )
        .limit(1)
    )
    return found is not None


@job(KIND, stages=("planning_your_day",))
async def plan_day(ctx: JobContext) -> dict[str, Any]:
    day = date.fromisoformat(ctx.payload["date"])
    async with db.get_sessionmaker()() as s:
        user = await s.get(User, (await s.get(Job, ctx.job_id)).user_id)
        profile = await s.get(Profile, user.id)
        cands = plan.ranked(await candidates(s, user.id), day)[:MAX_CANDIDATES]
        since = datetime.now(UTC) - timedelta(days=MISTAKE_DAYS)
        mistakes = (
            await s.execute(
                select(Mistake.concept, Mistake.mistake_type, func.count())
                .where(Mistake.user_id == user.id, Mistake.created_at > since)
                .group_by(Mistake.concept, Mistake.mistake_type)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        has_cards = await _has_cards(s, user.id, [c.chapter_id for c in cands])
    await ctx.set_stage("planning_your_day")
    p = profile
    version, messages = prompts.render(
        "daily_plan",
        language=user.ui_language,
        quiz_questions_targets="/".join(map(str, plan.TARGETS["quiz_questions"])),
        quiz_score_targets="/".join(map(str, plan.TARGETS["quiz_score"])),
        flashcards_line=FLASHCARDS_LINE.format("/".join(map(str, plan.TARGETS["flashcards"])))
        if has_cards
        else "",
        visual=p.style_visual if p else 25,
        practice=p.style_practice if p else 25,
        listening=p.style_listening if p else 25,
        teaching=p.style_teaching if p else 25,
        goal=(p.goal if p and p.goal else "pass"),
        minutes=(p.daily_minutes if p and p.daily_minutes else 30),
        chapters=_chapters_text(cands, day) or "(none)",
        mistakes="\n".join(f"- {c} ({k}) ×{n}" for c, k, n in mistakes) or "(none)",
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.DAILY_PLAN,
                lane="background",
                messages=messages,
                language=user.ui_language,
                cache_key=f"daily:{user.id}:{day.isoformat()}:v{version}",
                prompt_version=version,
            )
        )
    )
    async with db.get_sessionmaker()() as s:
        state = await s.get(DailyState, (user.id, day), with_for_update=True)
        if state is None or any(c["progress"] for c in state.challenges):
            await s.commit()
            return {"applied": False}
        challenges, message = plan.from_ai(result.content, cands, state.challenges, has_cards)
        state.challenges = challenges
        state.plan = {"message": message, "quick_mode": result.quick_mode}
        state.planned_by = "ai"
        await s.commit()
    return {"applied": True, "types": [c["type"] for c in challenges]}


# --- progress from real events -----------------------------------------------------------------
async def record(
    s: AsyncSession,
    user_id: uuid.UUID,
    event: str,
    *,
    chapter_id: uuid.UUID | None = None,
    amount: int = 1,
    score_pct: int | None = None,
    now: datetime | None = None,
) -> list[int]:
    """Apply a learning event to today's challenges; rewards what just got done. Does not commit
    (runs inside the caller's transaction). No row today (the student never opened the app
    today) → nothing to track. Returns the indexes completed by this event."""
    now = _now(now)
    day = tunis_day(now)
    state = await s.get(DailyState, (user_id, day), with_for_update=True, populate_existing=True)
    if state is None:
        return []
    challenges = [dict(c) for c in state.challenges]
    cid = str(chapter_id) if chapter_id else None
    done_now = [
        i for i, c in enumerate(challenges) if plan.advance(c, event, cid, amount, score_pct)
    ]
    if challenges == state.challenges:
        return []
    state.challenges = challenges
    for i in done_now:
        c = challenges[i]
        world = uuid.UUID(c["world_id"]) if c.get("world_id") else None
        ref = f"{day.isoformat()}:{i}"
        await wallet.earn(s, user_id, economy.EARN["daily_challenge"], f"challenge:{ref}", now)
        await wallet.add_points(
            s, user_id, world, economy.POINTS["daily_challenge"], "challenge", ref
        )
    if done_now and all(c["done"] for c in challenges):
        world = next((uuid.UUID(c["world_id"]) for c in challenges if c.get("world_id")), None)
        bonus = economy.POINTS["all_challenges_bonus"]
        await wallet.add_points(s, user_id, world, bonus, "challenges_all", day.isoformat())
    await s.flush()
    return done_now
