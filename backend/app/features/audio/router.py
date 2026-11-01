"""Audio Studio API: the chapter's episode (script, price, pool), and generating it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.features.audio import service
from app.features.quiz.router import Price
from app.features.studio.router import GenerateIn, GenerateOut, chapter_or_404, http_error
from app.features.studio.service import Rejected

router = APIRouter(prefix="/api/audio", tags=["audio"])


class Script(BaseModel):
    title: str
    segments: list[str]  # read one by one; the player highlights the current one


class Episode(BaseModel):
    chapter_id: uuid.UUID
    level: str
    language: str
    script: Script | None
    pending_job_id: uuid.UUID | None
    pool_balance: int
    cost: int
    cached: bool


@router.get("/{chapter_id}/price", response_model=Price)
async def price(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Price:
    chapter = await chapter_or_404(s, user, chapter_id)
    return Price(**await service.price(s, chapter.id, level, user.ui_language))


@router.get("/{chapter_id}", response_model=Episode)
async def get_episode(chapter_id: uuid.UUID, level: str, s: Session, user: CurrentUser) -> Episode:
    chapter = await chapter_or_404(s, user, chapter_id)
    try:
        return Episode(**await service.status(s, user, chapter, level))
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
