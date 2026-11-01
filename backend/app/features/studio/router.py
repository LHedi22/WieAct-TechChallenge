"""Study Studio API: the chapter's pack (notes, mind map, card counts, price), generating it, the
flashcard queue and reviews, and personal cards from a finished quiz."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.features.quiz.router import Price
from app.features.studio import service, srs
from app.features.studio.service import Pay, Rejected
from app.features.worlds.service import NotFound, member_chapter
from app.models import QuizAttempt

router = APIRouter(prefix="/api/studio", tags=["studio"])
quiz_router = APIRouter(prefix="/api/quiz", tags=["studio"])


class NoteSection(BaseModel):
    heading: str
    points: list[str]
    refs: list[str]  # page:12, slide:3 …


class KeyTerm(BaseModel):
    term: str
    meaning: str


class Notes(BaseModel):
    title: str
    sections: list[NoteSection]
    key_terms: list[KeyTerm]


class MapBranch(BaseModel):
    label: str
    children: list[str]


class MindMap(BaseModel):
    root: str
    branches: list[MapBranch]


class CardCounts(BaseModel):
    new: int
    learning: int
    review: int
    total: int


class Studio(BaseModel):
    chapter_id: uuid.UUID
    chapter_title: str
    level: str
    language: str
    notes: Notes | None
    map: MindMap | None
    missing: list[str]  # parts not generated yet: notes | flashcards | map
    pending_job_id: uuid.UUID | None
    cards: CardCounts
    pool_balance: int
    cost: int
    cached: bool


class GenerateIn(BaseModel):
    level: str
    pay: Pay = "me"


class GenerateOut(BaseModel):
    job_id: uuid.UUID | None  # None: the pack is complete, nothing to do
    cost: int
    cached: bool


class CardOut(BaseModel):
    id: uuid.UUID
    front: str
    back: str
    concept: str | None
    source: str  # deck | quiz
    stage: str  # new | learning | review
    intervals: dict[str, int]  # seconds until it comes back, per grade


class Queue(BaseModel):
    cards: list[CardOut]
    counts: CardCounts
    next_due_at: datetime | None


class ReviewIn(BaseModel):
    grade: srs.Grade


class ReviewOut(BaseModel):
    card_id: uuid.UUID
    due_at: datetime
    interval_s: int


class FromQuizOut(BaseModel):
    added: int
    chapter_id: uuid.UUID
    level: str


def http_error(e: Exception) -> HTTPException:
    if isinstance(e, NotFound):
        return HTTPException(404, e.key)
    if isinstance(e, Rejected):
        return HTTPException(e.status, e.key)
    raise e


async def chapter_or_404(s, user, chapter_id):
    try:
        return await member_chapter(s, user, chapter_id)
    except NotFound as e:
        raise http_error(e) from e


@router.get("/{chapter_id}/price", response_model=Price)
async def price(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Price:
    chapter = await chapter_or_404(s, user, chapter_id)
    return Price(**await service.price(s, chapter.id, level, user.ui_language))


@router.get("/{chapter_id}", response_model=Studio)
async def get_studio(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Studio:
    chapter = await chapter_or_404(s, user, chapter_id)
    try:
        return Studio(**await service.status(s, user, chapter, level))
    except Rejected as e:
        raise http_error(e) from e


@router.post("/{chapter_id}/generate", response_model=GenerateOut)
async def generate(
    chapter_id: uuid.UUID, body: GenerateIn, s: Session, user: CurrentUser
) -> GenerateOut:
    chapter = await chapter_or_404(s, user, chapter_id)
    try:
        return GenerateOut(**await service.generate(s, user, chapter, body.level, body.pay))
    except Rejected as e:
        raise http_error(e) from e


@router.get("/{chapter_id}/cards", response_model=Queue)
async def cards(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Queue:
    chapter = await chapter_or_404(s, user, chapter_id)
    return Queue(**await service.queue(s, user, chapter, level))


@router.post("/cards/{card_id}/review", response_model=ReviewOut)
async def review(card_id: uuid.UUID, body: ReviewIn, s: Session, user: CurrentUser) -> ReviewOut:
    try:
        out = ReviewOut(**await service.review(s, user, card_id, body.grade))
    except Rejected as e:
        raise http_error(e) from e
    await s.commit()
    return out


@quiz_router.post("/attempts/{attempt_id}/flashcards", response_model=FromQuizOut)
async def from_quiz(attempt_id: uuid.UUID, s: Session, user: CurrentUser) -> FromQuizOut:
    attempt = await s.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:  # attempts are personal
        raise HTTPException(404, "errors.quiz_not_found")
    try:
        out = FromQuizOut(**await service.from_quiz(s, user, attempt))
    except Rejected as e:
        raise http_error(e) from e
    await s.commit()
    return out
