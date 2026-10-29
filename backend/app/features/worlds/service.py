"""Worlds: create, join by code, courses + chapters, uploads, the indexing rollup.

A world is one class's shared archipelago; every route checks membership and answers 404 to
non-members (never revealing that a world exists)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.jobs.service import _avg_call_s, create_job
from app.models import Chapter, Course, Document, Job, QuizSet, User, World, WorldMember
from app.rag.indexing import KIND as INDEX_KIND
from app.rag.parsing import kind_for

# Join codes look like OLIVE-7Q2: a Mediterranean word + 3 characters nobody misreads.
CODE_WORDS = [
    "OLIVE",
    "CORAL",
    "PEARL",
    "CEDAR",
    "AMBER",
    "LEMON",
    "WAVES",
    "CLIFF",
    "DELTA",
    "AZURE",
    "ISLET",
    "REEFS",
    "SHELL",
    "THYME",
    "DATES",
    "SANDS",
    "TIDES",
    "GULLS",
    "PALMS",
    "DUNES",
]
CODE_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
ISLAND_ACCENTS = 6  # design tokens island-1 … island-6, assigned in creation order
TAG_CALLS_PER_DOC_S = 6.0  # rough per-document cost when no call history exists yet


class NotFound(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class Rejected(Exception):
    def __init__(self, key: str, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def new_join_code() -> str:
    suffix = "".join(secrets.choice(CODE_CHARS) for _ in range(3))
    return f"{secrets.choice(CODE_WORDS)}-{suffix}"


def normalise_code(raw: str) -> str:
    """'olive 7q2', 'OLIVE7Q2', 'olive-7q2' → 'OLIVE-7Q2'."""
    s = "".join(ch for ch in raw.upper() if ch.isalnum())
    return f"{s[:-3]}-{s[-3:]}" if len(s) > 3 else s


# --- worlds and membership -----------------------------------------------------------------------
async def create_world(s: AsyncSession, user: User, name: str) -> World:
    for _ in range(8):
        world = World(name=name.strip(), join_code=new_join_code(), creator_id=user.id)
        s.add(world)
        try:
            await s.flush()
        except IntegrityError:  # code collision: try another
            await s.rollback()
            continue
        s.add(WorldMember(world_id=world.id, user_id=user.id))
        await s.commit()
        return world
    raise Rejected("errors.try_again")


async def join_world(s: AsyncSession, user: User, code: str) -> World:
    world = await s.scalar(select(World).where(World.join_code == normalise_code(code)))
    if world is None:
        raise NotFound("errors.join_code_unknown")
    member = await s.get(WorldMember, (world.id, user.id))
    if member is None:
        s.add(WorldMember(world_id=world.id, user_id=user.id))
        await s.commit()
    return world


async def member_world(s: AsyncSession, user: User, world_id: uuid.UUID) -> World:
    world = await s.get(World, world_id)
    if world is None or await s.get(WorldMember, (world_id, user.id)) is None:
        raise NotFound("errors.world_not_found")
    return world


async def member_chapter(s: AsyncSession, user: User, chapter_id: uuid.UUID) -> Chapter:
    chapter = await s.get(Chapter, chapter_id)
    if chapter is None:
        raise NotFound("errors.world_not_found")
    course = await s.get(Course, chapter.course_id)
    await member_world(s, user, course.world_id)
    return chapter


# --- courses and chapters ------------------------------------------------------------------------
async def add_course(
    s: AsyncSession,
    world: World,
    name: str,
    chapters: list[str],
    exam_date: date | None = None,
) -> Course:
    n = await s.scalar(select(func.count()).select_from(Course).where(Course.world_id == world.id))
    course = Course(
        world_id=world.id,
        name=name.strip(),
        color_key=f"island-{(n or 0) % ISLAND_ACCENTS + 1}",
        exam_date=exam_date,
    )
    s.add(course)
    await s.flush()
    for i, title in enumerate(t.strip() for t in chapters if t.strip()):
        s.add(Chapter(course_id=course.id, idx=i + 1, title=title))
    await s.commit()
    return course


async def add_chapter(s: AsyncSession, course: Course, title: str) -> Chapter:
    last = await s.scalar(select(func.max(Chapter.idx)).where(Chapter.course_id == course.id))
    chapter = Chapter(course_id=course.id, idx=(last or 0) + 1, title=title.strip())
    s.add(chapter)
    await s.commit()
    return chapter


# --- uploads -------------------------------------------------------------------------------------
def upload_root() -> Path:
    root = Path(get_settings().UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def store_upload(
    s: AsyncSession,
    user: User,
    chapter: Chapter,
    filename: str,
    chunks: AsyncIterator[bytes],
) -> tuple[Document, uuid.UUID | None, bool]:
    """Stream to disk (size-checked), hash, dedupe within the chapter, queue INDEX_DOCUMENT.
    Returns (document, job_id, reused)."""
    kind = kind_for(filename)
    if kind is None:
        raise Rejected("errors.file_type")
    course = await s.get(Course, chapter.course_id)
    limit = get_settings().UPLOAD_MAX_MB * 1024 * 1024
    doc_id = uuid.uuid4()
    rel = Path(str(course.world_id)) / f"{doc_id}{Path(filename).suffix.lower()}"
    path = upload_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("wb") as f:
            async for part in chunks:
                size += len(part)
                if size > limit:
                    raise Rejected("errors.file_too_large", max_mb=get_settings().UPLOAD_MAX_MB)
                digest.update(part)
                f.write(part)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise Rejected("errors.document_empty")
    sha = digest.hexdigest()

    same = await s.scalar(
        select(Document).where(
            Document.chapter_id == chapter.id,
            Document.sha256 == sha,
            Document.status != "failed",
        )
    )
    if same is not None:  # the same file twice in a chapter: index it once
        path.unlink(missing_ok=True)
        return same, None, True

    doc = Document(
        id=doc_id,
        chapter_id=chapter.id,
        world_id=course.world_id,
        filename=Path(filename).name[:255],
        kind=kind,
        size=size,
        sha256=sha,
        storage_path=rel.as_posix(),
        status="uploaded",
        progress=0,
    )
    s.add(doc)
    await s.flush()
    job = await create_job(
        s,
        kind=INDEX_KIND,
        lane="background",
        payload={"document_id": str(doc.id)},
        user_id=user.id,
        world_id=course.world_id,
    )
    return doc, job.id, False


async def remove_document(s: AsyncSession, doc: Document) -> None:
    from app.rag.store import delete_document_everywhere  # noqa: PLC0415

    await delete_document_everywhere(doc.id)
    (upload_root() / doc.storage_path).unlink(missing_ok=True)
    await s.delete(doc)
    await s.commit()


# --- reading -------------------------------------------------------------------------------------
async def world_tree(s: AsyncSession, world: World) -> dict[str, Any]:
    courses = list(
        await s.scalars(select(Course).where(Course.world_id == world.id).order_by(Course.name))
    )
    course_ids = [c.id for c in courses]
    chapters = list(
        await s.scalars(
            select(Chapter).where(Chapter.course_id.in_(course_ids)).order_by(Chapter.idx)
        )
    )
    docs = list(
        await s.scalars(
            select(Document).where(Document.world_id == world.id).order_by(Document.created_at)
        )
    )
    members = await s.scalar(
        select(func.count()).select_from(WorldMember).where(WorldMember.world_id == world.id)
    )
    by_chapter: dict[uuid.UUID, list[Document]] = {}
    for d in docs:
        by_chapter.setdefault(d.chapter_id, []).append(d)
    by_course: dict[uuid.UUID, list[Chapter]] = {}
    for ch in chapters:
        by_course.setdefault(ch.course_id, []).append(ch)
    return {
        "world": world,
        "members": members or 0,
        "courses": [
            {
                "course": c,
                "chapters": [
                    {"chapter": ch, "documents": by_chapter.get(ch.id, [])}
                    for ch in by_course.get(c.id, [])
                ],
            }
            for c in courses
        ],
    }


async def indexing_view(s: AsyncSession, world: World) -> dict[str, Any]:
    """Rollup for the "Raising your islands" screen: per chapter, per document, overall."""
    tree = await world_tree(s, world)
    chapters_out: list[dict[str, Any]] = []
    total = done = 0
    remaining_docs = 0
    for c in tree["courses"]:
        for entry in c["chapters"]:
            docs = entry["documents"]
            if not docs:
                continue
            states = {d.status for d in docs}
            if states <= {"ready", "failed"}:
                state = "done" if "ready" in states else "failed"
            elif states & {"parsing", "tagging", "embedding"}:
                state = "in_progress"
            else:
                state = "waiting"
            total += 100 * len(docs)
            done += sum(100 if d.status in ("ready", "failed") else d.progress for d in docs)
            remaining_docs += sum(d.status not in ("ready", "failed") for d in docs)
            chapters_out.append(
                {
                    "chapter_id": entry["chapter"].id,
                    "course_id": c["course"].id,
                    "course_name": c["course"].name,
                    "idx": entry["chapter"].idx,
                    "title": entry["chapter"].title,
                    "state": state,
                    "documents": docs,
                }
            )
    pools = await s.scalar(
        select(func.count()).select_from(QuizSet).where(QuizSet.world_id == world.id)
    )
    pool_jobs = await s.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.world_id == world.id,
            Job.kind == "QUIZ_POOL",
            Job.status.in_(("queued", "running")),
        )
    )
    per_doc = 5 * await _avg_call_s(s) if remaining_docs else 0  # ~4 tag calls + 1 embed call
    return {
        "world_id": world.id,
        "join_code": world.join_code,
        "name": world.name,
        "percent": int(done * 100 / total) if total else 0,
        "eta_s": int(per_doc * remaining_docs) if remaining_docs else 0,
        "chapters": chapters_out,
        "quizzes": {
            "state": "in_progress" if pool_jobs else ("done" if pools else "waiting"),
            "ready": pools or 0,
        },
        "done": total > 0 and remaining_docs == 0,
    }
