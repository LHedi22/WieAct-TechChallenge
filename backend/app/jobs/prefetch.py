"""Background prefetch, so students find content ready instead of waiting (decided 2026-11-14,
DECISIONS.md).

`plan(s, world_id, …)` queues, in the background lane, what a world's class will open next and
nobody has made yet: per (chapter, level, language) the quiz set, the study pack and the audio
episode, and per (course, language) the placement quiz. Languages are the ones the world's
members use; levels are intermediate for every language plus each placed member's own level in
their language. Which chapters: the caller's (a trigger), else the first two ready chapters of
each course.

Prefetch jobs are ownerless and free (user_id None, cost 0): they never reserve from a wallet or
the Class Pool, and what they make is shared class content, free when opened like any cached
asset (ECONOMY.md). A student who needs it while it is still queued joins the job and promotes it
(`create_or_join_shared_job` / `promote`). The limiter keeps a call slot for students
(LLM_INTERACTIVE_RESERVED), so prefetch never makes a student wait for a slot.

Mid compute is the scarce resource, and anyone can create a world and upload files, so three
daily caps bound what prefetch may spend (Tunis day): per world, per creator (all their worlds
share one budget) and for the whole app. When a cap is near, the least useful work is dropped
first: audio, then study packs, then quiz sets, placement last.

Calls per set (code): quiz 1 compact + 1 mid (+1 + 1 on regeneration), study pack 1 mid + 2
compact (+ the chapter glossary, ≤ 1 compact), audio 1 mid, placement 1 compact + 1 mid.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy, flags
from app.core.config import get_settings
from app.core.db import reuse
from app.core.provenance import servable
from app.core.wallet_rules import tunis_day
from app.gateway.providers import paused_until
from app.jobs.service import (
    P_COURSE_START,
    P_DEFAULT,
    P_EXTRA,
    P_NEXT_CHAPTER,
    AIPaused,
    create_or_join_shared_job,
    eta_s,
    share_key,
)
from app.models import (
    AICallLog,
    Chapter,
    Course,
    CourseLevel,
    Document,
    Job,
    PlacementSet,
    Presence,
    QuizAttempt,
    QuizSet,
    User,
    World,
    WorldMember,
)

log = logging.getLogger("prefetch")

BASE_LEVEL = "intermediate"
FIRST_CHAPTERS = 2

# Kind names as in each feature's KIND (imported lazily below: features build on jobs).
PLACEMENT, QUIZ, PACK, AUDIO = "PLACEMENT", "QUIZ_POOL", "STUDY_PACK", "AUDIO_EPISODE"
# Order inside one prefetch set (background lane, lower first; ties run oldest first).
PRIORITY = {PLACEMENT: P_COURSE_START, QUIZ: P_NEXT_CHAPTER, PACK: P_NEXT_CHAPTER, AUDIO: P_EXTRA}
# Mid calls one job is expected to make, for the caps (regenerations are counted once made).
EXPECTED_MID = {PLACEMENT: 1, QUIZ: 1, PACK: 1, AUDIO: 1}
# What a cap drops first: audio, then packs, then quiz sets, placement last.
KEEP_ORDER = (PLACEMENT, QUIZ, PACK, AUDIO)


def priority(kind: str) -> int:
    return PRIORITY.get(kind, P_NEXT_CHAPTER)


@dataclass(frozen=True)
class Wanted:
    kind: str
    key: str
    payload: dict[str, Any]
    chapter_idx: int


# --- what the class needs ------------------------------------------------------------------------


async def member_languages(s: AsyncSession, world: World) -> list[str]:
    rows = await s.scalars(
        select(User.ui_language)
        .where(
            (User.id == world.creator_id)
            | User.id.in_(select(WorldMember.user_id).where(WorldMember.world_id == world.id))
        )
        .distinct()
    )
    return sorted(set(rows))


async def level_pairs(s: AsyncSession, world: World, course_id: uuid.UUID) -> set[tuple[str, str]]:
    """(level, language) to make: intermediate in every member language, plus each placed
    member's own level in their own language (never a level nobody in that language has)."""
    pairs = {(BASE_LEVEL, lang) for lang in await member_languages(s, world)}
    placed = await s.execute(
        select(CourseLevel.level, User.ui_language)
        .join(User, User.id == CourseLevel.user_id)
        .join(
            WorldMember,
            and_(WorldMember.user_id == CourseLevel.user_id, WorldMember.world_id == world.id),
        )
        .where(CourseLevel.course_id == course_id)
        .distinct()
    )
    return pairs | {(level, lang) for level, lang in placed}


