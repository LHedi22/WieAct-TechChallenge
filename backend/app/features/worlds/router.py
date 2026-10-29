"""Worlds API: create / join, courses and chapters, uploads, the indexing screen."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Response, UploadFile
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.features.worlds import service
from app.features.worlds.schemas import (
    ChapterIn,
    ChapterOut,
    CourseIn,
    CourseOut,
    DocumentOut,
    IndexingOut,
    JoinIn,
    UploadOut,
    WorldIn,
    WorldOut,
    WorldSummary,
)
from app.features.worlds.service import NotFound, Rejected
from app.models import Chapter, Course, Document, World, WorldMember

router = APIRouter(prefix="/api", tags=["worlds"])
READ_CHUNK = 1024 * 1024


def _http(e: NotFound | Rejected) -> HTTPException:
    if isinstance(e, NotFound):
        return HTTPException(404, e.key)
    return HTTPException(413 if e.key == "errors.file_too_large" else 400, e.key)


async def _world_out(s, user, world: World) -> WorldOut:
    tree = await service.world_tree(s, world)
    return WorldOut(
        id=world.id,
        name=world.name,
        join_code=world.join_code,
        is_creator=world.creator_id == user.id,
        members=tree["members"],
        courses=[
            CourseOut(
                id=c["course"].id,
                name=c["course"].name,
                color_key=c["course"].color_key,
                exam_date=c["course"].exam_date,
                chapters=[
                    ChapterOut(
                        id=ch["chapter"].id,
                        idx=ch["chapter"].idx,
                        title=ch["chapter"].title,
                        documents=[DocumentOut.model_validate(d) for d in ch["documents"]],
                    )
                    for ch in c["chapters"]
                ],
            )
            for c in tree["courses"]
        ],
    )


async def _course(s, user, course_id: uuid.UUID) -> Course:
    course = await s.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "errors.world_not_found")
    try:
        await service.member_world(s, user, course.world_id)
    except NotFound as e:
        raise _http(e) from e
    return course


@router.get("/worlds", response_model=list[WorldSummary])
async def my_worlds(s: Session, user: CurrentUser) -> list[WorldSummary]:
    rows = await s.scalars(
        select(World)
        .join(WorldMember, WorldMember.world_id == World.id)
        .where(WorldMember.user_id == user.id)
        .order_by(WorldMember.joined_at.desc())
    )
    return [WorldSummary(id=w.id, name=w.name, join_code=w.join_code) for w in rows]


@router.post("/worlds", response_model=WorldOut, status_code=201)
async def create_world(body: WorldIn, s: Session, user: CurrentUser) -> WorldOut:
    try:
        world = await service.create_world(s, user, body.name)
    except Rejected as e:
        raise _http(e) from e
    return await _world_out(s, user, world)


@router.post("/worlds/join", response_model=WorldOut)
async def join_world(body: JoinIn, s: Session, user: CurrentUser) -> WorldOut:
    try:
        world = await service.join_world(s, user, body.code)
    except NotFound as e:
        raise _http(e) from e
    return await _world_out(s, user, world)


@router.get("/worlds/{world_id}", response_model=WorldOut)
async def get_world(world_id: uuid.UUID, s: Session, user: CurrentUser) -> WorldOut:
    try:
        world = await service.member_world(s, user, world_id)
    except NotFound as e:
        raise _http(e) from e
    return await _world_out(s, user, world)


@router.post("/worlds/{world_id}/courses", response_model=CourseOut, status_code=201)
async def add_course(world_id: uuid.UUID, body: CourseIn, s: Session, user: CurrentUser):
    try:
        world = await service.member_world(s, user, world_id)
    except NotFound as e:
        raise _http(e) from e
    course = await service.add_course(s, world, body.name, body.chapters, body.exam_date)
    tree = await service.world_tree(s, world)
    entry = next(c for c in tree["courses"] if c["course"].id == course.id)
    return CourseOut(
        id=course.id,
        name=course.name,
        color_key=course.color_key,
        exam_date=course.exam_date,
        chapters=[
            ChapterOut(id=ch["chapter"].id, idx=ch["chapter"].idx, title=ch["chapter"].title)
            for ch in entry["chapters"]
        ],
    )


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID, s: Session, user: CurrentUser) -> Response:
    course = await _course(s, user, course_id)
    docs = await s.scalars(
        select(Document)
        .join(Chapter, Chapter.id == Document.chapter_id)
        .where(Chapter.course_id == course.id)
    )
    for doc in list(docs):  # vectors and stored files go too; rows cascade with the course
        await service.remove_document(s, doc)
    await s.delete(course)
    await s.commit()
    return Response(status_code=204)


@router.post("/courses/{course_id}/chapters", response_model=ChapterOut, status_code=201)
async def add_chapter(course_id: uuid.UUID, body: ChapterIn, s: Session, user: CurrentUser):
    course = await _course(s, user, course_id)
    chapter = await service.add_chapter(s, course, body.title)
    return ChapterOut(id=chapter.id, idx=chapter.idx, title=chapter.title)


@router.post("/chapters/{chapter_id}/documents", response_model=UploadOut, status_code=202)
async def upload_document(
    chapter_id: uuid.UUID, file: UploadFile, s: Session, user: CurrentUser
) -> UploadOut:
    """One file per request (the UI uploads several in parallel and shows each one's state).
    Indexing runs as a background job; poll GET /api/worlds/{id}/indexing."""
    try:
        chapter = await service.member_chapter(s, user, chapter_id)
    except NotFound as e:
        raise _http(e) from e

    async def parts() -> AsyncIterator[bytes]:
        while chunk := await file.read(READ_CHUNK):
            yield chunk

    try:
        doc, job_id, reused = await service.store_upload(
            s, user, chapter, file.filename or "upload", parts()
        )
    except Rejected as e:
        raise _http(e) from e
    return UploadOut(document=DocumentOut.model_validate(doc), job_id=job_id, reused=reused)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, s: Session, user: CurrentUser) -> Response:
    doc = await s.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "errors.document_not_found")
    try:
        await service.member_world(s, user, doc.world_id)
    except NotFound as e:
        raise _http(e) from e
    await service.remove_document(s, doc)
    return Response(status_code=204)


@router.get("/worlds/{world_id}/indexing", response_model=IndexingOut)
async def indexing(world_id: uuid.UUID, s: Session, user: CurrentUser) -> IndexingOut:
    """Polled every 1.5 s by the "Raising your islands" screen."""
    try:
        world = await service.member_world(s, user, world_id)
    except NotFound as e:
        raise _http(e) from e
    return IndexingOut.model_validate(await service.indexing_view(s, world))
