"""Class Wisdom: count distinct students per (world, concept, mistake_type); at WISDOM_THRESHOLD
ONE WISDOM_TIP job (mid, generate-once, background) writes an anonymous tip in every language of
the world's members in a single call. Later students only raise `student_count` — no new call."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import (
    Chapter,
    Course,
    Job,
    Mistake,
    QuizAttempt,
    QuizSet,
    User,
    WisdomTip,
    WorldMember,
)

KIND = "WISDOM_TIP"
LANGUAGES = tuple(prompts.LANGUAGE_NAMES)  # en, fr, ar, ar-TN
TOKENS_PER_LANGUAGE = 160
MAX_SAMPLES = 3  # missed questions shown to the model


class TipText(BaseModel):
    trap: str = Field(min_length=1, max_length=400)
    why: str = Field(min_length=1, max_length=400)
    right: str = Field(min_length=1, max_length=400)


async def distinct_students(s: AsyncSession, world_id: uuid.UUID, concept: str, kind: str) -> int:
    n = await s.scalar(
        select(func.count(distinct(Mistake.user_id))).where(
            Mistake.world_id == world_id,
            Mistake.concept == concept,
            Mistake.mistake_type == kind,
        )
    )
    return int(n or 0)


async def check_patterns(
    s: AsyncSession, world_id: uuid.UUID, pairs: set[tuple[str, str]]
) -> list[uuid.UUID]:
    """After a tagging job: refresh counts, and enqueue one tip job per pattern that just reached
    the threshold. Returns the new job ids. Commits."""
    jobs: list[uuid.UUID] = []
    for concept, kind in sorted(pairs):
        n = await distinct_students(s, world_id, concept, kind)
        if n < economy.WISDOM_THRESHOLD:
            continue
        same = (
            WisdomTip.world_id == world_id,
            WisdomTip.concept == concept,
            WisdomTip.mistake_type == kind,
        )
        if await s.scalar(select(WisdomTip.id).where(*same).limit(1)):
            await s.execute(update(WisdomTip).where(*same).values(student_count=n))
            continue
        pending = await s.scalar(
            select(Job.id).where(
                Job.kind == KIND,
                Job.world_id == world_id,
                Job.status.in_(("queued", "running")),
                Job.payload["concept"].astext == concept,
                Job.payload["mistake_type"].astext == kind,
            )
        )
        if pending:
            continue
        # A tip that failed at n students is retried only once more students hit the trap, so
        # unusable replies can't be re-asked on every attempt (each retry is a new request).
        failed_at = await s.scalar(
            select(func.max(Job.payload["students"].as_integer())).where(
                Job.kind == KIND,
                Job.world_id == world_id,
                Job.status == "failed",
                Job.payload["concept"].astext == concept,
                Job.payload["mistake_type"].astext == kind,
            )
        )
        if failed_at is not None and n <= failed_at:
            continue
        j = await create_job(
            s,
            kind=KIND,
            lane="background",
            payload={
                "world_id": str(world_id),
                "concept": concept,
                "mistake_type": kind,
                "students": n,
            },
            world_id=world_id,
        )
        jobs.append(j.id)
    await s.commit()
    return jobs


async def world_languages(s: AsyncSession, world_id: uuid.UUID) -> list[str]:
    """The UI languages of the world's members, in a stable order (max 4)."""
    used = set(
        await s.scalars(
            select(User.ui_language)
            .join(WorldMember, WorldMember.user_id == User.id)
            .where(WorldMember.world_id == world_id)
        )
    )
    return [lang for lang in LANGUAGES if lang in used] or ["en"]


async def _samples(
    s: AsyncSession, world_id: uuid.UUID, concept: str, kind: str
) -> tuple[list[str], uuid.UUID | None]:
    """Up to MAX_SAMPLES distinct missed questions (question, wrong pick, right answer,
    explanation) and the chapter they come from most. No user data."""
    rows = (
        await s.execute(
            select(Mistake.chapter_id, Mistake.question_idx, QuizAttempt.answers, QuizSet.questions)
            .join(QuizAttempt, QuizAttempt.id == Mistake.attempt_id)
            .join(QuizSet, QuizSet.id == QuizAttempt.quiz_set_id)
            .where(
                Mistake.world_id == world_id,
                Mistake.concept == concept,
                Mistake.mistake_type == kind,
            )
            .order_by(Mistake.created_at.desc())
            .limit(30)
        )
    ).all()
    chapters = Counter(r.chapter_id for r in rows)
    items, seen = [], set()
    for r in rows:
        if r.question_idx is None or r.question_idx >= len(r.questions):
            continue
        q = r.questions[r.question_idx]
        if q["question"] in seen:
            continue
        seen.add(q["question"])
        a = r.answers[r.question_idx]
        chosen = a.get("second") if a.get("second") is not None else a.get("first")
        wrong = q["options"][chosen] if chosen is not None else "(skipped)"
        line = (
            f"- Q: {q['question']}\n  wrong answer given: {wrong}\n"
            f"  correct: {q['options'][q['answer_index']]}"
        )
        if q.get("explanation"):
            line += f"\n  explanation: {q['explanation']}"
        items.append(line)
        if len(items) == MAX_SAMPLES:
            break
    chapter_id = chapters.most_common(1)[0][0] if chapters else None
    return items, chapter_id


