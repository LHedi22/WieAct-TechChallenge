"""Placement quiz: 8 questions per course + language, generated ONCE for the class (compact,
narrow-before-generating: 2 chunks per chapter, one call), graded here — answers never leave the
server. Free (economy COST["placement_quiz"] = 0). Sets the course level and seeds chapter mastery.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import gateway, prompts
from app.core import db
from app.features.quiz.pool import Question, pick_context
from app.gateway import BadOutput, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.models import Chapter, ChapterMastery, Chunk, Course, CourseLevel, PlacementSet

KIND = "PLACEMENT"
COUNT = 8
MIN_VALID = 6
CHUNKS_PER_CHAPTER = 2
MAX_CHUNKS = 10
WEIGHT = {"beginner": 1, "intermediate": 2, "advanced": 3}
WEAK_BELOW = 50


class PlacementQuestion(Question):
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    chapter: int = Field(1, ge=1)


class NoMaterial(Exception):
    """Nothing indexed in this course yet."""


def level_for(percent: float) -> str:
    if percent < 40:
        return "beginner"
    return "intermediate" if percent <= 75 else "advanced"


def redact(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the student sees: no answer, no difficulty, no concept (they would give it away)."""
    return [
        {"i": i, "question": q["question"], "options": q["options"]}
        for i, q in enumerate(questions)
    ]


async def find_set(course_id: uuid.UUID, language: str) -> PlacementSet | None:
    async with db.get_sessionmaker()() as s:
        return await s.scalar(
            select(PlacementSet).where(
                PlacementSet.course_id == course_id, PlacementSet.language == language
            )
        )


async def context_for(course_id: uuid.UUID) -> tuple[list[Chapter], str]:
    async with db.get_sessionmaker()() as s:
        chapters = list(
            await s.scalars(
                select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.idx)
            )
        )
        chunks = list(
            await s.scalars(select(Chunk).where(Chunk.chapter_id.in_([c.id for c in chapters])))
        )
    by_chapter: dict[uuid.UUID, list[Chunk]] = {}
    for c in chunks:
        by_chapter.setdefault(c.chapter_id, []).append(c)
    parts: list[str] = []
    for ch in chapters:
        for c in pick_context(by_chapter.get(ch.id, []), CHUNKS_PER_CHAPTER):
            if len(parts) < MAX_CHUNKS:
                parts.append(f"[chapter {ch.idx} · {ch.title} · {c.page_ref}] {c.text}")
    if not parts:
        raise NoMaterial
    return chapters, "\n\n".join(parts)


def clean(content: Any, chapters: list[Chapter]) -> list[dict[str, Any]]:
    by_idx = {c.idx: c for c in chapters}
    raw = content.get("questions", []) if isinstance(content, dict) else []
    out: list[dict[str, Any]] = []
    for q in raw if isinstance(raw, list) else []:
        try:
            pq = PlacementQuestion.model_validate(q)
        except ValidationError:
            continue
        chapter = by_idx.get(pq.chapter) or chapters[len(out) % len(chapters)]
        out.append(pq.model_dump() | {"chapter": chapter.idx, "chapter_id": str(chapter.id)})
    return out[:COUNT]


@job(KIND, stages=("reading_chapter", "matching_level", "writing_questions"))
async def generate(ctx: JobContext) -> dict[str, Any]:
    course_id = uuid.UUID(ctx.payload["course_id"])
    language = ctx.payload["language"]
    if await find_set(course_id, language):
        return {"course_id": str(course_id), "ready": True}
    await ctx.set_stage("reading_chapter")
    async with db.get_sessionmaker()() as s:
        course = await s.get(Course, course_id)
    try:
        chapters, context = await context_for(course_id)
    except NoMaterial as e:
        raise BadOutput("no material", refusal="no_material") from e
    await ctx.set_stage("matching_level")
    version, messages = prompts.render(
        "placement_quiz", count=COUNT, language=language, course=course.name, context=context
    )
    await ctx.set_stage("writing_questions")
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.PLACEMENT_QUIZ,
                lane="interactive",
                messages=messages,
                language=language,
                cache_key=f"placement:{course_id}:{language}",
                prompt_version=version,
            )
        )
    )
    questions = clean(result.content, chapters)
    if len(questions) < MIN_VALID:
        raise BadOutput(f"only {len(questions)} valid questions", refusal="bad_quiz")
    async with db.get_sessionmaker()() as s:
        await s.execute(
            insert(PlacementSet)
            .values(id=uuid.uuid4(), course_id=course_id, language=language, questions=questions)
            .on_conflict_do_nothing(index_elements=["course_id", "language"])
        )
        await s.commit()
    # The result is public (GET /api/jobs/{id}): never put the questions or answers in it.
    return {"course_id": str(course_id), "ready": True}


class ChapterResult(BaseModel):
    chapter_id: str
    title: str
    correct: int
    asked: int


class Graded(BaseModel):
    level: str
    correct: int
    total: int
    percent: int
    chapters: list[ChapterResult]


async def grade(
    user_id: uuid.UUID, course_id: uuid.UUID, placement: PlacementSet, answers: list[int | None]
) -> Graded:
    questions = placement.questions
    got = earned = possible = 0
    per: dict[str, dict[str, Any]] = {}
    for q, a in zip(questions, answers, strict=False):
        w = WEIGHT.get(q.get("difficulty", "intermediate"), 2)
        ok = a is not None and a == q["answer_index"]
        possible += w
        earned += w if ok else 0
        got += ok
        c = per.setdefault(
            q["chapter_id"], {"chapter_id": q["chapter_id"], "correct": 0, "asked": 0}
        )
        c["asked"] += 1
        c["correct"] += ok
    percent = round(100 * earned / possible) if possible else 0
    level = level_for(100 * earned / possible if possible else 0)
    async with db.get_sessionmaker()() as s:
        titles = dict(
            (
                await s.execute(
                    select(Chapter.id, Chapter.title).where(
                        Chapter.id.in_([uuid.UUID(k) for k in per])
                    )
                )
            ).all()
        )
        stmt = insert(CourseLevel).values(user_id=user_id, course_id=course_id, level=level)
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "course_id"], set_={"level": level}
            )
        )
        for c in per.values():
            mastery = round(100 * c["correct"] / c["asked"])
            c["title"] = titles.get(uuid.UUID(c["chapter_id"]), "")
            stmt = insert(ChapterMastery).values(
                user_id=user_id,
                chapter_id=uuid.UUID(c["chapter_id"]),
                mastery=mastery,
                weak=mastery < WEAK_BELOW,
            )
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["user_id", "chapter_id"],
                    set_={"mastery": mastery, "weak": mastery < WEAK_BELOW},
                )
            )
        await s.commit()
    return Graded(
        level=level,
        correct=got,
        total=len(questions),
        percent=percent,
        chapters=[ChapterResult(**c) for c in per.values()],
    )
