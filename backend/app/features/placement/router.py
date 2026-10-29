"""Placement API: start (cached set → questions now; else a job), get questions, finish (grade)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core import economy
from app.features.placement import service
from app.features.worlds.map import course_for_member
from app.features.worlds.service import NotFound
from app.jobs.service import create_job
from app.models import Chapter, Chunk, Job

router = APIRouter(prefix="/api/placement", tags=["placement"])


class PlacementStartIn(BaseModel):
    course_id: uuid.UUID


class AskedQuestion(BaseModel):
    """A placement question as the student sees it: no answer, no difficulty."""

    i: int
    question: str
    options: list[str]


class QuestionsOut(BaseModel):
    course_id: uuid.UUID
    questions: list[AskedQuestion]


class PlacementStartOut(BaseModel):
    course_id: uuid.UUID
    cached: bool
    cost: int
    job_id: uuid.UUID | None  # set when the questions still have to be written
    questions: list[AskedQuestion] | None  # set when they are ready (no answers inside)


class FinishIn(BaseModel):
    course_id: uuid.UUID
    answers: list[int | None] = Field(max_length=20)


async def _course(s, user, course_id):
    try:
        return await course_for_member(s, user, course_id)
    except NotFound as e:
        raise HTTPException(404, e.key) from e


@router.post("/start", response_model=PlacementStartOut)
async def start(body: PlacementStartIn, s: Session, user: CurrentUser) -> PlacementStartOut:
    course = await _course(s, user, body.course_id)
    language = user.ui_language
    cost = economy.COST["placement_quiz"]
    existing = await service.find_set(course.id, language)
    if existing:
        return PlacementStartOut(
            course_id=course.id,
            cached=True,
            cost=0,
            job_id=None,
            questions=service.redact(existing.questions),
        )
    has_material = await s.scalar(
        select(Chunk.id)
        .join(Chapter, Chapter.id == Chunk.chapter_id)
        .where(Chapter.course_id == course.id)
        .limit(1)
    )
    if not has_material:
        raise HTTPException(409, "errors.placement_no_material")
    # Classmates starting at the same moment share one job (and one AI call).
    pending = await s.scalar(
        select(Job.id).where(
            Job.kind == service.KIND,
            Job.status.in_(("queued", "running")),
            Job.payload["course_id"].astext == str(course.id),
            Job.payload["language"].astext == language,
        )
    )
    if pending is None:
        created = await create_job(
            s,
            kind=service.KIND,
            lane="interactive",
            payload={"course_id": str(course.id), "language": language},
            user_id=user.id,
            world_id=course.world_id,
            cost=cost,
        )
        pending = created.id
    return PlacementStartOut(
        course_id=course.id, cached=False, cost=cost, job_id=pending, questions=None
    )


@router.get("/{course_id}", response_model=QuestionsOut)
async def questions(course_id: uuid.UUID, s: Session, user: CurrentUser) -> dict[str, Any]:
    course = await _course(s, user, course_id)
    placement = await service.find_set(course.id, user.ui_language)
    if placement is None:
        raise HTTPException(404, "errors.placement_not_ready")
    return {"course_id": str(course.id), "questions": service.redact(placement.questions)}


@router.post("/finish", response_model=service.Graded)
async def finish(body: FinishIn, s: Session, user: CurrentUser) -> service.Graded:
    course = await _course(s, user, body.course_id)
    placement = await service.find_set(course.id, user.ui_language)
    if placement is None:
        raise HTTPException(404, "errors.placement_not_ready")
    if len(body.answers) != len(placement.questions):
        raise HTTPException(400, "errors.placement_incomplete")
    return await service.grade(user.id, course.id, placement, body.answers)
