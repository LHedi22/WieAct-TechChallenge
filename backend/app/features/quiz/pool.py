"""Shared quiz sets: QUIZ_GENERATE, compact, narrow-before-generating, ONE call for 10 questions.

Narrowing without an extra call: vector search in the chapter (cached query embedding of the
chapter title + level), then up to 6 chunks picked round-robin across their tagged concepts,
rotated by the set's seed so each new set looks at different material. Sets are shared by the
class: generated once per (chapter, level, language, seed), then free (economy: cached content).

Precompute after upload (M2): when a chapter's last file is ready, seed 1 at intermediate level in
the creator's language is generated on the background lane."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app import gateway, prompts
from app.core import db
from app.gateway import BadOutput, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import Chapter, Chunk, Course, Document, Job, QuizSet, User, World
from app.rag.search import search

KIND = "QUIZ_POOL"
POOL_LEVEL = "intermediate"
POOL_SIZE = 10
CONTEXT_CHUNKS = 6
SEARCH_K = 12
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


def pick_context(chunks: list[Chunk], k: int = CONTEXT_CHUNKS, offset: int = 0) -> list[Chunk]:
    """Round-robin over each chunk's first concept so the set covers the chapter; `offset`
    rotates the starting concept (a new seed looks at different material first)."""
    groups: dict[str, list[Chunk]] = {}
    for c in sorted(chunks, key=lambda c: (c.document_id, c.idx)):
        groups.setdefault(c.tags[0] if c.tags else "-", []).append(c)
    keys = list(groups)
    if keys:
        r = offset % len(keys)
        keys = keys[r:] + keys[:r]
    picked: list[Chunk] = []
    while len(picked) < k and any(groups.values()):
        for key in keys:
            if groups[key] and len(picked) < k:
                picked.append(groups[key].pop(0))
    return sorted(picked, key=lambda c: (c.document_id, c.idx))


async def next_seed(s, chapter_id: uuid.UUID, level: str, language: str) -> int:
    top = await s.scalar(
        select(func.max(QuizSet.seed)).where(
            QuizSet.chapter_id == chapter_id, QuizSet.level == level, QuizSet.language == language
        )
    )
    return (top or 0) + 1


async def pending_generation(s, chapter_id: uuid.UUID, level: str, language: str):
    """A generation already queued or running for this chapter + level + language (shared)."""
    return await s.scalar(
        select(Job.id).where(
            Job.kind == KIND,
            Job.status.in_(("queued", "running")),
            Job.payload["chapter_id"].astext == str(chapter_id),
            Job.payload["level"].astext == level,
            Job.payload["language"].astext == language,
        )
    )


async def maybe_precompute(chapter_id: uuid.UUID) -> uuid.UUID | None:
    """When every document of the chapter is ready, queue the first set once (background lane)."""
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
        if exists or await pending_generation(s, chapter_id, POOL_LEVEL, language):
            return None
        created = await create_job(
            s,
            kind=KIND,
            lane="background",
            payload={
                "chapter_id": str(chapter_id),
                "level": POOL_LEVEL,
                "language": language,
                "seed": 1,
            },
            world_id=world.id,
        )
        return created.id


async def chapter_context(
    ctx: JobContext, chapter: Chapter, course: Course, level: str, seed: int = 1
) -> list[Chunk]:
    """narrow-before-generating without an extra call: vector search, then round-robin by concept
    (also used by the Study Studio's notes)."""
    try:
        hits = await search(
            course.world_id,
            f"{chapter.title} ({level})",
            chapter_id=chapter.id,
            k=SEARCH_K,
            lane=ctx.lane,
        )
    except gateway.Defer:
        raise
    except gateway.GatewayError:
        hits = []
    async with db.get_sessionmaker()() as s:
        if hits:
            rows = list(
                await s.scalars(select(Chunk).where(Chunk.id.in_([h.chunk_id for h in hits])))
            )
        else:  # nothing in the vector store (yet) for this provider: use the chapter's chunks
            rows = list(await s.scalars(select(Chunk).where(Chunk.chapter_id == chapter.id)))
    return pick_context(rows, CONTEXT_CHUNKS, offset=seed - 1)


@job(KIND, stages=("reading_chapter", "matching_level", "writing_questions", "writing_hints"))
async def quiz_pool(ctx: JobContext) -> dict[str, Any]:
    chapter_id = uuid.UUID(ctx.payload["chapter_id"])
    level, language = ctx.payload["level"], ctx.payload["language"]
    seed = int(ctx.payload.get("seed", 1))
    await ctx.set_stage("reading_chapter")
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        existing = await s.scalar(
            select(QuizSet.id).where(
                QuizSet.chapter_id == chapter_id,
                QuizSet.level == level,
                QuizSet.language == language,
                QuizSet.seed == seed,
            )
        )
    if existing:
        return {"quiz_set_id": str(existing), "cached": True}
    await ctx.set_stage("matching_level")
    rows = await chapter_context(ctx, chapter, course, level, seed)
    context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in rows)
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
                lane=ctx.lane,
                messages=messages,
                language=language,
                cache_key=f"quiz:{chapter_id}:{level}:{language}:{seed}",
                prompt_version=version,
            )
        )
    )
    await ctx.set_stage("writing_hints")
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
                seed=seed,
                questions=questions,
            )
            .on_conflict_do_nothing(index_elements=["chapter_id", "level", "language", "seed"])
        )
        await s.commit()
        set_id = await s.scalar(
            select(QuizSet.id).where(
                QuizSet.chapter_id == chapter_id,
                QuizSet.level == level,
                QuizSet.language == language,
                QuizSet.seed == seed,
            )
        )
    # Public job result (GET /api/jobs/{id}): ids only, never questions or answers.
    return {"quiz_set_id": str(set_id), "questions": len(questions), "cached": result.cached}
