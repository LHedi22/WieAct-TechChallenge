"""Teach-Back Arena (PRODUCT.md): a peer room per chapter and a solo mode.

- ask    — ARENA_ASK job: ONE compact MODERATE_POST (classification, cached by text). Costs
           COST["peer_question"], refunded when the question is rejected.
- answer — ARENA_GRADE job: ONE compact TEACHBACK_GRADE that also moderates (its `flag`), grounded
           in the chapter (narrow-before-generating, k=4). draft-then-revise: the mid model reviews
           the draft only when it is unsure or the score is within TEACHBACK_REVIEW_BAND of the
           reward threshold (coins depend on it). Mid busy → the draft stands (Quick mode). Free.
- solo   — ARENA_SOLO job: the same grade for a self-chosen concept; mid only when unsure.
           Costs COST["teachback_solo"]; points = POINTS["teachback_solo_per_10_score"] per 10.
Rewards: an answer ≥ PEER_ANSWER_THRESHOLD earns EARN["peer_answer_good"] coins (daily cap) and
POINTS["peer_answer_good"], once per answer; the asker's pin gives POINTS["pinned_best_answer"].
Nicknames only; detailed feedback is shown to the answer's author only."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.features.daily import service as daily
from app.features.wallet import service as wallet
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import Chapter, Course, Job, PeerAnswer, PeerQuestion, PeerVote, User
from app.rag.search import search

ASK_KIND = "ARENA_ASK"
GRADE_KIND = "ARENA_GRADE"
SOLO_KIND = "ARENA_SOLO"
CONTEXT_K = 4
GRADE_STAGES = ("reading_chapter", "scoring_answer", "double_checking")


class Rejected(Exception):
    def __init__(self, key: str, status: int = 400) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


class Fix(BaseModel):
    quote: str = ""
    fix: str = ""


class Grade(BaseModel):
    flag: Literal["ok", "off_topic", "abusive"] = "ok"
    score: int = Field(ge=0, le=100)
    confidence: Literal["high", "medium", "low"] = "medium"
    errors: list[Fix] = Field(default_factory=list, max_length=3)
    good: str = ""
    missing: list[str] = Field(default_factory=list, max_length=2)


def needs_review(g: Grade, *, peer: bool) -> bool:
    """draft-then-revise: spend a mid call only when the compact draft is unsure, or (peer room)
    when the score is close enough to the threshold that the reward could flip."""
    if g.flag != "ok":
        return False
    if g.confidence == "low":
        return True
    return peer and abs(g.score - economy.PEER_ANSWER_THRESHOLD) <= economy.TEACHBACK_REVIEW_BAND


def parse_grade(content: Any) -> Grade | None:
    if not isinstance(content, dict) or content.get("score") is None:
        return None  # no score is unusable, never a silent 0
    data = dict(content)
    try:
        data["score"] = max(0, min(100, int(round(float(data["score"])))))
        data["errors"] = [e for e in data.get("errors") or [] if isinstance(e, dict)][:3]
        data["missing"] = [str(m) for m in data.get("missing") or []][:2]
        if data.get("confidence") not in ("high", "medium", "low"):
            data["confidence"] = "medium"
        if data.get("flag") not in ("ok", "off_topic", "abusive"):
            data["flag"] = "ok"
        return Grade.model_validate(data)
    except (TypeError, ValueError, ValidationError):
        return None


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:32]


# --- API side ------------------------------------------------------------------------------------
async def grading_job(s: AsyncSession, answer_id: uuid.UUID) -> uuid.UUID | None:
    """The queued or running grade job of an answer, if any (a job that gave up after its
    deferrals leaves the answer re-sendable)."""
    return await s.scalar(
        select(Job.id)
        .where(
            Job.kind == GRADE_KIND,
            Job.status.in_(("queued", "running")),
            Job.payload["answer_id"].astext == str(answer_id),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


async def _world_of(s: AsyncSession, chapter: Chapter) -> uuid.UUID:
    course = await s.get(Course, chapter.course_id)
    return course.world_id


async def ask(s: AsyncSession, user: User, chapter: Chapter, text: str) -> tuple[PeerQuestion, Job]:
    q = PeerQuestion(
        world_id=await _world_of(s, chapter),
        chapter_id=chapter.id,
        author_id=user.id,
        text=text.strip(),
        language=user.ui_language,
        status="pending",
    )
    s.add(q)
    await s.flush()
    j = await create_job(
        s,
        kind=ASK_KIND,
        lane="interactive",
        payload={"question_id": str(q.id)},
        user_id=user.id,
        world_id=q.world_id,
        cost=economy.COST["peer_question"],
    )
    return q, j


async def answer(s: AsyncSession, user: User, q: PeerQuestion, text: str) -> tuple[PeerAnswer, Job]:
    """Answer, or improve my answer: one row per student per question, graded again each time."""
    if q.status != "open":
        raise Rejected("errors.arena_question_closed", 409)
    if q.author_id == user.id:
        raise Rejected("errors.arena_own_question", 403)
    a = await s.scalar(
        select(PeerAnswer)
        .where(PeerAnswer.question_id == q.id, PeerAnswer.author_id == user.id)
        .with_for_update()
    )
    if a is not None and a.status == "grading" and await grading_job(s, a.id) is not None:
        raise Rejected("errors.arena_still_grading", 409)
    if a is None:
        a = PeerAnswer(question_id=q.id, author_id=user.id, text=text.strip())
        s.add(a)
    else:
        a.text, a.updated_at = text.strip(), datetime.now(UTC)
    a.status, a.ai_score, a.ai_confidence, a.ai_feedback = "grading", None, None, None
    a.reviewed_by_mid = False
    await s.flush()
    j = await create_job(
        s,
        kind=GRADE_KIND,
        lane="interactive",
        payload={"answer_id": str(a.id), "language": user.ui_language},
        user_id=user.id,
        world_id=q.world_id,
    )
    return a, j


async def pin(s: AsyncSession, user: User, a: PeerAnswer) -> None:
    q = await s.get(PeerQuestion, a.question_id, with_for_update=True)
    if q.author_id != user.id:
        raise Rejected("errors.arena_not_asker", 403)
    if q.pinned_answer_id is not None:
        raise Rejected("errors.arena_already_pinned", 409)
    if a.status != "graded":
        raise Rejected("errors.arena_still_grading", 409)
    q.pinned_answer_id = a.id
    await wallet.add_points(
        s, a.author_id, q.world_id, economy.POINTS["pinned_best_answer"], "pinned", str(q.id)
    )


async def vote(s: AsyncSession, user: User, a: PeerAnswer, helpful: bool) -> None:
    if a.author_id == user.id:
        raise Rejected("errors.arena_own_answer", 403)
    if helpful:
        await s.execute(
            insert(PeerVote).values(answer_id=a.id, user_id=user.id).on_conflict_do_nothing()
        )
    else:
        await s.execute(
            delete(PeerVote).where(PeerVote.answer_id == a.id, PeerVote.user_id == user.id)
        )


async def solo(s: AsyncSession, user: User, chapter: Chapter, concept: str, text: str) -> Job:
    return await create_job(
        s,
        kind=SOLO_KIND,
        lane="interactive",
        payload={
            "chapter_id": str(chapter.id),
            "concept": concept.strip(),
            "text": text.strip(),
            "language": user.ui_language,
        },
        user_id=user.id,
        world_id=await _world_of(s, chapter),
        cost=economy.COST["teachback_solo"],
    )


async def helpful_counts(s: AsyncSession, answer_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not answer_ids:
        return {}
    rows = await s.execute(
        select(PeerVote.answer_id, func.count())
        .where(PeerVote.answer_id.in_(answer_ids))
        .group_by(PeerVote.answer_id)
    )
    return dict(rows.all())


# --- jobs ----------------------------------------------------------------------------------------
async def _context(world_id: uuid.UUID, chapter_id: uuid.UUID, query: str) -> str:
    try:
        hits = await search(world_id, query, chapter_id=chapter_id, k=CONTEXT_K, lane="interactive")
    except gateway.Defer:
        raise
    except gateway.GatewayError:
        hits = []
    return "\n\n".join(f"[{h.page_ref}] {h.text[:900]}" for h in hits) or "(no excerpt found)"


async def grade(
    ctx: JobContext,
    *,
    mode: Literal["peer", "solo"],
    world_id: uuid.UUID,
    chapter: Chapter,
    course: Course,
    prompt: str,
    text: str,
    language: str,
) -> tuple[Grade, bool]:
    """(grade, reviewed_by_mid). One compact call; a mid review only when needs_review()."""
    await ctx.set_stage("reading_chapter")
    context = await _context(world_id, chapter.id, f"{prompt} {text}"[:500])
    values = {
        "language": language,
        "mode": "answering a classmate's question" if mode == "peer" else "teaching a concept",
        "course": course.name,
        "chapter": chapter.title,
        "context": context,
        "prompt_label": "QUESTION" if mode == "peer" else "CONCEPT",
        "prompt": prompt,
        "answer": text,
    }
    await ctx.set_stage("scoring_answer")
    version, messages = prompts.render("teachback_grade", **values)
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.TEACHBACK_GRADE,
                lane="interactive",
                messages=messages,
                language=language,
                prompt_version=version,
            )
        )
    )
    draft = parse_grade(result.content)
    if draft is None:
        raise gateway.BadOutput("unusable grade", refusal="bad_json")
    if not needs_review(draft, peer=mode == "peer"):
        return draft, False

    await ctx.set_stage("double_checking")
    version, messages = prompts.render(
        "teachback_review", draft=json.dumps(draft.model_dump(), ensure_ascii=False), **values
    )
    try:
        reviewed = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.TEACHBACK_GRADE,
                    lane="interactive",
                    messages=messages,
                    language=language,
                    tier="mid",
                    allow_fallback=False,  # if mid is busy, the compact draft stands
                    prompt_version=f"review-{version}",
                )
            )
        )
    except gateway.Defer:
        ctx.quick_mode = True
        return draft, False
    final = parse_grade(reviewed.content)
    return (final, True) if final is not None else (draft, False)


@job(ASK_KIND, stages=("checking_message",))
async def check_question(ctx: JobContext) -> dict[str, Any]:
    qid = uuid.UUID(ctx.payload["question_id"])
    async with db.get_sessionmaker()() as s:
        q = await s.get(PeerQuestion, qid)
        chapter = await s.get(Chapter, q.chapter_id)
        course = await s.get(Course, chapter.course_id)
    await ctx.set_stage("checking_message")
    version, messages = prompts.render(
        "moderate_post", language=q.language, course=course.name, chapter=chapter.title, text=q.text
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.MODERATE_POST,
                lane="interactive",
                messages=messages,
                language=q.language,
                cache_key=f"moderate:{text_hash(q.text)}",
                prompt_version=version,
            )
        )
    )
    verdict = str((result.content or {}).get("verdict") if isinstance(result.content, dict) else "")
    ok = verdict in ("ok", "")  # an unreadable verdict lets the question through
    async with db.get_sessionmaker()() as s:
        q = await s.get(PeerQuestion, qid)
        q.status = "open" if ok else "rejected"
        q.reject_reason = None if ok else verdict[:16]
        if not ok:  # the 2 coins come back
            await wallet.refund(s, await s.get(Job, ctx.job_id))
        await s.commit()
    return {"question_id": str(qid), "status": q.status, "reason": q.reject_reason}


@job(GRADE_KIND, stages=GRADE_STAGES)
async def grade_answer(ctx: JobContext) -> dict[str, Any]:
    aid = uuid.UUID(ctx.payload["answer_id"])
    async with db.get_sessionmaker()() as s:
        a = await s.get(PeerAnswer, aid)
        q = await s.get(PeerQuestion, a.question_id)
        chapter = await s.get(Chapter, q.chapter_id)
        course = await s.get(Course, chapter.course_id)
    try:
        g, reviewed = await grade(
            ctx,
            mode="peer",
            world_id=q.world_id,
            chapter=chapter,
            course=course,
            prompt=q.text,
            text=a.text,
            language=ctx.payload.get("language") or q.language,
        )
    except gateway.Defer:
        raise  # requeued: the answer stays "grading" until the job runs again
    except Exception:
        async with db.get_sessionmaker()() as s:  # let the student send it again
            row = await s.get(PeerAnswer, aid)
            row.status = "failed"
            await s.commit()
        raise
    earned = 0
    async with db.get_sessionmaker()() as s:
        a = await s.get(PeerAnswer, aid, with_for_update=True)
        if g.flag != "ok":
            a.status = "rejected"
            a.ai_feedback = {"flag": g.flag}
        else:
            a.status = "graded"
            await daily.record(s, a.author_id, "teachback", chapter_id=q.chapter_id)
            a.ai_score, a.ai_confidence = g.score, g.confidence
            a.ai_feedback = {
                "errors": [e.model_dump() for e in g.errors],
                "good": g.good,
                "missing": g.missing,
                "quick_mode": ctx.quick_mode,
            }
            a.reviewed_by_mid = reviewed
            if g.score >= economy.PEER_ANSWER_THRESHOLD and not a.rewarded:
                a.rewarded = True
                ref = f"answer:{a.id}"
                earned = await wallet.earn(s, a.author_id, economy.EARN["peer_answer_good"], ref)
                await wallet.add_points(
                    s, a.author_id, q.world_id, economy.POINTS["peer_answer_good"], "answer", ref
                )
        await s.commit()
        status = a.status
    return {"answer_id": str(aid), "status": status, "score": g.score, "coins_earned": earned}


@job(SOLO_KIND, stages=GRADE_STAGES)
async def grade_solo(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, uuid.UUID(p["chapter_id"]))
        course = await s.get(Course, chapter.course_id)
        user_id = (await s.get(Job, ctx.job_id)).user_id
    g, reviewed = await grade(
        ctx,
        mode="solo",
        world_id=course.world_id,
        chapter=chapter,
        course=course,
        prompt=p["concept"] or chapter.title,
        text=p["text"],
        language=p.get("language") or "en",
    )
    points = 0
    if g.flag == "ok":
        points = economy.POINTS["teachback_solo_per_10_score"] * (g.score // 10)
        async with db.get_sessionmaker()() as s:
            await wallet.add_points(s, user_id, course.world_id, points, "solo", str(ctx.job_id))
            await daily.record(s, user_id, "teachback", chapter_id=chapter.id)
            await s.commit()
    return {
        "flag": g.flag,
        "score": g.score if g.flag == "ok" else None,
        "confidence": g.confidence,
        "errors": [e.model_dump() for e in g.errors],
        "good": g.good,
        "missing": g.missing,
        "reviewed_by_mid": reviewed,
        "points": points,
    }
