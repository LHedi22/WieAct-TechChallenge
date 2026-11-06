"""Teach-Back Arena (PRODUCT.md): a peer room per chapter and a solo mode.

- ask    — ARENA_ASK job: ONE compact MODERATE_POST (classification, cached by text). Costs
           COST["peer_question"], refunded when the question is rejected.
- answer — ARENA_GRADE job: ONE compact TEACHBACK_GRADE that also moderates (its `flag`), grounded
           in the chapter (narrow-before-generating, k=4). Free.
- solo   — ARENA_SOLO job: the same grade for a self-chosen concept. Costs COST["teachback_solo"];
           points = POINTS["teachback_solo_per_10_score"] per 10.
Scoring (audit N-2): a rubric; the model rates each criterion's level, the server totals them.
Guarded finish (audit N-1, draft-then-revise): the answer is fenced as untrusted data, every level
needs evidence copied from the answer (checked here; unsupported levels count 0), and a compact
draft is final only when no review reason applies: injection detected (injection.py), evidence
missing, low confidence, a score >= TEACHBACK_REVIEW_HIGH_SCORE, or (peer) near the reward
threshold. Otherwise mid reviews it before anything is awarded. Mid busy, or the day's review
budget (TEACHBACK_REVIEW_DAILY_CAP / _USER_DAILY_CAP) spent → the attempt is "pending_review"
with no rewards and an ARENA_REVIEW background job settles it later; the compact score never
stands in for the review. Arabic and Darija (MID_GRADE_LANGUAGES) are graded by mid directly
(DECISIONS.md 2026-10-31), which is their review. A grade still low-confidence after mid stays
pending (author only).
Rewards: an answer >= PEER_ANSWER_THRESHOLD earns EARN["peer_answer_good"] coins (daily cap) and
POINTS["peer_answer_good"], once per answer; the asker's pin gives POINTS["pinned_best_answer"].
Nicknames only; detailed feedback is shown to the answer's author only."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.core.config import get_settings
from app.features.arena import injection
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
MID_GRADE_LANGUAGES = ("ar", "ar-TN")  # graded by mid directly: no compact draft


class Rejected(Exception):
    def __init__(self, key: str, status: int = 400) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


class Fix(BaseModel):
    quote: str = ""
    fix: str = ""


# The rubric (audit N-2): the model rates each criterion with an integer level and the server adds
# them up, 10 points per level (max 100). No score ever appears in a prompt, so nothing anchors it.
CRITERIA: dict[str, int] = {"accuracy": 4, "coverage": 3, "reasoning": 2, "example": 1}
POINTS_PER_LEVEL = 10


class Criterion(BaseModel):
    level: int = 0
    evidence: str = ""


class Grade(BaseModel):
    flag: Literal["ok", "off_topic", "abusive"] = "ok"
    score: int = Field(ge=0, le=100)  # always the server's total of the criteria
    confidence: Literal["high", "medium", "low"] = "medium"
    errors: list[Fix] = Field(default_factory=list, max_length=3)
    good: str = ""
    missing: list[str] = Field(default_factory=list, max_length=2)
    criteria: dict[str, Criterion] = Field(default_factory=dict)


def total(criteria: dict[str, Criterion]) -> int:
    return min(100, POINTS_PER_LEVEL * sum(c.level for c in criteria.values()))


def _criteria(raw: Any) -> dict[str, Criterion] | None:
    if isinstance(raw, list):  # small models write a list: by name if given, else rubric order
        named = {
            str(i.get("name") or i.get("criterion") or i.get("key")).lower(): i
            for i in raw
            if isinstance(i, dict) and (i.get("name") or i.get("criterion") or i.get("key"))
        }
        raw = named if named else dict(zip(CRITERIA, raw, strict=False))
    if not isinstance(raw, dict):
        return None
    out: dict[str, Criterion] = {}
    for name, top in CRITERIA.items():
        item = raw.get(name)
        item = item if isinstance(item, dict) else {"level": item}
        try:
            level = int(round(float(item.get("level"))))
        except (TypeError, ValueError):
            level = 0
        out[name] = Criterion(
            level=max(0, min(top, level)), evidence=str(item.get("evidence") or "")
        )
    return out


REVIEW_KIND = "ARENA_REVIEW"
REVIEW_STAGE = "double_checking"
REVIEW_RETRY_S = 0.0  # least wait before the background review after mid was busy (gateway paces)


def review_reasons(g: Grade, *, peer: bool, injected: bool, evidence_ok: bool) -> list[str]:
    """Why a compact draft must be checked by mid before anything is awarded (audit N-1). An
    off-topic or abusive draft pays nothing anyway, so it needs no review."""
    if g.flag != "ok":
        return []
    reasons = []
    if injected:
        reasons.append("injection")
    if not evidence_ok:
        reasons.append("evidence")
    if g.confidence == "low":
        reasons.append("low_confidence")
    if g.score >= get_settings().TEACHBACK_REVIEW_HIGH_SCORE:
        reasons.append("high_score")
    elif peer and abs(g.score - economy.PEER_ANSWER_THRESHOLD) <= economy.TEACHBACK_REVIEW_BAND:
        reasons.append("near_threshold")  # the coins could flip either way
    return reasons


def needs_review(g: Grade, *, peer: bool) -> bool:
    return bool(review_reasons(g, peer=peer, injected=False, evidence_ok=True))


def pending_review(g: Grade) -> bool:
    """Still unsure after grading: no automatic coins or points; the answer waits for a check."""
    return g.flag == "ok" and g.confidence == "low"


def check_evidence(g: Grade, answer: str) -> tuple[Grade, bool]:
    """(the grade with every level whose evidence isn't in the student's text set to 0, whether
    every level above 0 was supported). Evidence inside a flagged instruction doesn't count."""
    if g.flag != "ok":
        return g, True
    body = f" {injection.without_injection(answer)} "
    criteria, ok = {}, True
    for name, c in g.criteria.items():
        quote = injection.plain(c.evidence)
        valid = c.level == 0 or (len(quote) >= 3 and f" {quote} " in body)
        ok = ok and valid
        criteria[name] = c if valid else Criterion(level=0, evidence=c.evidence)
    return g.model_copy(update={"criteria": criteria, "score": total(criteria)}), ok