async def chapter_ready(s: AsyncSession, chapter_id: uuid.UUID) -> bool:
    """Every document of the chapter finished indexing and at least one is ready."""
    statuses = set(
        await s.scalars(select(Document.status).where(Document.chapter_id == chapter_id))
    )
    return "ready" in statuses and statuses <= {"ready", "failed"}


async def ready_chapters(s: AsyncSession, course_id: uuid.UUID) -> list[Chapter]:
    chapters = await s.scalars(
        select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.idx)
    )
    return [c for c in chapters if await chapter_ready(s, c.id)]


async def next_chapter(s: AsyncSession, chapter: Chapter) -> Chapter | None:
    """The chapter after this one in its course, if its material is indexed."""
    nxt = await s.scalar(
        select(Chapter)
        .where(Chapter.course_id == chapter.course_id, Chapter.idx > chapter.idx)
        .order_by(Chapter.idx)
        .limit(1)
    )
    return nxt if nxt is not None and await chapter_ready(s, nxt.id) else None


async def _quiz_made(s: AsyncSession, chapter_id: uuid.UUID, level: str, language: str) -> bool:
    from app.features.quiz import pool  # noqa: PLC0415  (quiz builds on jobs)

    found = await s.scalar(
        select(QuizSet.id).where(
            QuizSet.chapter_id == chapter_id,
            QuizSet.level == level,
            QuizSet.language == language,
            servable(QuizSet.provider),
            pool.shareable(QuizSet.questions),
        )
    )
    return found is not None


async def _missing_for_chapter(
    s: AsyncSession, chapter: Chapter, level: str, language: str, reason: str
) -> list[Wanted]:
    from app.features.audio import service as audio  # noqa: PLC0415
    from app.features.quiz import pool  # noqa: PLC0415
    from app.features.studio import pack  # noqa: PLC0415

    base = {
        "chapter_id": str(chapter.id),
        "level": level,
        "language": language,
        "prefetch": True,
        "reason": reason,
    }
    out = []
    if not await _quiz_made(s, chapter.id, level, language):
        seed = await pool.next_seed(s, chapter.id, level, language)
        key = pool.share(chapter.id, level, language)
        out.append(Wanted(QUIZ, key, {**base, "seed": seed}, chapter.idx))
    found = await pack.assets(s, chapter.id, level, language)
    if "notes" not in found:
        key = share_key(pack.KIND, chapter.id, level, language)
        out.append(Wanted(PACK, key, {**base, "paid_by": None}, chapter.idx))
    if audio.ASSET not in found:
        key = share_key(audio.KIND, chapter.id, level, language)
        out.append(Wanted(AUDIO, key, {**base, "paid_by": None}, chapter.idx))
    return out


async def _placement_missing(
    s: AsyncSession, course: Course, language: str, reason: str
) -> Wanted | None:
    made = await s.scalar(
        select(PlacementSet.id).where(
            PlacementSet.course_id == course.id,
            PlacementSet.language == language,
            servable(PlacementSet.provider),
        )
    )
    if made is not None:
        return None
    payload = {"course_id": str(course.id), "language": language, "prefetch": True}
    return Wanted(
        PLACEMENT, share_key(PLACEMENT, course.id, language), payload | {"reason": reason}, -1
    )


# --- the mid caps --------------------------------------------------------------------------------


def _day_start() -> datetime:
    return datetime.combine(tunis_day(), time.min, tzinfo=economy.TZ)


