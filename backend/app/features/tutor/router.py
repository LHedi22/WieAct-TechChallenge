"""Socratic Tutor API: start a session, send turns (message / hint / another way / stuck), end."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.features.tutor import service
from app.features.tutor.service import MAX_HINTS, Rejected
from app.features.worlds.service import NotFound, member_chapter
from app.models import Chapter, Course, TutorSession

router = APIRouter(prefix="/api/tutor", tags=["tutor"])


class TutorStartIn(BaseModel):
    chapter_id: uuid.UUID
    level: Literal["beginner", "intermediate", "advanced"]


class TurnIn(BaseModel):
    text: str = Field("", max_length=1500)
    action: service.Action = "message"


class JobRef(BaseModel):
    session_id: uuid.UUID
    job_id: uuid.UUID


class Idea(BaseModel):
    text: str
    found: bool


class Turn(BaseModel):
    role: Literal["student", "tutor"]
    text: str
    action: str | None = None
    tier: str | None = None
    quick_mode: bool = False
    confidence: str | None = None
    at: datetime | None = None


class SessionOut(BaseModel):
    id: uuid.UUID
    world_id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    chapter_id: uuid.UUID
    chapter_title: str
    level: str
    status: Literal["active", "ended"]
    goal: str | None
    ideas: list[Idea]
    hints_used: int
    max_hints: int
    turns: list[Turn]
    pending_job_id: uuid.UUID | None
    summary: dict[str, Any] | None


async def _session(s, user, session_id: uuid.UUID) -> TutorSession:
    row = await s.get(TutorSession, session_id)
    if row is None or row.user_id != user.id:  # conversations are personal
        raise HTTPException(404, "errors.tutor_not_found")
    return row


async def _out(s, row: TutorSession) -> SessionOut:
    chapter = await s.get(Chapter, row.chapter_id)
    course = await s.get(Course, row.course_id)
    return SessionOut(
        id=row.id,
        world_id=row.world_id,
        course_id=row.course_id,
        course_name=course.name,
        chapter_id=row.chapter_id,
        chapter_title=chapter.title,
        level=row.level,
        status=row.status,
        goal=row.goal,
        ideas=[Idea(**i) for i in row.ideas],
        hints_used=row.hints_used,
        max_hints=MAX_HINTS,
        turns=[Turn(**t) for t in row.turns],
        pending_job_id=row.pending_job_id,
        summary=row.summary,
    )


def _http(e: Rejected) -> HTTPException:
    return HTTPException(e.status, e.key)


@router.post("/start", response_model=JobRef)
async def start(body: TutorStartIn, s: Session, user: CurrentUser) -> JobRef:
    try:
        chapter = await member_chapter(s, user, body.chapter_id)
    except NotFound as e:
        raise HTTPException(404, e.key) from e
    row = await service.start(s, user, chapter, body.level)
    return JobRef(session_id=row.id, job_id=row.pending_job_id)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, s: Session, user: CurrentUser) -> SessionOut:
    return await _out(s, await _session(s, user, session_id))


@router.post("/{session_id}/turn", response_model=JobRef)
async def turn(session_id: uuid.UUID, body: TurnIn, s: Session, user: CurrentUser) -> JobRef:
    row = await _session(s, user, session_id)
    try:
        job_id = await service.turn(s, row, body.text, body.action)
    except Rejected as e:
        raise _http(e) from e
    return JobRef(session_id=row.id, job_id=job_id)


@router.post("/{session_id}/end", response_model=JobRef)
async def end(session_id: uuid.UUID, s: Session, user: CurrentUser) -> JobRef:
    row = await _session(s, user, session_id)
    try:
        job_id = await service.end(s, row)
    except Rejected as e:
        raise _http(e) from e
    return JobRef(session_id=row.id, job_id=job_id)
