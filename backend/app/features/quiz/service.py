"""Quiz Hall: pick a shared set (free) or generate a new one (a job, economy COST["quiz"]), then
run the attempt here: answers are graded on the server and never sent ahead (hints before answers:
first wrong → hint + second try; second wrong or skip → the answer + explanation)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy
from app.features.daily import service as daily
from app.features.quiz import pool
from app.features.wallet import service as wallet
from app.jobs.service import create_job
from app.models import (
    Chapter,
    ChapterMastery,
    Course,
    Job,
    QuizAttempt,
    QuizSet,
    User,
)

LEVELS = ("beginner", "intermediate", "advanced")
Status = Literal["pending", "hint", "correct", "second", "wrong", "skipped"]
DONE: tuple[str, ...] = ("correct", "second", "wrong", "skipped")
WEAK_BELOW = 50


class Rejected(Exception):
    def __init__(self, key: str, status: int = 400) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


# --- choosing a set ------------------------------------------------------------------------------
async def unseen_set(
    s: AsyncSession, user: User, chapter_id: uuid.UUID, level: str, language: str
) -> QuizSet | None:
    seen = select(QuizAttempt.quiz_set_id).where(QuizAttempt.user_id == user.id)
    return await s.scalar(
        select(QuizSet)
        .where(
            QuizSet.chapter_id == chapter_id,
            QuizSet.level == level,
            QuizSet.language == language,
            QuizSet.id.not_in(seen),
        )
        .order_by(QuizSet.seed)
        .limit(1)
    )


async def price(s, user, chapter_id, level, language) -> dict[str, Any]:
    """What Confirm will cost, told to the UI before the student confirms (ECONOMY.md)."""
    if await unseen_set(s, user, chapter_id, level, language):
        return {"cost": economy.COST["cached_content"], "cached": True}
    return {"cost": economy.COST["quiz"], "cached": False}


async def start(s: AsyncSession, user: User, chapter: Chapter, level: str) -> dict[str, Any]:
    if level not in LEVELS:
        raise Rejected("errors.level_invalid")
    course = await s.get(Course, chapter.course_id)
    language = user.ui_language
    # An unfinished attempt here is resumed (Save and exit, a double click, a reload) instead of
    # using up another shared set.
    unfinished = await s.scalar(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.chapter_id == chapter.id,
            QuizAttempt.level == level,
            QuizAttempt.language == language,
            QuizAttempt.status == "in_progress",
        )
    )
    if unfinished:
        return {"attempt_id": unfinished.id, "job_id": None, "cost": 0, "cached": True}
    found = await unseen_set(s, user, chapter.id, level, language)
    if found:
        attempt = await create_attempt(s, user, found, course)
        return {"attempt_id": attempt.id, "job_id": None, "cost": 0, "cached": True}
    # A classmate is already generating this chapter + level + language: share that job.
    job_id = await pool.pending_generation(s, chapter.id, level, language)
    cost = 0  # sharing that job reserves nothing: this student gets the class's set for free
    if job_id is None:
        cost = economy.COST["quiz"]
        seed = await pool.next_seed(s, chapter.id, level, language)
        job = await create_job(
            s,
            kind=pool.KIND,
            lane="interactive",
            payload={
                "chapter_id": str(chapter.id),
                "level": level,
                "language": language,
                "seed": seed,
            },
            user_id=user.id,
            world_id=course.world_id,
            cost=cost,
        )
        job_id = job.id
    return {"attempt_id": None, "job_id": job_id, "cost": cost, "cached": False}


async def create_attempt(s: AsyncSession, user: User, qs: QuizSet, course: Course) -> QuizAttempt:
    existing = await s.scalar(
        select(QuizAttempt).where(
            QuizAttempt.user_id == user.id,
            QuizAttempt.quiz_set_id == qs.id,
        )
    )
    if existing:
        return existing
    attempt = QuizAttempt(
        user_id=user.id,
        quiz_set_id=qs.id,
        world_id=qs.world_id,
        course_id=course.id,
        chapter_id=qs.chapter_id,
        level=qs.level,
        language=qs.language,
        answers=[{"first": None, "second": None, "status": "pending"} for _ in qs.questions],
        current=0,
        score=0,
        points=0,
        second_tries=0,
        status="in_progress",
    )
    s.add(attempt)
    await s.commit()
    return attempt


async def attempt_from_job(s: AsyncSession, user: User, job: Job) -> QuizAttempt:
    if job.kind != pool.KIND or job.status != "done" or not job.result:
        raise Rejected("errors.quiz_not_ready", 409)
    qs = await s.get(QuizSet, uuid.UUID(job.result["quiz_set_id"]))
    if qs is None:
        raise Rejected("errors.quiz_not_ready", 409)
    chapter = await s.get(Chapter, qs.chapter_id)
    course = await s.get(Course, chapter.course_id)
    return await create_attempt(s, user, qs, course)


# --- the attempt ---------------------------------------------------------------------------------
class QuestionView(BaseModel):
    i: int
    question: str
    options: list[str]
    status: Status
    first: int | None = None
    second: int | None = None
    hint: str | None = None  # after a first wrong answer
    answer_index: int | None = None  # only once the question is over
    explanation: str | None = None  # only once the question is over


class AttemptView(BaseModel):
    id: uuid.UUID
    world_id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    chapter_id: uuid.UUID
    chapter_title: str
    chapter_idx: int
    level: str
    status: str
    current: int
    points: int
    questions: list[QuestionView]


def question_view(i: int, q: dict[str, Any], a: dict[str, Any]) -> QuestionView:
    status = a["status"]
    over = status in DONE
    return QuestionView(
        i=i,
        question=q["question"],
        options=q["options"],
        status=status,
        first=a.get("first"),
        second=a.get("second"),
        hint=q.get("hint") or None if status == "hint" or over else None,
        answer_index=q["answer_index"] if over else None,
        explanation=q.get("explanation") or None if over else None,
    )


async def view(s: AsyncSession, attempt: QuizAttempt) -> AttemptView:
    qs = await s.get(QuizSet, attempt.quiz_set_id)
    chapter = await s.get(Chapter, attempt.chapter_id)
    course = await s.get(Course, attempt.course_id)
    return AttemptView(
        id=attempt.id,
        world_id=attempt.world_id,
        course_id=attempt.course_id,
        course_name=course.name,
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        chapter_idx=chapter.idx,
        level=attempt.level,
        status=attempt.status,
        current=attempt.current,
        points=attempt.points,
        questions=[
            question_view(i, q, a)
            for i, (q, a) in enumerate(zip(qs.questions, attempt.answers, strict=True))
        ],
    )


async def _load(s: AsyncSession, attempt: QuizAttempt, i: int) -> tuple[dict, dict, list]:
    if attempt.status != "in_progress":
        raise Rejected("errors.quiz_finished", 409)
    qs = await s.get(QuizSet, attempt.quiz_set_id)
    if not 0 <= i < len(qs.questions):
        raise Rejected("errors.quiz_question_invalid")
    answers = [dict(a) for a in attempt.answers]
    return qs.questions[i], answers[i], answers


def _advance(attempt: QuizAttempt, answers: list[dict]) -> None:
    attempt.answers = answers  # reassign: JSONB changes are tracked per attribute
    pending = [k for k, a in enumerate(answers) if a["status"] not in DONE]
    attempt.current = pending[0] if pending else len(answers)


async def answer(s: AsyncSession, attempt: QuizAttempt, i: int, choice: int) -> QuestionView:
    q, a, answers = await _load(s, attempt, i)
    if not 0 <= choice <= 3:
        raise Rejected("errors.quiz_choice_invalid")
    if a["status"] in DONE:
        raise Rejected("errors.quiz_question_done", 409)
    right = choice == q["answer_index"]
    if a["status"] == "pending":
        a["first"] = choice
        if right:
            a["status"] = "correct"
            attempt.points += economy.POINTS["quiz_correct_first_try"]
        else:
            a["status"] = "hint"  # free hint, second try (hints before answers)
    else:  # second try after the hint
        a["second"] = choice
        attempt.second_tries += 1
        if right:
            a["status"] = "second"
            attempt.points += economy.POINTS["quiz_correct_second_try"]
        else:
            a["status"] = "wrong"
    answers[i] = a
    _advance(attempt, answers)
    if a["status"] in DONE:  # a question answered for good counts for today's challenges
        await daily.record(s, attempt.user_id, "quiz_questions", chapter_id=attempt.chapter_id)
    await s.commit()
    return question_view(i, q, a)


async def skip(s: AsyncSession, attempt: QuizAttempt, i: int) -> QuestionView:
    q, a, answers = await _load(s, attempt, i)
    if a["status"] in DONE:
        raise Rejected("errors.quiz_question_done", 409)
    a["status"] = "skipped"
    answers[i] = a
    _advance(attempt, answers)
    await s.commit()
    return question_view(i, q, a)


# --- results -------------------------------------------------------------------------------------
class Missed(BaseModel):
    i: int
    question: str
    status: str
    yours: str | None
    correct: str
    explanation: str | None
    concept: str | None


class NextStep(BaseModel):
    kind: Literal["tutor", "quiz"]
    chapter_id: uuid.UUID
    chapter_title: str
    level: str
    cost: int


class Results(BaseModel):
    attempt_id: uuid.UUID
    score: int
    total: int
    points: int  # from the answers
    activity_points: int  # bonus for finishing (POINTS["activity_completed"])
    second_tries: int
    mastery: int
    weak: bool
    missed: list[Missed]
    right_concepts: list[str]
    next_step: NextStep
    tag_job_id: uuid.UUID | None


async def finish(s: AsyncSession, user: User, attempt: QuizAttempt) -> Results:
    qs = await s.get(QuizSet, attempt.quiz_set_id)
    chapter = await s.get(Chapter, attempt.chapter_id)
    first_finish = attempt.status == "in_progress"
    answers = [dict(a) for a in attempt.answers]
    for a in answers:  # finishing early counts what is left as skipped
        if a["status"] not in DONE:
            a["status"] = "skipped"
    attempt.answers = answers
    score = sum(a["status"] in ("correct", "second") for a in answers)
    total = len(answers)
    attempt.score = score

    mastery_row = await s.get(ChapterMastery, (user.id, chapter.id))
    pct = round(100 * score / total) if total else 0
    mastery = pct if mastery_row is None else round(0.6 * mastery_row.mastery + 0.4 * pct)
    tag_job_id = None
    if first_finish:
        attempt.status = "finished"
        attempt.finished_at = datetime.now(UTC)
        ref = str(attempt.id)
        await wallet.add_points(s, user.id, attempt.world_id, attempt.points, "quiz_answers", ref)
        await wallet.add_points(
            s, user.id, attempt.world_id, economy.POINTS["activity_completed"], "activity", ref
        )
        stmt = insert(ChapterMastery).values(
            user_id=user.id, chapter_id=chapter.id, mastery=mastery, weak=mastery < WEAK_BELOW
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "chapter_id"],
                set_={"mastery": mastery, "weak": mastery < WEAK_BELOW},
            )
        )
        if any(a["status"] != "correct" for a in answers):
            from app.features.quiz.tagging import KIND as TAG_KIND  # noqa: PLC0415

            job = await create_job(
                s,
                kind=TAG_KIND,
                lane="background",
                payload={"attempt_id": str(attempt.id)},
                user_id=user.id,
                world_id=attempt.world_id,
            )
            tag_job_id = job.id
        await daily.record(s, user.id, "quiz_score", chapter_id=chapter.id, score_pct=pct)
    else:
        mastery = mastery_row.mastery if mastery_row else pct
    await s.commit()

    missed = []
    right: list[str] = []
    for i, (q, a) in enumerate(zip(qs.questions, answers, strict=True)):
        if a["status"] == "correct":
            if q.get("concept"):
                right.append(q["concept"])
            continue
        yours = a.get("second") if a.get("second") is not None else a.get("first")
        missed.append(
            Missed(
                i=i,
                question=q["question"],
                status=a["status"],
                yours=q["options"][yours] if yours is not None else None,
                correct=q["options"][q["answer_index"]],
                explanation=q.get("explanation") or None,
                concept=q.get("concept") or None,
            )
        )
    return Results(
        attempt_id=attempt.id,
        score=score,
        total=total,
        points=attempt.points,
        activity_points=economy.POINTS["activity_completed"],
        second_tries=attempt.second_tries,
        mastery=mastery,
        weak=mastery < WEAK_BELOW,
        missed=missed,
        right_concepts=list(dict.fromkeys(right))[:5],
        next_step=await next_step(s, attempt, chapter, score, total),
        tag_job_id=tag_job_id,
    )


async def next_step(s, attempt: QuizAttempt, chapter: Chapter, score: int, total: int) -> NextStep:
    """ONE suggestion: struggling → the Socratic Tutor on this chapter; doing well → the next
    chapter's quiz at the same level (or this one again at the next level)."""
    if score < total * 0.8:
        return NextStep(
            kind="tutor",
            chapter_id=chapter.id,
            chapter_title=chapter.title,
            level=attempt.level,
            cost=economy.COST["tutor_session"],
        )
    nxt = await s.scalar(
        select(Chapter)
        .where(Chapter.course_id == chapter.course_id, Chapter.idx > chapter.idx)
        .order_by(Chapter.idx)
        .limit(1)
    )
    level = attempt.level
    if nxt is None:
        nxt = chapter
        level = LEVELS[min(LEVELS.index(attempt.level) + 1, len(LEVELS) - 1)]
    return NextStep(
        kind="quiz",
        chapter_id=nxt.id,
        chapter_title=nxt.title,
        level=level,
        cost=economy.COST["quiz"],
    )