async def review_budget_left(user_id: uuid.UUID | None, job_id: uuid.UUID) -> bool:
    """Mid reviews spent today (Tunis day), counted from the jobs that reached the review stage,
    stay under TEACHBACK_REVIEW_DAILY_CAP (all) and TEACHBACK_REVIEW_USER_DAILY_CAP (one)."""
    settings = get_settings()
    start = economy.next_refill() - timedelta(days=1)
    spent = (
        select(func.count())
        .select_from(Job)
        .where(
            Job.kind.in_((GRADE_KIND, SOLO_KIND, REVIEW_KIND)),
            Job.stage == REVIEW_STAGE,
            Job.id != job_id,
            or_(Job.finished_at >= start, Job.status == "running"),
        )
    )
    async with db.get_sessionmaker()() as s:
        everyone = await s.scalar(spent)
        mine = await s.scalar(spent.where(Job.user_id == user_id))
    return (
        everyone < settings.TEACHBACK_REVIEW_DAILY_CAP
        and mine < settings.TEACHBACK_REVIEW_USER_DAILY_CAP
    )


def parse_grade(content: Any) -> Grade | None:
    """The model's reply → a Grade whose score is the server's total of the rubric levels. Any
    "score" the model writes is ignored; an "ok" grade without criteria is unusable (None)."""
    if not isinstance(content, dict):
        return None
    data = {k: v for k, v in content.items() if k != "score"}
    try:
        if data.get("flag") not in ("ok", "off_topic", "abusive"):
            data["flag"] = "ok"
        criteria = _criteria(data.get("criteria"))
        if criteria is None and data["flag"] == "ok":
            return None  # no rubric, no score: never a silent number
        data["criteria"] = criteria or {}
        data["score"] = total(criteria) if criteria and data["flag"] == "ok" else 0
        data["errors"] = [e for e in data.get("errors") or [] if isinstance(e, dict)][:3]
        data["missing"] = [str(m) for m in data.get("missing") or []][:2]
        if data.get("confidence") not in ("high", "medium", "low"):
            data["confidence"] = "medium"
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