async def mid_used(s: AsyncSession, world: World) -> dict[str, int]:
    """Prefetch mid calls today (Tunis day) for this world, its creator's worlds and the whole
    app, plus the mid calls still expected from queued prefetch jobs. Cache hits and debug
    replays are no platform calls."""
    is_prefetch = Job.payload["prefetch"].astext == "true"
    scopes = (
        func.count().filter(Job.world_id == world.id),
        func.count().filter(World.creator_id == world.creator_id),
        func.count(),
    )
    made = (
        await s.execute(
            select(*scopes)
            .select_from(AICallLog)
            .join(Job, Job.id == AICallLog.job_id)
            .join(World, World.id == Job.world_id, isouter=True)
            .where(
                is_prefetch,
                AICallLog.model_tier == "mid",
                AICallLog.cache_hit.is_(False),
                AICallLog.debug.is_(False),
                AICallLog.ts >= _day_start(),
            )
        )
    ).one()
    queued = (
        await s.execute(
            select(*scopes)
            .select_from(Job)
            .join(World, World.id == Job.world_id, isouter=True)
            .where(is_prefetch, Job.status == "queued", Job.attempts == 0)
        )
    ).one()
    return {
        "world": made[0] + queued[0],
        "creator": made[1] + queued[1],
        "all": made[2] + queued[2],
    }


def caps() -> dict[str, int]:
    settings = get_settings()
    return {
        "world": settings.PREFETCH_MAX_MID_PER_WORLD_PER_DAY,
        "creator": settings.PREFETCH_MAX_MID_PER_CREATOR_PER_DAY,
        "all": settings.PREFETCH_MAX_MID_PER_DAY,
    }


async def mid_left(s: AsyncSession, world: World) -> int:
    used = await mid_used(s, world)
    return max(0, min(cap - used[scope] for scope, cap in caps().items()))


# --- the planner ---------------------------------------------------------------------------------


async def _paused(s: AsyncSession) -> bool:
    offline, _ = await paused_until(get_settings(), reuse(s))  # no 2nd connection (OPT-34)
    return offline or (await flags.load(reuse(s))).pause_background_lane


async def plan(
    s: AsyncSession,
    world_id: uuid.UUID,
    *,
    reason: str,
    chapter_id: uuid.UUID | None = None,
    level: str | None = None,
    language: str | None = None,
    placement: bool | None = None,
) -> list[uuid.UUID]:
    """Queue what the class is missing (see the module docstring). `chapter_id`, `level` and
    `language` narrow it; placement is planned for whole-world plans unless `placement` says
    otherwise. Returns the jobs queued now; nothing when switched off, paused or offline, or
    when it all exists or is already queued. Idempotent."""
    if not get_settings().PREFETCH_ENABLED or await _paused(s):
        return []
    world = await s.get(World, world_id)
    if world is None:
        return []
    if chapter_id is not None:
        chapter = await s.get(Chapter, chapter_id)
        if chapter is None or not await chapter_ready(s, chapter.id):
            return []
        courses = [await s.get(Course, chapter.course_id)]
        chapters_of = {courses[0].id: [chapter]}
    else:
        courses = list(await s.scalars(select(Course).where(Course.world_id == world.id)))
        chapters_of = {c.id: (await ready_chapters(s, c.id))[:FIRST_CHAPTERS] for c in courses}
    with_placement = chapter_id is None if placement is None else placement

    wanted: list[Wanted] = []
    for course in courses:
        if not chapters_of[course.id]:
            continue
        if level is not None and language is not None:  # one student's next chapter
            pairs = [(level, language)]
        else:
            pairs = sorted(
                (lv, lang)
                for lv, lang in await level_pairs(s, world, course.id)
                if (level is None or lv == level) and (language is None or lang == language)
            )
        if with_placement:
            for lang in sorted({lang for _, lang in pairs}):
                if (w := await _placement_missing(s, course, lang, reason)) is not None:
                    wanted.append(w)
        for chapter in chapters_of[course.id]:
            for lv, lang in pairs:
                wanted += await _missing_for_chapter(s, chapter, lv, lang, reason)
    if not wanted:
        return []
    busy = set(
        await s.scalars(
            select(Job.share_key).where(
                Job.share_key.in_([w.key for w in wanted]), Job.status.in_(("queued", "running"))
            )
        )
    )
    wanted = [w for w in wanted if w.key not in busy]
    wanted.sort(key=lambda w: (KEEP_ORDER.index(w.kind), w.chapter_idx))

    left, queued, dropped = await mid_left(s, world), [], 0
    for w in wanted:
        if EXPECTED_MID[w.kind] > left:
            dropped += 1
            continue
        try:
            job_id, created = await create_or_join_shared_job(
                s,
                kind=w.kind,
                share_key=w.key,
                lane="background",
                payload=w.payload,
                world_id=world.id,
                priority=priority(w.kind),
            )
        except AIPaused:  # offline switched on meanwhile
            break
        if created:
            left -= EXPECTED_MID[w.kind]
            queued.append(job_id)
    if queued or dropped:
        log.info(
            "prefetch (%s): world %s, %d job(s) queued, %d dropped by the mid caps",
            reason,
            world.id,
            len(queued),
            dropped,
        )
    return queued


