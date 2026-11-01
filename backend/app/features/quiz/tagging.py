"""QUIZ_GRADE_TAG (compact, extraction, background): ONE call tags every missed question of an
attempt with (concept, mistake_type) → `mistakes` (weak spots, daily challenges, Class Wisdom)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select

from app import gateway, prompts
from app.core import db
from app.features.wisdom import service as wisdom
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job
from app.models import Chapter, Course, Mistake, QuizAttempt, QuizSet

KIND = "QUIZ_TAG"
MISTAKE_TYPES = ("misconception", "calculation", "misread", "definition", "procedure")
TOKENS_PER_ITEM = 40


class Tag(BaseModel):
    i: int
    concept: str
    mistake_type: Literal["misconception", "calculation", "misread", "definition", "procedure"]


def items_text(
    questions: list[dict[str, Any]], answers: list[dict[str, Any]]
) -> tuple[str, list[int]]:
    lines, idx = [], []
    for i, (q, a) in enumerate(zip(questions, answers, strict=True)):
        if a["status"] == "correct":
            continue
        chosen = a.get("second") if a.get("second") is not None else a.get("first")
        picked = q["options"][chosen] if chosen is not None else "(skipped)"
        lines.append(
            f"[{i}] Q: {q['question']}\n    student: {picked}\n"
            f"    correct: {q['options'][q['answer_index']]}"
        )
        idx.append(i)
    return "\n".join(lines), idx


@job(KIND, stages=("finding_key_ideas",))
async def tag_mistakes(ctx: JobContext) -> dict[str, Any]:
    attempt_id = uuid.UUID(ctx.payload["attempt_id"])
    async with db.get_sessionmaker()() as s:
        attempt = await s.get(QuizAttempt, attempt_id)
        qs = await s.get(QuizSet, attempt.quiz_set_id)
        chapter = await s.get(Chapter, attempt.chapter_id)
        course = await s.get(Course, attempt.course_id)
    items, idx = items_text(qs.questions, attempt.answers)
    if not idx:
        return {"tagged": 0}
    await ctx.set_stage("finding_key_ideas")
    version, messages = prompts.render(
        "quiz_grade_tag",
        language=attempt.language,
        course=course.name,
        chapter=chapter.title,
        items=items,
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.QUIZ_GRADE_TAG,
                lane="background",
                messages=messages,
                language=attempt.language,
                cache_key=f"tags:{attempt.language}:"
                + hashlib.sha256(items.encode("utf-8")).hexdigest()[:32],
                max_tokens=TOKENS_PER_ITEM * len(idx) + 40,
                prompt_version=version,
            )
        )
    )
    raw = result.content.get("mistakes", []) if isinstance(result.content, dict) else []
    tags: dict[int, Tag] = {}
    for item in raw if isinstance(raw, list) else []:
        try:
            tag = Tag.model_validate(item)
        except ValidationError:
            continue
        if tag.i in idx:
            tags[tag.i] = tag
    async with db.get_sessionmaker()() as s:
        await s.execute(delete(Mistake).where(Mistake.attempt_id == attempt_id))  # idempotent
        for i in idx:
            tag = tags.get(i)
            # The shared question's own concept first: it is the same text for the whole class,
            # so Class Wisdom can count students per concept (the tagger's wording varies).
            concept = (
                qs.questions[i].get("concept") or (tag.concept if tag else "") or chapter.title
            )[:80]
            s.add(
                Mistake(
                    user_id=attempt.user_id,
                    world_id=attempt.world_id,
                    chapter_id=attempt.chapter_id,
                    attempt_id=attempt_id,
                    question_idx=i,
                    concept=concept.strip().lower(),
                    mistake_type=tag.mistake_type if tag else "misconception",
                )
            )
        await s.commit()
        rows = await s.execute(
            select(Mistake.concept, Mistake.mistake_type).where(Mistake.attempt_id == attempt_id)
        )
        pairs = {(concept, kind) for concept, kind in rows}
        count = await s.scalar(select(func.count()).where(Mistake.attempt_id == attempt_id))
        await wisdom.check_patterns(s, attempt.world_id, pairs)
    return {"tagged": count}
