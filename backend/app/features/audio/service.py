"""Audio Studio: a short spoken revision episode per chapter + level + language, written once by
ONE mid AUDIO_SCRIPT call (narrow-before-generating, the quiz pool's narrowing) and then free for
the class. The browser reads it aloud (Web Speech API); nothing is synthesised on our side, so no
voice data exists. Darija is transcript-only (DECISIONS: silma-tts still OPEN)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.features.pool import service as pool
from app.features.quiz.pool import chapter_context
from app.features.quiz.service import LEVELS
from app.features.studio import pack
from app.features.studio.service import Pay, Rejected
from app.gateway import BadOutput, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import Chapter, Course, User

KIND = "AUDIO_EPISODE"
ASSET = "audio_script"
MIN_SEGMENTS = 3
MAX_SEGMENTS = 16


def valid_script(content: Any) -> dict[str, Any] | None:
    raw = content.get("segments") if isinstance(content, dict) else None
    segments = [s.strip() for s in raw if isinstance(s, str) and s.strip()] if raw else []
    if len(segments) < MIN_SEGMENTS:
        return None
    title = content.get("title") if isinstance(content.get("title"), str) else ""
    return {"title": title.strip()[:120], "segments": segments[:MAX_SEGMENTS]}


async def _pending(s: AsyncSession, chapter_id: uuid.UUID, level: str, language: str):
    return await pack.pending_generation(s, chapter_id, level, language, kind=KIND)


async def price(s: AsyncSession, chapter_id: uuid.UUID, level: str, language: str) -> dict:
    found = await pack.assets(s, chapter_id, level, language)
    if ASSET in found:
        return {"cost": economy.COST["cached_content"], "cached": True}
    if await _pending(s, chapter_id, level, language):
        return {"cost": economy.COST["cached_content"], "cached": False}
    return {"cost": economy.COST["generate_shared_asset"], "cached": False}


async def status(s: AsyncSession, user: User, chapter: Chapter, level: str) -> dict[str, Any]:
    if level not in LEVELS:
        raise Rejected("errors.level_invalid")
    language = user.ui_language
    course = await s.get(Course, chapter.course_id)
    found = await pack.assets(s, chapter.id, level, language)
    return {
        "chapter_id": chapter.id,
        "level": level,
        "language": language,
        "script": found[ASSET].content if ASSET in found else None,
        "pending_job_id": await _pending(s, chapter.id, level, language),
        "pool_balance": await pool.balance(s, course.world_id),
        **await price(s, chapter.id, level, language),
    }


async def generate(
    s: AsyncSession, user: User, chapter: Chapter, level: str, pay: Pay
) -> dict[str, Any]:
    """Queue the episode (free when it exists or a classmate is already generating it)."""
    if level not in LEVELS:
        raise Rejected("errors.level_invalid")
    language = user.ui_language
    if ASSET in await pack.assets(s, chapter.id, level, language):
        return {"job_id": None, "cost": 0, "cached": True}
    job_id = await _pending(s, chapter.id, level, language)
    if job_id:
        return {"job_id": job_id, "cost": 0, "cached": False}
    course = await s.get(Course, chapter.course_id)
    cost = economy.COST["generate_shared_asset"]
    created = await create_job(  # reserves from the wallet or the pool (LedgerCoins.reserve)
        s,
        kind=KIND,
        lane="interactive",
        payload={
            "chapter_id": str(chapter.id),
            "level": level,
            "language": language,
            "paid_by": pay,
        },
        user_id=user.id,
        world_id=course.world_id,
        cost=cost,
    )
    return {"job_id": created.id, "cost": cost, "cached": False}


@job(KIND, stages=("reading_chapter", "writing_script"))
async def audio_episode(ctx: JobContext) -> dict[str, Any]:
    chapter_id = uuid.UUID(ctx.payload["chapter_id"])
    level, language = ctx.payload["level"], ctx.payload["language"]
    await ctx.set_stage("reading_chapter")
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        if ASSET in await pack.assets(s, chapter_id, level, language):
            return {"chapter_id": str(chapter_id), "cached": True}
    rows = await chapter_context(ctx, chapter, course, level)
    await ctx.set_stage("writing_script")
    version, messages = prompts.render(
        "audio_script",
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        context="\n\n".join(f"[{c.page_ref}] {c.text}" for c in rows),
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.AUDIO_SCRIPT,
                lane=ctx.lane,
                messages=messages,
                language=language,
                # Same rule as the study pack: study_assets is the class cache; the job id keeps
                # an unusable reply from being re-read by the next attempt.
                cache_key=f"audio:{chapter_id}:{level}:{language}:job{ctx.job_id}",
                prompt_version=version,
            )
        )
    )
    script = valid_script(result.content)
    if script is None:
        raise BadOutput("no usable audio script", refusal="bad_audio")
    await pack.save_asset(course.world_id, chapter_id, level, language, ASSET, script)
    return {"chapter_id": str(chapter_id), "segments": len(script["segments"])}