# --- triggers: events only, never a polled GET (each one idempotent) ------------------------------


async def precompute_chapter(s: AsyncSession, chapter_id: uuid.UUID) -> list[uuid.UUID]:
    """A chapter finished indexing (upload or REFRESH_CONTENT). With prefetch on, it is planned
    for the whole class if it is one of the course's first two ready chapters, or if a member is
    already on the chapter before it (a quiz attempt or presence there). With prefetch off, the M2
    precompute stays: the chapter's first intermediate quiz set in the creator's language."""
    chapter = await s.get(Chapter, chapter_id)
    if chapter is None or not await chapter_ready(s, chapter_id):
        return []
    course = await s.get(Course, chapter.course_id)
    if not get_settings().PREFETCH_ENABLED:
        return [j] if (j := await _first_quiz_set(s, chapter, course)) else []
    if not await _wanted_now(s, chapter, course.world_id):
        return []
    return await plan(
        s, course.world_id, reason="chapter_ready", chapter_id=chapter_id, placement=True
    )


async def _wanted_now(s: AsyncSession, chapter: Chapter, world_id: uuid.UUID) -> bool:
    """One query: fewer than FIRST_CHAPTERS ready chapters before it, or a member's quiz attempt
    or presence on the chapter right before it."""
    earlier_ready = (
        select(func.count(func.distinct(Chapter.id)))
        .join(Document, Document.chapter_id == Chapter.id)
        .where(
            Chapter.course_id == chapter.course_id,
            Chapter.idx < chapter.idx,
            Document.status == "ready",
        )
        .scalar_subquery()
    )
    previous = (
        select(Chapter.id)
        .where(Chapter.course_id == chapter.course_id, Chapter.idx < chapter.idx)
        .order_by(Chapter.idx.desc())
        .limit(1)
        .scalar_subquery()
    )
    members = select(WorldMember.user_id).where(WorldMember.world_id == world_id)
    on_previous = (
        select(QuizAttempt.id)
        .where(QuizAttempt.chapter_id == previous, QuizAttempt.user_id.in_(members))
        .exists()
        | select(Presence.user_id)
        .where(Presence.chapter_id == previous, Presence.user_id.in_(members))
        .exists()
    )
    return bool(await s.scalar(select((earlier_ready < FIRST_CHAPTERS) | on_previous)))


async def on_join(s: AsyncSession, world: World, user: User) -> list[uuid.UUID]:
    """A new member: if nobody in the world uses their language yet, plan chapters 1–2 and the
    placement quiz in it (one query decides)."""
    others = await s.scalar(
        select(
            select(User.id)
            .where(
                User.id != user.id,
                User.ui_language == user.ui_language,
                (User.id == world.creator_id)
                | User.id.in_(select(WorldMember.user_id).where(WorldMember.world_id == world.id)),
            )
            .exists()
        )
    )
    if others:
        return []
    return await plan(s, world.id, reason="join", language=user.ui_language)


