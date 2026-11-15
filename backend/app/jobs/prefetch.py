"""Background prefetch, one chapter ahead (Group E; decided 2026-11-14, DECISIONS.md).

A student who finishes a quiz or opens the Study Studio on chapter N is likely to need chapter
N+1 next, so its quiz set and study pack for the same level and language are queued now, in the
background lane at P_NEXT_CHAPTER. The limiter keeps a call slot for students
(LLM_INTERACTIVE_RESERVED), so prefetch never makes a student wait for a slot.

Prefetch jobs are ownerless and free (user_id None, cost 0): they never reserve from a wallet or
the Class Pool, and what they make is shared class content, free when opened like any cached
asset. A student who needs it while it is still queued joins the job and promotes it to the
interactive lane (`create_or_join_shared_job` → `promote`).

Not prefetched: audio episodes (first in the scope guard, one mid call each, few students open
them) and placement (it already precomputes per course).

Extra platform calls, at most once per class × next chapter × level × language, and only when
nobody has made that content yet: quiz set 1 compact + 1 mid (+1 + 1 if fewer than 5 items
survive the check), study pack 1 mid + 2 compact, chapter glossary ≤ 1 compact. The calls are
wasted only if no student in that level and language opens the next chapter's quiz or pack.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import reuse
from app.core.provenance import servable
from app.gateway.providers import paused_until
from app.jobs.service import (
    P_COURSE_START,
    P_EXTRA,
    P_NEXT_CHAPTER,
    create_or_join_shared_job,
    eta_s,
    share_key,
)
from app.models import Chapter, Course, Document, Job, QuizSet, User

log = logging.getLogger("prefetch")

# Order inside one prefetch set (background lane, lower first; ties run oldest first). Kind
# names as in each feature's KIND (imported lazily below: features build on jobs).
PRIORITY = {
    "PLACEMENT": P_COURSE_START,
    "QUIZ_POOL": P_NEXT_CHAPTER,
    "STUDY_PACK": P_NEXT_CHAPTER,
    "AUDIO_EPISODE": P_EXTRA,
}


def priority(kind: str) -> int:
    return PRIORITY.get(kind, P_NEXT_CHAPTER)


async def next_chapter(s: AsyncSession, chapter: Chapter) -> Chapter | None:
    """The chapter after this one in its course, if it has indexed material."""
    nxt = await s.scalar(
        select(Chapter)
        .where(Chapter.course_id == chapter.course_id, Chapter.idx > chapter.idx)
        .order_by(Chapter.idx)
        .limit(1)
    )
    if nxt is None:
        return None
    ready = await s.scalar(
        select(Document.id).where(Document.chapter_id == nxt.id, Document.status == "ready")
    )
    return nxt if ready else None


async def _quiz_ready(s: AsyncSession, chapter_id: uuid.UUID, level: str, language: str) -> bool:
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
    return found is not None or bool(await pool.pending_generation(s, chapter_id, level, language))


async def plan_next(s: AsyncSession, user: User, chapter: Chapter, level: str) -> list[uuid.UUID]:
    """Queue what chapter N+1 is missing for this student's level and language. Returns the jobs
    queued now (none when switched off, offline, at the last chapter or when it all exists)."""
    from app.features.quiz import pool  # noqa: PLC0415
    from app.features.studio import pack  # noqa: PLC0415

    settings = get_settings()
    if not settings.PREFETCH_ENABLED:
        return []
    offline, _ = await paused_until(settings, reuse(s))  # no 2nd connection (OPT-34)
    if offline:  # nothing new is made while AI is paused; the student's own start still works
        return []
    nxt = await next_chapter(s, chapter)
    if nxt is None:
        return []
    course = await s.get(Course, nxt.course_id)
    language = user.ui_language
    base = {"chapter_id": str(nxt.id), "level": level, "language": language, "prefetch": True}
    wanted: list[tuple[str, str, dict[str, Any]]] = []
    if not await _quiz_ready(s, nxt.id, level, language):
        seed = await pool.next_seed(s, nxt.id, level, language)
        wanted.append((pool.KIND, pool.share(nxt.id, level, language), {**base, "seed": seed}))
    if "notes" in await pack.missing(s, nxt.id, level, language) and not (
        await pack.pending_generation(s, nxt.id, level, language)
    ):
        key = share_key(pack.KIND, nxt.id, level, language)
        wanted.append((pack.KIND, key, {**base, "paid_by": None}))
    queued = []
    for kind, key, payload in wanted:
        job_id, created = await create_or_join_shared_job(
            s,
            kind=kind,
            share_key=key,
            lane="background",
            payload=payload,
            world_id=course.world_id,
            priority=priority(kind),
        )
        if created:
            queued.append(job_id)
    if queued:
        log.info("prefetch: chapter %s %s/%s, %d job(s)", nxt.id, level, language, len(queued))
    return queued


async def safely(s: AsyncSession, user: User, chapter: Chapter, level: str) -> None:
    """plan_next from a student's request: best effort, never fails the request."""
    try:
        await plan_next(s, user, chapter, level)
    except Exception:  # noqa: BLE001  (prefetch is an optimisation)
        await s.rollback()
        log.exception("prefetch planning failed for chapter %s", chapter.id)


async def preparing(s: AsyncSession, job_id: uuid.UUID | None) -> dict[str, Any] | None:
    """{job_id, eta_s} while a background job (a prefetch) makes this content, for the
    "Being prepared · about N min" note and its "Get it now" button."""
    if job_id is None:
        return None
    job = await s.get(Job, job_id)
    if job is None or job.lane != "background" or job.status not in ("queued", "running"):
        return None
    return {"job_id": job.id, "eta_s": max(1, round(await eta_s(s, job)))}
