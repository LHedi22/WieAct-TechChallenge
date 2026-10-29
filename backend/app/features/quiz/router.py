"""Quiz Hall API: price (before Confirm), start, attempt, answer, skip, finish."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.features.quiz import service
from app.features.quiz.service import AttemptView, QuestionView, Rejected, Results
from app.features.worlds.service import NotFound, member_chapter
from app.models import Job, QuizAttempt

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


class Price(BaseModel):
    cost: int
    cached: bool


class StartIn(BaseModel):
    chapter_id: uuid.UUID
    level: str


class StartOut(BaseModel):
    attempt_id: uuid.UUID | None  # a shared set was ready: no AI call, free
    job_id: uuid.UUID | None  # a new set is being written: poll the job, then from-job
    cost: int
    cached: bool


class AnswerIn(BaseModel):
    q: int = Field(ge=0)
    choice: int = Field(ge=0, le=3)


class SkipIn(BaseModel):
    q: int = Field(ge=0)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, NotFound):
        return HTTPException(404, e.key)
    if isinstance(e, Rejected):
        return HTTPException(e.status, e.key)
    raise e


async def _chapter(s, user, chapter_id):
    try:
        return await member_chapter(s, user, chapter_id)
    except NotFound as e:
        raise _http(e) from e


async def _attempt(s, user, attempt_id: uuid.UUID) -> QuizAttempt:
    attempt = await s.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:  # attempts are personal
        raise HTTPException(404, "errors.quiz_not_found")
    return attempt


@router.get("/price", response_model=Price)
async def price(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Price:
    chapter = await _chapter(s, user, chapter_id)
    return Price(**await service.price(s, user, chapter.id, level, user.ui_language))


@router.post("/start", response_model=StartOut)
async def start(body: StartIn, s: Session, user: CurrentUser) -> StartOut:
    chapter = await _chapter(s, user, body.chapter_id)
    try:
        return StartOut(**await service.start(s, user, chapter, body.level))
    except Rejected as e:
        raise _http(e) from e


@router.post("/attempts/from-job/{job_id}", response_model=AttemptView)
async def from_job(job_id: uuid.UUID, s: Session, user: CurrentUser) -> AttemptView:
    job = await s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "errors.job_not_found")
    try:
        attempt = await service.attempt_from_job(s, user, job)
    except Rejected as e:
        raise _http(e) from e
    await _chapter(s, user, attempt.chapter_id)  # membership
    return await service.view(s, attempt)


@router.get("/attempts/{attempt_id}", response_model=AttemptView)
async def get_attempt(attempt_id: uuid.UUID, s: Session, user: CurrentUser) -> AttemptView:
    return await service.view(s, await _attempt(s, user, attempt_id))


@router.post("/attempts/{attempt_id}/answer", response_model=QuestionView)
async def answer(attempt_id: uuid.UUID, body: AnswerIn, s: Session, user: CurrentUser):
    attempt = await _attempt(s, user, attempt_id)
    try:
        return await service.answer(s, attempt, body.q, body.choice)
    except Rejected as e:
        raise _http(e) from e


@router.post("/attempts/{attempt_id}/skip", response_model=QuestionView)
async def skip(attempt_id: uuid.UUID, body: SkipIn, s: Session, user: CurrentUser):
    attempt = await _attempt(s, user, attempt_id)
    try:
        return await service.skip(s, attempt, body.q)
    except Rejected as e:
        raise _http(e) from e


@router.post("/attempts/{attempt_id}/finish", response_model=Results)
async def finish(attempt_id: uuid.UUID, s: Session, user: CurrentUser) -> Results:
    return await service.finish(s, user, await _attempt(s, user, attempt_id))