def cache_key(
    world_id: uuid.UUID, concept: str, kind: str, langs: list[str], count: int, version: str
) -> str:
    """One tip per pattern and set of languages. The student count is part of the key so that a
    reply with no usable tip (failed job) is retried only when one more student hits the trap,
    never re-read from the cache."""
    return f"wisdom:{world_id}:{concept}:{kind}:{','.join(langs)}:n{count}:v{version}"


def parse_tips(content: Any, langs: list[str]) -> dict[str, TipText]:
    tips = content.get("tips") if isinstance(content, dict) else None
    out: dict[str, TipText] = {}
    for lang in langs:
        raw = tips.get(lang) if isinstance(tips, dict) else None
        try:
            out[lang] = TipText.model_validate(raw)
        except ValidationError:
            continue
    return out


@job(KIND, stages=("spotting_the_pattern", "writing_the_tip"))
async def write_tip(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    world_id, concept, kind = uuid.UUID(p["world_id"]), p["concept"], p["mistake_type"]
    await ctx.set_stage("spotting_the_pattern")
    async with db.get_sessionmaker()() as s:
        items, chapter_id = await _samples(s, world_id, concept, kind)
        if chapter_id is None:
            return {"tips": 0}
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        langs = await world_languages(s, world_id)
        count = await distinct_students(s, world_id, concept, kind)
    await ctx.set_stage("writing_the_tip")
    example = ", ".join(
        f'"{lang}": {{"trap": "...", "why": "...", "right": "..."}}' for lang in langs
    )
    version, messages = prompts.render(
        "wisdom_tip",
        language=langs[0],
        language_list=", ".join(f"{lang} ({prompts.LANGUAGE_NAMES[lang]})" for lang in langs),
        example=example,
        course=course.name,
        chapter=chapter.title,
        concept=concept,
        mistake_type=kind,
        items="\n".join(items) or "(no question text kept)",
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.WISDOM_TIP,
                lane="background",
                messages=messages,
                language=langs[0],
                cache_key=cache_key(world_id, concept, kind, langs, count, version),
                max_tokens=TOKENS_PER_LANGUAGE * len(langs) + 40,
                prompt_version=version,
            )
        )
    )
    tips = parse_tips(result.content, langs)
    if not tips:  # nothing usable: fail the job; the next student with this mistake retries
        raise gateway.GatewayError("WISDOM_TIP reply had no valid tip")
    async with db.get_sessionmaker()() as s:
        for lang, tip in tips.items():
            stmt = insert(WisdomTip).values(
                id=uuid.uuid4(),
                world_id=world_id,
                course_id=course.id,
                chapter_id=chapter.id,
                concept=concept,
                mistake_type=kind,
                language=lang,
                text=tip.model_dump(),
                student_count=count,
            )
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["world_id", "concept", "mistake_type", "language"],
                    set_={"text": tip.model_dump(), "student_count": count},
                )
            )
        await s.commit()
    return {"tips": len(tips), "languages": sorted(tips)}


async def tips_for(
    s: AsyncSession,
    world_id: uuid.UUID,
    language: str,
    course_id: uuid.UUID | None = None,
    limit: int = 10,
) -> list[WisdomTip]:
    """Tips in the student's language; a pattern without one falls back to its English tip."""
    q = select(WisdomTip).where(WisdomTip.world_id == world_id)
    if course_id:
        q = q.where(WisdomTip.course_id == course_id)
    rows = list(await s.scalars(q.order_by(WisdomTip.student_count.desc(), WisdomTip.created_at)))
    best: dict[tuple[str, str], WisdomTip] = {}
    for t in rows:
        key = (t.concept, t.mistake_type)
        if t.language == language or (t.language == "en" and key not in best):
            best[key] = t
    return list(best.values())[:limit]
