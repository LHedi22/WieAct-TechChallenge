"""Teach-Back Arena API: the chapter's question feed (polled), asking, answering / improving,
pinning, helpful votes, and solo mode. Every AI step is a job (see service.py)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, Session
from app.core import economy
from app.features.arena import service
from app.features.arena.service import Rejected
from app.features.worlds.service import NotFound, member_chapter
from app.models import Chapter, Course, PeerAnswer, PeerQuestion, PeerVote, Profile, User

router = APIRouter(prefix="/api/arena", tags=["arena"])


class Author(BaseModel):
    nickname: str
    avatar: dict[str, Any] | None


class QuestionItem(BaseModel):
    id: uuid.UUID
    text: str
    author: Author
    is_mine: bool
    status: str  # pending | open | rejected (the last two only reach the author)
    reject_reason: str | None
    answers: int
    pinned: bool
    answered_by_me: bool
    created_at: datetime


class Feed(BaseModel):
    chapter_id: uuid.UUID
    chapter_title: str
    course_name: str
    ask_cost: int
    solo_cost: int
    questions: list[QuestionItem]


class Feedback(BaseModel):
    errors: list[dict[str, str]]
    good: str
    missing: list[str]
    quick_mode: bool = False


class AnswerOut(BaseModel):
    id: uuid.UUID
    author: Author
    is_mine: bool
    text: str
    status: str  # grading | graded | rejected | failed
    score: int | None
    confidence: str | None
    helpful: int
    voted: bool
    pinned: bool
    feedback: Feedback | None  # the author's own answer only
    reject_flag: str | None
    grading_job_id: uuid.UUID | None
    updated_at: datetime


class QuestionDetail(BaseModel):
    question: QuestionItem
    answers: list[AnswerOut]  # graded answers of classmates, pinned first
    my_answer: AnswerOut | None
    can_answer: bool
    can_pin: bool
    threshold: int


class AskIn(BaseModel):
    chapter_id: uuid.UUID
    text: str = Field(min_length=8, max_length=300)


class AnswerIn(BaseModel):
    text: str = Field(min_length=20, max_length=1500)


class SoloIn(BaseModel):
    chapter_id: uuid.UUID
    concept: str = Field(min_length=2, max_length=120)
    text: str = Field(min_length=20, max_length=1500)


class Started(BaseModel):
    job_id: uuid.UUID
    cost: int
    question_id: uuid.UUID | None = None
    answer_id: uuid.UUID | None = None


class Votes(BaseModel):
    helpful: int
    voted: bool


def _http(e: Rejected | NotFound) -> HTTPException:
    return HTTPException(getattr(e, "status", 404), e.key)


async def _chapter(s, user: User, chapter_id: uuid.UUID) -> Chapter:
    try:
        return await member_chapter(s, user, chapter_id)
    except NotFound as e:
        raise _http(e) from e


async def _question(s, user: User, question_id: uuid.UUID) -> PeerQuestion:
    q = await s.get(PeerQuestion, question_id)
    if q is None or (q.status != "open" and q.author_id != user.id):
        raise HTTPException(404, "errors.arena_not_found")
    await _chapter(s, user, q.chapter_id)
    return q


async def _answer(s, user: User, answer_id: uuid.UUID) -> PeerAnswer:
    a = await s.get(PeerAnswer, answer_id)
    if a is None:
        raise HTTPException(404, "errors.arena_not_found")
    await _question(s, user, a.question_id)
    return a


async def _authors(s, ids: set[uuid.UUID]) -> dict[uuid.UUID, Author]:
    rows = await s.execute(
        select(User.id, User.nickname, Profile.avatar)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(User.id.in_(ids))
    )
    return {uid: Author(nickname=n, avatar=av) for uid, n, av in rows.all()}


async def _items(s, user: User, questions: list[PeerQuestion]) -> list[QuestionItem]:
    ids = [q.id for q in questions]
    counts = dict(
        (
            await s.execute(
                select(PeerAnswer.question_id, func.count())
                .where(PeerAnswer.question_id.in_(ids), PeerAnswer.status == "graded")
                .group_by(PeerAnswer.question_id)
            )
        ).all()
    )
    mine = set(
        await s.scalars(
            select(PeerAnswer.question_id).where(
                PeerAnswer.question_id.in_(ids), PeerAnswer.author_id == user.id
            )
        )
    )
    authors = await _authors(s, {q.author_id for q in questions})
    return [
        QuestionItem(
            id=q.id,
            text=q.text,
            author=authors[q.author_id],
            is_mine=q.author_id == user.id,
            status=q.status,
            reject_reason=q.reject_reason,
            answers=counts.get(q.id, 0),
            pinned=q.pinned_answer_id is not None,
            answered_by_me=q.id in mine,
            created_at=q.created_at,
        )
        for q in questions
    ]


@router.get("/questions", response_model=Feed)
async def feed(chapter_id: uuid.UUID, s: Session, user: CurrentUser) -> Feed:
    chapter = await _chapter(s, user, chapter_id)
    course = await s.get(Course, chapter.course_id)
    questions = list(
        await s.scalars(
            select(PeerQuestion)
            .where(
                PeerQuestion.chapter_id == chapter.id,
                (PeerQuestion.status == "open") | (PeerQuestion.author_id == user.id),
            )
            .order_by(PeerQuestion.created_at.desc())
            .limit(50)
        )
    )
    return Feed(
        chapter_id=chapter.id,
        chapter_title=chapter.title,
        course_name=course.name,
        ask_cost=economy.COST["peer_question"],
        solo_cost=economy.COST["teachback_solo"],
        questions=await _items(s, user, questions),
    )


@router.post("/questions", response_model=Started, status_code=202)
async def ask(body: AskIn, s: Session, user: CurrentUser) -> Started:
    chapter = await _chapter(s, user, body.chapter_id)
    q, j = await service.ask(s, user, chapter, body.text)
    return Started(job_id=j.id, cost=j.cost, question_id=q.id)


@router.get("/questions/{question_id}", response_model=QuestionDetail)
async def detail(question_id: uuid.UUID, s: Session, user: CurrentUser) -> QuestionDetail:
    q = await _question(s, user, question_id)
    rows = list(
        await s.scalars(
            select(PeerAnswer)
            .where(
                PeerAnswer.question_id == q.id,
                (PeerAnswer.status == "graded") | (PeerAnswer.author_id == user.id),
            )
            .order_by(PeerAnswer.ai_score.desc().nulls_last(), PeerAnswer.created_at)
        )
    )
    helpful = await service.helpful_counts(s, [a.id for a in rows])
    voted = set(
        await s.scalars(
            select(PeerVote.answer_id).where(
                PeerVote.user_id == user.id, PeerVote.answer_id.in_([a.id for a in rows])
            )
        )
    )
    authors = await _authors(s, {a.author_id for a in rows})
    out, mine = [], None
    for a in rows:
        own = a.author_id == user.id
        fb = a.ai_feedback or {}
        view = AnswerOut(
            id=a.id,
            author=authors[a.author_id],
            is_mine=own,
            text=a.text,
            status=a.status,
            score=a.ai_score,
            confidence=a.ai_confidence,
            helpful=helpful.get(a.id, 0),
            voted=a.id in voted,
            pinned=a.id == q.pinned_answer_id,
            feedback=Feedback(**{k: fb[k] for k in Feedback.model_fields if k in fb})
            if own and a.status == "graded"
            else None,
            reject_flag=fb.get("flag") if own and a.status == "rejected" else None,
            grading_job_id=await service.grading_job(s, a.id)
            if own and a.status == "grading"
            else None,
            updated_at=a.updated_at or a.created_at,
        )
        if own:
            mine = view
        else:
            out.append(view)
    out.sort(key=lambda v: not v.pinned)  # the pinned answer first, then by score
    (item,) = await _items(s, user, [q])
    is_asker = q.author_id == user.id
    return QuestionDetail(
        question=item,
        answers=out,
        my_answer=mine,
        can_answer=q.status == "open" and not is_asker,
        can_pin=is_asker and q.pinned_answer_id is None,
        threshold=economy.PEER_ANSWER_THRESHOLD,
    )


@router.post("/questions/{question_id}/answers", response_model=Started, status_code=202)
async def answer(question_id: uuid.UUID, body: AnswerIn, s: Session, user: CurrentUser) -> Started:
    q = await _question(s, user, question_id)
    try:
        a, j = await service.answer(s, user, q, body.text)
    except Rejected as e:
        raise _http(e) from e
    return Started(job_id=j.id, cost=0, answer_id=a.id)


@router.post("/answers/{answer_id}/pin", status_code=204)
async def pin(answer_id: uuid.UUID, s: Session, user: CurrentUser) -> None:
    a = await _answer(s, user, answer_id)
    try:
        await service.pin(s, user, a)
    except Rejected as e:
        raise _http(e) from e
    await s.commit()


async def _vote(answer_id: uuid.UUID, s, user: User, helpful: bool) -> Votes:
    a = await _answer(s, user, answer_id)
    try:
        await service.vote(s, user, a, helpful)
    except Rejected as e:
        raise _http(e) from e
    await s.commit()
    return Votes(helpful=(await service.helpful_counts(s, [a.id])).get(a.id, 0), voted=helpful)


@router.post("/answers/{answer_id}/helpful", response_model=Votes)
async def mark_helpful(answer_id: uuid.UUID, s: Session, user: CurrentUser) -> Votes:
    return await _vote(answer_id, s, user, True)


@router.delete("/answers/{answer_id}/helpful", response_model=Votes)
async def unmark_helpful(answer_id: uuid.UUID, s: Session, user: CurrentUser) -> Votes:
    return await _vote(answer_id, s, user, False)


@router.post("/solo", response_model=Started, status_code=202)
async def solo(body: SoloIn, s: Session, user: CurrentUser) -> Started:
    chapter = await _chapter(s, user, body.chapter_id)
    j = await service.solo(s, user, chapter, body.concept, body.text)
    return Started(job_id=j.id, cost=j.cost)