async def on_placement(
    s: AsyncSession, user: User, course: Course, level: str, weak: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Placement finished: the chapter the student starts on (their first weak chapter, else the
    first ready one) at their level, and the chapter after it."""
    chapters = await ready_chapters(s, course.id)
    if not chapters:
        return []
    start = next((c for c in chapters if c.id in set(weak)), chapters[0])
    queued = await plan(
        s,
        course.world_id,
        reason="placement",
        chapter_id=start.id,
        level=level,
        language=user.ui_language,
    )
    return queued + await plan_next(s, user, start, level, reason="placement")


async def student_level(s: AsyncSession, user: User, course_id: uuid.UUID) -> str:
    """The level a student was placed at for this course (intermediate before placement); never
    a level sent by the browser."""
    level = await s.scalar(
        select(CourseLevel.level).where(
            CourseLevel.user_id == user.id, CourseLevel.course_id == course_id
        )
    )
    return level or BASE_LEVEL


async def _first_quiz_set(s: AsyncSession, chapter: Chapter, course: Course) -> uuid.UUID | None:
    from app.features.quiz import pool  # noqa: PLC0415

    world = await s.get(World, course.world_id)
    creator = await s.get(User, world.creator_id)
    language = creator.ui_language if creator else "en"
    made = await s.scalar(
        select(QuizSet.id).where(
            QuizSet.chapter_id == chapter.id,
            QuizSet.level == BASE_LEVEL,
            QuizSet.language == language,
            servable(QuizSet.provider),
        )
    )
    if made or await pool.pending_generation(s, chapter.id, BASE_LEVEL, language):
        return None
    try:
        job_id, created = await create_or_join_shared_job(
            s,
            kind=pool.KIND,
            share_key=pool.share(chapter.id, BASE_LEVEL, language),
            lane="background",
            payload={
                "chapter_id": str(chapter.id),
                "level": BASE_LEVEL,
                "language": language,
                "seed": 1,
            },
            world_id=world.id,
            priority=P_DEFAULT,
        )
    except AIPaused:
        return None
    return job_id if created else None


async def plan_next(
    s: AsyncSession, user: User, chapter: Chapter, level: str, *, reason: str = "next_chapter"
) -> list[uuid.UUID]:
    """Chapter N+1 for this student's level and language (a quiz finished, a building opened
    or a generation started on chapter N)."""
    nxt = await next_chapter(s, chapter)
    if nxt is None:
        return []
    course = await s.get(Course, nxt.course_id)
    return await plan(
        s,
        course.world_id,
        reason=reason,
        chapter_id=nxt.id,
        level=level,
        language=user.ui_language,
    )


async def safely(s: AsyncSession, user: User, chapter: Chapter, level: str) -> None:
    """plan_next from a student's request: best effort, never fails the request."""
    await guard(s, plan_next(s, user, chapter, level))


async def guard(s: AsyncSession, planning) -> None:
    """Run a trigger from a request or a job: best effort, never fails the caller."""
    try:
        await planning
    except Exception:  # noqa: BLE001  (prefetch is an optimisation)
        await s.rollback()
        log.exception("prefetch planning failed")


async def preparing(s: AsyncSession, job_id: uuid.UUID | None) -> dict[str, Any] | None:
    """{job_id, eta_s} while a background job (a prefetch) makes this content, for the
    "Being prepared · about N min" note and its "Get it now" button."""
    if job_id is None:
        return None
    job = await s.get(Job, job_id)
    if job is None or job.lane != "background" or job.status not in ("queued", "running"):
        return None
    return {"job_id": job.id, "eta_s": max(1, round(await eta_s(s, job)))}


# --- CLI: the jury-slot warm-up ------------------------------------------------------------------


async def _cli(code: str) -> int:
    from app.core.db import get_sessionmaker  # noqa: PLC0415

    async with get_sessionmaker()() as s:
        world = await s.scalar(select(World).where(World.join_code == code.upper()))
        if world is None:
            print(f"no world with join code {code}")
            return 1
        queued = await plan(s, world.id, reason="cli")
        used, cap = await mid_used(s, world), caps()
    print(f"{len(queued)} prefetch job(s) queued for {world.name}; the worker runs them")
    print("mid today (made + expected): " + ", ".join(f"{k} {used[k]}/{cap[k]}" for k in cap))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Queue a world's prefetch now (no AI call here).")
    ap.add_argument("--world", required=True, help="join code")
    raise SystemExit(asyncio.run(_cli(ap.parse_args().world)))
