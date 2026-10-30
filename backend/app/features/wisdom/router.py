"""Class Wisdom API: anonymous tips for the loading screens and Quiz Hall."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session
from app.features.wisdom import service
from app.features.worlds.service import NotFound, member_world

router = APIRouter(prefix="/api/wisdom", tags=["wisdom"])


class Tip(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    concept: str
    mistake_type: str
    language: str
    trap: str
    why: str
    right: str
    student_count: int


class Tips(BaseModel):
    tips: list[Tip]


@router.get("", response_model=Tips)
async def tips(
    world_id: uuid.UUID, s: Session, user: CurrentUser, course_id: uuid.UUID | None = None
) -> Tips:
    try:
        await member_world(s, user, world_id)
    except NotFound as e:
        raise HTTPException(404, e.key) from e
    rows = await service.tips_for(s, world_id, user.ui_language, course_id)
    return Tips(
        tips=[
            Tip(
                id=t.id,
                course_id=t.course_id,
                concept=t.concept,
                mistake_type=t.mistake_type,
                language=t.language,
                student_count=t.student_count,
                **t.text,
            )
            for t in rows
        ]
    )