@dataclass
class Later:
    """A mid review that couldn't run now (mid busy, or today's review budget spent)."""

    draft: Grade
    values: dict[str, Any]
    not_before: datetime


@dataclass
class Graded:
    grade: Grade  # evidence-checked: unsupported levels count 0
    reviewed: bool = False  # mid made or confirmed it
    pending: bool = False  # nothing is awarded until a mid review settles it
    reasons: list[str] = field(default_factory=list)
    later: Later | None = None


def _values(mode, language, course, chapter, context, prompt, text) -> dict[str, Any]:
    fence = ("<<<STUDENT_TEXT", "STUDENT_TEXT>>>")
    for marker in fence:  # the student can't close the fence early
        text = text.replace(marker, " ")
    return {
        "language": language,
        "mode": "answering a classmate's question" if mode == "peer" else "teaching a concept",
        "course": course,
        "chapter": chapter,
        "context": context,
        "prompt_label": "QUESTION" if mode == "peer" else "CONCEPT",
        "prompt": prompt,
        "answer": text,
    }


async def _review(
    ctx: JobContext,
    values: dict[str, Any],
    draft: Grade,
    lane: Literal["interactive", "background"],
) -> Grade:
    """One mid call on the draft (never a compact fallback: a compact score is what is being
    checked). Defer / GatewayError propagate; an unusable reply is BadOutput."""
    version, messages = prompts.render(
        "teachback_review",
        draft=json.dumps(draft.model_dump(exclude={"score"}), ensure_ascii=False),
        **values,
    )
    reviewed = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.TEACHBACK_GRADE,
                lane=lane,
                messages=messages,
                language=values["language"],
                tier="mid",
                allow_fallback=False,
                prompt_version=f"review-{version}",
            )
        )
    )
    final = parse_grade(reviewed.content)
    if final is None:
        raise gateway.BadOutput("unusable review", refusal="bad_json")
    return final


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
    user_id: uuid.UUID | None,
) -> Graded:
    """draft-then-revise with a guarded finish (audit N-1). One compact draft (Arabic / Darija: one
    mid grade, which is its own review). The draft is final only when nothing calls for a review;
    otherwise mid reviews it now, or — mid busy, or today's review budget spent — the attempt is
    pending and a background review job settles it later. A compact score never pays alone when
    it is high, flagged as injection, or not backed by evidence from the answer."""
    await ctx.set_stage("reading_chapter")
    context = await _context(world_id, chapter.id, f"{prompt} {text}"[:500])
    values = _values(mode, language, course.name, chapter.title, context, prompt, text)
    await ctx.set_stage("scoring_answer")
    version, messages = prompts.render("teachback_grade", **values)
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.TEACHBACK_GRADE,
                lane="interactive",
                messages=messages,
                language=language,
                tier="mid" if language in MID_GRADE_LANGUAGES else None,
                prompt_version=version,
            )
        )
    )
    draft = parse_grade(result.content)
    if draft is None:
        raise gateway.BadOutput("unusable grade", refusal="bad_json")
    supported, evidence_ok = check_evidence(draft, text)
    if result.model_tier == "mid":  # mid graded it (ar / ar-TN): that is the review
        return Graded(supported, reviewed=True, pending=pending_review(supported))
    reasons = review_reasons(
        draft, peer=mode == "peer", injected=injection.detect(text), evidence_ok=evidence_ok
    )
    if not reasons:
        return Graded(supported)
    if not await review_budget_left(user_id, ctx.job_id):
        later = Later(draft, values, economy.next_refill())  # tomorrow's budget
        return Graded(supported, pending=True, reasons=reasons + ["budget"], later=later)
    await ctx.set_stage(REVIEW_STAGE)
    try:
        final = await _review(ctx, values, draft, "interactive")
    except gateway.Defer as d:
        wait = timedelta(seconds=max(d.delay_s, REVIEW_RETRY_S))
        later = Later(draft, values, datetime.now(UTC) + wait)
        return Graded(supported, pending=True, reasons=reasons, later=later)
    except gateway.GatewayError:
        later = Later(draft, values, datetime.now(UTC) + timedelta(seconds=REVIEW_RETRY_S))
        return Graded(supported, pending=True, reasons=reasons, later=later)
    final, _ = check_evidence(final, text)
    return Graded(final, reviewed=True, pending=pending_review(final), reasons=reasons)


