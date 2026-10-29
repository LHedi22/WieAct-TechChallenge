from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorldIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=24)


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    chapters: list[str] = Field(default_factory=list, max_length=30)
    exam_date: date | None = None


class ChapterIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chapter_id: uuid.UUID
    filename: str
    kind: str
    size: int
    status: Literal["uploaded", "parsing", "tagging", "embedding", "ready", "failed"]
    progress: int
    detail: dict[str, Any] | None  # {"key": "page"|"slide"|…|"ideas"|"saving"|"waiting", n, of}
    page_count: int | None
    error: str | None  # i18n key
    created_at: datetime


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idx: int
    title: str
    documents: list[DocumentOut] = Field(default_factory=list)


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color_key: str
    exam_date: date | None
    chapters: list[ChapterOut] = Field(default_factory=list)


class WorldOut(BaseModel):
    id: uuid.UUID
    name: str
    join_code: str
    is_creator: bool
    members: int
    courses: list[CourseOut]


class WorldSummary(BaseModel):
    id: uuid.UUID
    name: str
    join_code: str


class UploadOut(BaseModel):
    document: DocumentOut
    job_id: uuid.UUID | None
    reused: bool  # the same file was already in this chapter: nothing to index


class IndexingChapter(BaseModel):
    chapter_id: uuid.UUID
    course_id: uuid.UUID
    course_name: str
    idx: int
    title: str
    state: Literal["waiting", "in_progress", "done", "failed"]
    documents: list[DocumentOut]


class IndexingQuizzes(BaseModel):
    state: Literal["waiting", "in_progress", "done"]
    ready: int


class IndexingOut(BaseModel):
    world_id: uuid.UUID
    name: str
    join_code: str
    percent: int
    eta_s: int
    done: bool
    chapters: list[IndexingChapter]
    quizzes: IndexingQuizzes
