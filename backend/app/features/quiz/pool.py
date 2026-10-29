"""Precompute after upload: one shared quiz pool per chapter (intermediate, creator's language).

QUIZ_GENERATE, compact, narrow-before-generating: instead of the whole chapter, up to 8 chunks
chosen round-robin across the chapter's tagged concepts go into ONE call for 10 questions.
Stored in quiz_sets and reused by the whole class (M4 builds the Quiz Hall on it)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import gateway, prompts
from app.core import db
from app.gateway import BadOutput, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import Chapter, Chunk, Course, Document, Job, QuizSet, User, World

KIND = "QUIZ_POOL"
POOL_LEVEL = "intermediate"
POOL_SIZE = 10
CONTEXT_CHUNKS = 8
MIN_VALID = 5


class Question(BaseModel):
    question: str = Field(min_length=3)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    hint: str = ""
    explanation: str = ""
    concept: str = ""

    @field_validator("options")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len({o.strip().lower() for o in v}) != 4:
            raise ValueError("options must be distinct")
        return v


def valid_questions(content: Any) -> list[dict[str, Any]]:
    raw = content.get("questions", []) if isinstance(content, dict) else []
    out = []
    for q in raw if isinstance(raw, list) else []:
        try:
            out.append(Question.model_validate(q).model_dump())
        except ValidationError:
            continue
    return out


def pick_context(chunks: list[Chunk], k: int = CONTEXT_CHUNKS) -> list[Chunk]:
    """Round-robin over each chunk's first concept so the pool covers the whole chapter."""
    groups: dict[str, list[Chunk]] = {}
    for c in sorted(chunks, key=lambda c: (c.document_id, c.idx)):
        groups.setdefault(c.tags[0] if c.tags else "-", []).append(c)
    picked: list[Chunk] = []
    while len(picked) < k and any(groups.values()):
        for key in list(groups):
            if groups[key] and len(picked) < k:
                picked.append(groups[key].pop(0))
    return sorted(picked, key=lambda c: (c.document_id, c.idx))


async def maybe_precompute(chapter_id: uuid.UUID) -> uuid.UUID | None:
    """When every document of the chapter is ready, queue the pool once (background lane)."""
    async with db.get_sessionmaker()() as s:
        statuses = list(
            await s.scalars(select(Document.status).where(Document.chapter_id == chapter_id))
        )
        if not statuses or any(st not in ("ready", "failed") for st in statuses):
            return None
        if "ready" not in statuses:
            return None
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        world = await s.get(World, course.world_id)
        creator = await s.get(User, world.creator_id)
        language = creator.ui_language if creator else "en"
        exists = await s.scalar(
            select(QuizSet.id).where(
                QuizSet.chapter_id == chapter_id,
                QuizSet.level == POOL_LEVEL,
                QuizSet.language == language,
            )
        )
        pending = await s.scalar(
            select(Job.id).where(
                Job.kind == KIND,
                Job.status.in_(("queued", "running")),
                Job.payload["chapter_id"].astext == str(chapter_id),
            )
        )
        if exists or pending:
            return None
        created = await create_job(
            s,
            kind=KIND,
            lane="background",
            payload={"chapter_id": str(chapter_id), "level": POOL_LEVEL, "language": language},
            world_id=world.id,
        )
        return created.id


@job(KIND, stages=("matching_level", "writing_questions"))
async def quiz_pool(ctx: JobContext) -> dict[str, Any]:
    chapter_id = uuid.UUID(ctx.payload["chapter_id"])
    level, language = ctx.payload["level"], ctx.payload["language"]
    await ctx.set_stage("matching_level")
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        chunks = list(await s.scalars(select(Chunk).where(Chunk.chapter_id == chapter_id)))
    context_rows = pick_context(chunks)
    context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in context_rows)
    await ctx.set_stage("writing_questions")
    version, messages = prompts.render(
        "quiz_generate",
        count=POOL_SIZE,
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        context=context,
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.QUIZ_GENERATE,
                lane="background",
                messages=messages,
                language=language,
                cache_key=f"pool:{chapter_id}:{level}:{language}",
                prompt_version=version,
            )
        )
    )
    questions = valid_questions(result.content)
    if len(questions) < MIN_VALID:
        raise BadOutput(f"only {len(questions)} valid questions", refusal="bad_quiz")
    async with db.get_sessionmaker()() as s:
        await s.execute(
            insert(QuizSet)
            .values(
                id=uuid.uuid4(),
                world_id=course.world_id,
                chapter_id=chapter_id,
                level=level,
                language=language,
                questions=questions,
            )
            .on_conflict_do_nothing(index_elements=["chapter_id", "level", "language"])
        )
        await s.commit()
    return {"chapter_id": str(chapter_id), "questions": len(questions), "cached": result.cached}