async def schedule_review(
    *, user_id: uuid.UUID | None, world_id: uuid.UUID, later: Later, payload: dict[str, Any]
) -> uuid.UUID:
    """A background ARENA_REVIEW job for a pending attempt."""
    async with db.get_sessionmaker()() as s:
        j = await create_job(
            s,
            kind=REVIEW_KIND,
            lane="background",
            payload={
                **payload,
                "values": later.values,
                "draft": later.draft.model_dump(exclude={"score"}),
            },
            user_id=user_id,
            world_id=world_id,
        )
        if j.not_before is None or later.not_before > j.not_before:
            j.not_before = later.not_before
            await s.commit()
        return j.id


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


async def _settle_peer(
    aid: uuid.UUID, g: Graded, *, quick_mode: bool, text_hash_of: str | None = None
) -> tuple[str, int, int | None] | None:
    """Store a peer grade and pay it once when it is final. (status, coins earned, score), or None
    when the answer changed since (a stale background review)."""
    earned = 0
    async with db.get_sessionmaker()() as s:
        a = await s.get(PeerAnswer, aid, with_for_update=True)
        if a is None or (text_hash_of is not None and text_hash(a.text) != text_hash_of):
            return None
        q = await s.get(PeerQuestion, a.question_id)
        grade_ = g.grade
        if grade_.flag != "ok":
            a.status = "rejected"
            a.ai_feedback = {"flag": grade_.flag}
        else:
            a.status = "pending_review" if g.pending else "graded"
            if a.status == "graded":
                await daily.record(s, a.author_id, "teachback", chapter_id=q.chapter_id)
            a.ai_score, a.ai_confidence = grade_.score, grade_.confidence
            a.ai_feedback = {
                "errors": [e.model_dump() for e in grade_.errors],
                "good": grade_.good,
                "missing": grade_.missing,
                "quick_mode": quick_mode,
            }
            a.reviewed_by_mid = g.reviewed
            if (
                a.status == "graded"
                and grade_.score >= economy.PEER_ANSWER_THRESHOLD
                and not a.rewarded
            ):
                a.rewarded = True
                ref = f"answer:{a.id}"
                earned = await wallet.earn(s, a.author_id, economy.EARN["peer_answer_good"], ref)
                await wallet.add_points(
                    s, a.author_id, q.world_id, economy.POINTS["peer_answer_good"], "answer", ref
                )
        await s.commit()
        return a.status, earned, grade_.score


async def _settle_solo(
    user_id: uuid.UUID, world_id: uuid.UUID, chapter_id: uuid.UUID, ref: str, g: Graded
) -> int:
    """Points for a final solo grade, once per solo job (the ledger is unique on the ref)."""
    if g.grade.flag != "ok" or g.pending:
        return 0
    points = economy.POINTS["teachback_solo_per_10_score"] * (g.grade.score // 10)
    async with db.get_sessionmaker()() as s:
        await wallet.add_points(s, user_id, world_id, points, "solo", ref)
        await daily.record(s, user_id, "teachback", chapter_id=chapter_id)
        await s.commit()
    return points


@job(GRADE_KIND, stages=GRADE_STAGES)
async def grade_answer(ctx: JobContext) -> dict[str, Any]:
    aid = uuid.UUID(ctx.payload["answer_id"])
    async with db.get_sessionmaker()() as s:
        a = await s.get(PeerAnswer, aid)
        q = await s.get(PeerQuestion, a.question_id)
        chapter = await s.get(Chapter, q.chapter_id)
        course = await s.get(Course, chapter.course_id)
    language = ctx.payload.get("language") or q.language
    try:
        g = await grade(
            ctx,
            mode="peer",
            world_id=q.world_id,
            chapter=chapter,
            course=course,
            prompt=q.text,
            text=a.text,
            language=language,
            user_id=a.author_id,
        )
    except gateway.Defer:
        raise  # requeued: the answer stays "grading" until the job runs again
    except Exception:
        async with db.get_sessionmaker()() as s:  # let the student send it again
            row = await s.get(PeerAnswer, aid)
            row.status = "failed"
            await s.commit()
        raise
    review_job = None
    if g.later is not None:
        review_job = await schedule_review(
            user_id=a.author_id,
            world_id=q.world_id,
            later=g.later,
            payload={"mode": "peer", "answer_id": str(aid), "text_hash": text_hash(a.text)},
        )
    status, earned, score = await _settle_peer(aid, g, quick_mode=ctx.quick_mode)
    return {
        "answer_id": str(aid),
        "status": status,
        "score": None if g.pending else score,
        "coins_earned": earned,
        "review_job_id": str(review_job) if review_job else None,
    }


@job(SOLO_KIND, stages=GRADE_STAGES)
async def grade_solo(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, uuid.UUID(p["chapter_id"]))
        course = await s.get(Course, chapter.course_id)
        user_id = (await s.get(Job, ctx.job_id)).user_id
    g = await grade(
        ctx,
        mode="solo",
        world_id=course.world_id,
        chapter=chapter,
        course=course,
        prompt=p["concept"] or chapter.title,
        text=p["text"],
        language=p.get("language") or "en",
        user_id=user_id,
    )
    review_job = None
    if g.later is not None:
        review_job = await schedule_review(
            user_id=user_id,
            world_id=course.world_id,
            later=g.later,
            payload={"mode": "solo", "solo_job_id": str(ctx.job_id), "chapter_id": p["chapter_id"]},
        )
    points = await _settle_solo(user_id, course.world_id, chapter.id, str(ctx.job_id), g)
    final = g.grade
    return {
        "flag": final.flag,
        "score": final.score if final.flag == "ok" and not g.pending else None,
        "confidence": final.confidence,
        "errors": [e.model_dump() for e in final.errors],
        "good": final.good,
        "missing": final.missing,
        "reviewed_by_mid": g.reviewed,
        "points": points,
        "pending_review": g.pending,
        "review_job_id": str(review_job) if review_job else None,
    }


@job(REVIEW_KIND, stages=(REVIEW_STAGE,))
async def review_later(ctx: JobContext) -> dict[str, Any]:
    """Settles a pending Teach-Back attempt with the mid review it is waiting for (background
    lane, within the daily review budget; mid busy or budget spent → Defer, it stays pending)."""
    p = ctx.payload
    async with db.get_sessionmaker()() as s:
        me = await s.get(Job, ctx.job_id)
        user_id, world_id = me.user_id, me.world_id
        if p["mode"] == "peer":
            a = await s.get(PeerAnswer, uuid.UUID(p["answer_id"]))
            if a is None or a.status != "pending_review" or text_hash(a.text) != p["text_hash"]:
                return {"skipped": "answer changed"}
    if not await review_budget_left(user_id, ctx.job_id):
        wait = (economy.next_refill() - datetime.now(UTC)).total_seconds()
        raise gateway.Defer(max(60.0, wait), "review_budget")
    await ctx.set_stage(REVIEW_STAGE)
    draft = parse_grade(p["draft"]) or Grade(score=0)
    final = await _review(ctx, p["values"], draft, "background")
    final, _ = check_evidence(final, p["values"]["answer"])
    g = Graded(final, reviewed=True, pending=pending_review(final))
    if p["mode"] == "peer":
        settled = await _settle_peer(
            uuid.UUID(p["answer_id"]), g, quick_mode=False, text_hash_of=p["text_hash"]
        )
        if settled is None:
            return {"skipped": "answer changed"}
        status, earned, score = settled
        return {"answer_id": p["answer_id"], "status": status, "score": score, "coins": earned}
    chapter_id = uuid.UUID(p["chapter_id"])
    points = await _settle_solo(user_id, world_id, chapter_id, p["solo_job_id"], g)
    return {"solo_job_id": p["solo_job_id"], "score": final.score, "points": points}
