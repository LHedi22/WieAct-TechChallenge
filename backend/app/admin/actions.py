"""Admin changes to users, worlds, course material, jobs, the cache, content and the arena.

Every action writes an admin_actions row in the same transaction and validates with the app's own
rules (nickname pattern, password length, the generated-content schemas). Destructive actions are
two steps: `POST …/dry-run` returns the counts that would go and the text to type, then `DELETE`
with `confirm` equal to that text. Deleted documents leave every provider's Qdrant collection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import audit
from app.admin.auth import AdminActionDep
from app.admin.browse import CONTENT, content_body
from app.api.deps import NICKNAME, Session
from app.core.security import MIN_PASSWORD, hash_password
from app.core.wallet_rules import tunis_day
from app.features.arena.service import pay_good_answer
from app.features.audio.service import valid_script
from app.features.daily import service as daily
from app.features.placement.service import PlacementQuestion
from app.features.quiz.pool import Question
from app.features.studio.pack import Card, valid_map, valid_notes
from app.features.wisdom.service import TipText
from app.features.worlds.service import new_join_code, upload_root
from app.jobs.coins import coins
from app.jobs.service import create_job
from app.models import (
    AICache,
    Chapter,
    ChapterMastery,
    ClassPoolLedger,
    CoinLedger,
    Course,
    CourseLevel,
    DailyState,
    Document,
    Flashcard,
    Job,
    PeerAnswer,
    PeerQuestion,
    PointsLedger,
    Profile,
    QuizAttempt,
    QuizSet,
    StudyAsset,
    TutorSession,
    User,
    WisdomTip,
    World,
    WorldMember,
)
from app.rag.indexing import KIND as INDEX_KIND

log = logging.getLogger("admin")
router = APIRouter()
Reason = Field(min_length=3, max_length=500)
OptionalReason = Field(None, max_length=500)


async def _get(s: AsyncSession, model, item_id: uuid.UUID, *, lock: bool = False):
    row = await s.get(model, item_id, with_for_update=lock)
    if row is None:
        raise HTTPException(404, "Not Found")
    return row


async def _count(s: AsyncSession, model, *where) -> int:
    return int(await s.scalar(select(func.count()).select_from(model).where(*where)) or 0)


# --- users ---------------------------------------------------------------------------------------
class UserEdit(BaseModel):
    nickname: str | None = Field(None, min_length=3, max_length=32)
    ui_language: Literal["en", "fr", "ar", "ar-TN"] | None = None
    leaderboard_opt_in: bool | None = None
    reason: str | None = OptionalReason


@router.patch("/users/{user_id}")
async def edit_user(user_id: uuid.UUID, body: UserEdit, admin: AdminActionDep, s: Session):
    user = await _get(s, User, user_id, lock=True)
    profile = await s.get(Profile, user_id)
    before = {
        "nickname": user.nickname,
        "ui_language": user.ui_language,
        "leaderboard_opt_in": profile.leaderboard_opt_in if profile else None,
    }
    if body.nickname is not None:
        nickname = body.nickname.strip()
        if not NICKNAME.match(nickname):  # the sign-up rule
            raise HTTPException(422, "Nicknames are 3-32 letters, digits, _ or -")
        taken = await s.scalar(select(User.id).where(User.nickname == nickname, User.id != user_id))
        if taken:
            raise HTTPException(409, "That nickname is taken")
        user.nickname = nickname
    if body.ui_language is not None:
        user.ui_language = body.ui_language
    if body.leaderboard_opt_in is not None:
        if profile is None:
            raise HTTPException(422, "This student has no profile yet (onboarding not finished)")
        profile.leaderboard_opt_in = body.leaderboard_opt_in
    after = {
        "nickname": user.nickname,
        "ui_language": user.ui_language,
        "leaderboard_opt_in": profile.leaderboard_opt_in if profile else None,
    }
    audit.record(
        s,
        admin,
        "user.edit",
        target_kind="user",
        target_id=user_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    await s.commit()
    return after


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    reason: str | None = OptionalReason


@router.post("/users/{user_id}/password", status_code=204)
async def reset_password(user_id: uuid.UUID, body: PasswordIn, admin: AdminActionDep, s: Session):
    """The admin sets a new password (the old hash is never shown); every session ends."""
    user = await _get(s, User, user_id, lock=True)
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(422, f"Passwords need at least {MIN_PASSWORD} characters")
    user.password_hash = hash_password(body.password)
    user.session_epoch += 1
    audit.record(
        s, admin, "user.password_reset", target_kind="user", target_id=user_id, reason=body.reason
    )
    await s.commit()


class ReasonIn(BaseModel):
    reason: str | None = OptionalReason


@router.post("/users/{user_id}/sign-out")
async def sign_out_everywhere(
    user_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session
):
    user = await _get(s, User, user_id, lock=True)
    before = user.session_epoch
    user.session_epoch += 1  # every cookie signed for an older epoch is refused
    audit.record(
        s,
        admin,
        "user.sign_out_everywhere",
        target_kind="user",
        target_id=user_id,
        before={"session_epoch": before},
        after={"session_epoch": before + 1},
        reason=body.reason,
    )
    await s.commit()
    return {"session_epoch": user.session_epoch}


class ResetCourseIn(BaseModel):
    course_id: uuid.UUID
    dry_run: bool = True
    reason: str | None = OptionalReason


@router.post("/users/{user_id}/reset-course")
async def reset_course(user_id: uuid.UUID, body: ResetCourseIn, admin: AdminActionDep, s: Session):
    """Level, chapter mastery and today's daily state for one course (quiz history, ledgers and
    points stay: they are the record of what happened)."""
    await _get(s, User, user_id)
    course = await _get(s, Course, body.course_id)
    chapters = select(Chapter.id).where(Chapter.course_id == course.id)
    where = {
        "course_levels": (
            CourseLevel,
            CourseLevel.user_id == user_id,
            CourseLevel.course_id == course.id,
        ),
        "chapter_mastery": (
            ChapterMastery,
            ChapterMastery.user_id == user_id,
            ChapterMastery.chapter_id.in_(chapters),
        ),
        "daily_state_today": (
            DailyState,
            DailyState.user_id == user_id,
            DailyState.date == tunis_day(),
        ),
    }
    counts = {k: await _count(s, m, *w) for k, (m, *w) in where.items()}
    if body.dry_run:
        return {"dry_run": True, "counts": counts, "course": course.name}
    if not (body.reason or "").strip():
        raise HTTPException(422, "A reason is required")
    for model, *w in where.values():
        await s.execute(delete(model).where(*w))
    audit.record(
        s,
        admin,
        "user.reset_course",
        target_kind="user",
        target_id=user_id,
        before=counts,
        after={"course_id": course.id},
        reason=body.reason,
    )
    await s.commit()
    return {"dry_run": False, "counts": counts, "course": course.name}


# --- worlds, courses, chapters -------------------------------------------------------------------
class WorldEdit(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    regenerate_join_code: bool = False
    reason: str | None = OptionalReason


@router.patch("/worlds/{world_id}")
async def edit_world(world_id: uuid.UUID, body: WorldEdit, admin: AdminActionDep, s: Session):
    world = await _get(s, World, world_id, lock=True)
    before = {"name": world.name, "join_code": world.join_code}
    if body.name is not None:
        world.name = body.name.strip()
    if body.regenerate_join_code:
        for _ in range(10):
            code = new_join_code()
            if not await s.scalar(select(World.id).where(World.join_code == code)):
                world.join_code = code
                break
        else:
            raise HTTPException(503, "Could not find a free join code; try again")
    after = {"name": world.name, "join_code": world.join_code}
    audit.record(
        s,
        admin,
        "world.edit",
        target_kind="world",
        target_id=world_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    await s.commit()
    return after


@router.delete("/worlds/{world_id}/members/{user_id}")
async def remove_member(
    world_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: AdminActionDep,
    s: Session,
    body: ReasonIn | None = None,
):
    reason = body.reason if body else None
    world = await _get(s, World, world_id)
    if world.creator_id == user_id:
        raise HTTPException(409, "The creator can't be removed; delete the world instead")
    res = await s.execute(
        delete(WorldMember).where(WorldMember.world_id == world_id, WorldMember.user_id == user_id)
    )
    if res.rowcount == 0:
        raise HTTPException(404, "Not a member")
    audit.record(
        s,
        admin,
        "world.remove_member",
        target_kind="world",
        target_id=world_id,
        before={"user_id": user_id},
        reason=reason or None,
    )
    await s.commit()
    return {"removed": str(user_id)}


class CourseEdit(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    exam_date: date | None = None
    clear_exam_date: bool = False
    reason: str | None = OptionalReason


@router.patch("/courses/{course_id}")
async def edit_course(course_id: uuid.UUID, body: CourseEdit, admin: AdminActionDep, s: Session):
    course = await _get(s, Course, course_id, lock=True)
    before = {"name": course.name, "exam_date": course.exam_date}
    if body.name is not None:
        course.name = body.name.strip()
    if body.clear_exam_date:
        course.exam_date = None
    elif body.exam_date is not None:
        course.exam_date = body.exam_date
    after = {"name": course.name, "exam_date": course.exam_date}
    audit.record(
        s,
        admin,
        "course.edit",
        target_kind="course",
        target_id=course_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    await s.commit()
    return after


class ChapterEdit(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    reason: str | None = OptionalReason


@router.patch("/chapters/{chapter_id}")
async def edit_chapter(chapter_id: uuid.UUID, body: ChapterEdit, admin: AdminActionDep, s: Session):
    chapter = await _get(s, Chapter, chapter_id, lock=True)
    before = {"title": chapter.title}
    chapter.title = body.title.strip()
    audit.record(
        s,
        admin,
        "chapter.edit",
        target_kind="chapter",
        target_id=chapter_id,
        before=before,
        after={"title": chapter.title},
        reason=body.reason,
    )
    await s.commit()
    return {"title": chapter.title}


# --- re-index ------------------------------------------------------------------------------------
async def _reindex(s: AsyncSession, doc: Document) -> uuid.UUID:
    if not (upload_root() / doc.storage_path).exists():
        raise HTTPException(409, f"{doc.filename}: the uploaded file is gone; upload it again")
    busy = await s.scalar(
        select(Job.id).where(
            Job.kind == INDEX_KIND,
            Job.status.in_(("queued", "running")),
            Job.payload["document_id"].astext == str(doc.id),
        )
    )
    if busy:
        return busy
    doc.status, doc.progress, doc.error, doc.detail = "uploaded", 0, None, None
    # A background job like any upload: offline, it waits for the next slot
    job = await create_job(
        s,
        kind=INDEX_KIND,
        lane="background",
        payload={"document_id": str(doc.id)},
        world_id=doc.world_id,
    )
    return job.id


@router.post("/documents/{document_id}/reindex")
async def reindex_document(
    document_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session
):
    doc = await _get(s, Document, document_id, lock=True)
    job_id = await _reindex(s, doc)
    audit.record(
        s,
        admin,
        "document.reindex",
        target_kind="document",
        target_id=document_id,
        after={"job_id": job_id},
        reason=body.reason,
    )
    await s.commit()
    return {"jobs": [str(job_id)]}


@router.post("/chapters/{chapter_id}/reindex")
async def reindex_chapter(chapter_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session):
    await _get(s, Chapter, chapter_id)
    docs = list(
        await s.scalars(select(Document).where(Document.chapter_id == chapter_id).with_for_update())
    )
    jobs = [await _reindex(s, d) for d in docs]
    audit.record(
        s,
        admin,
        "chapter.reindex",
        target_kind="chapter",
        target_id=chapter_id,
        after={"jobs": jobs},
        reason=body.reason,
    )
    await s.commit()
    return {"jobs": [str(j) for j in jobs]}


# --- deletes: dry run, then a typed confirm ------------------------------------------------------
Kind = Literal["user", "world", "course", "chapter", "document"]


async def _target(s: AsyncSession, kind: Kind, item_id: uuid.UUID):
    model = {
        "user": User,
        "world": World,
        "course": Course,
        "chapter": Chapter,
        "document": Document,
    }[kind]
    row = await _get(s, model, item_id)
    name = {
        "user": lambda r: r.nickname,
        "world": lambda r: r.name,
        "course": lambda r: r.name,
        "chapter": lambda r: r.title,
        "document": lambda r: r.filename,
    }[kind](row)
    return row, name


def _doc_filter(kind: Kind, item_id: uuid.UUID):
    if kind == "world":
        return Document.world_id == item_id
    if kind == "course":
        return Document.chapter_id.in_(select(Chapter.id).where(Chapter.course_id == item_id))
    if kind == "chapter":
        return Document.chapter_id == item_id
    return Document.id == item_id


async def _impact(s: AsyncSession, kind: Kind, item_id: uuid.UUID) -> dict[str, Any]:
    if kind == "user":
        created = list(await s.scalars(select(World).where(World.creator_id == item_id)))
        transfers, blocked = [], []
        for w in created:
            heir = await s.scalar(
                select(WorldMember.user_id)
                .where(WorldMember.world_id == w.id, WorldMember.user_id != item_id)
                .order_by(WorldMember.joined_at)
                .limit(1)
            )
            (transfers if heir else blocked).append(
                {"world_id": w.id, "world": w.name, "new_creator": heir}
            )
        return {
            "counts": {
                "coin_ledger_rows": await _count(s, CoinLedger, CoinLedger.user_id == item_id),
                "points_ledger_rows": await _count(
                    s, PointsLedger, PointsLedger.user_id == item_id
                ),
                "memberships": await _count(s, WorldMember, WorldMember.user_id == item_id),
                "quiz_attempts": await _count(s, QuizAttempt, QuizAttempt.user_id == item_id),
                "tutor_sessions": await _count(s, TutorSession, TutorSession.user_id == item_id),
                "peer_questions": await _count(s, PeerQuestion, PeerQuestion.author_id == item_id),
                "peer_answers": await _count(s, PeerAnswer, PeerAnswer.author_id == item_id),
                "jobs_kept_anonymous": await _count(s, Job, Job.user_id == item_id),
                "pool_rows_kept_anonymous": await _count(
                    s, ClassPoolLedger, ClassPoolLedger.user_id == item_id
                ),
            },
            "worlds_transferred": transfers,
            "blocked_by": blocked,  # worlds with no other member: delete those first
            "documents": 0,
        }
    docs = _doc_filter(kind, item_id)
    counts: dict[str, int] = {"documents": await _count(s, Document, docs)}
    if kind in ("world", "course", "chapter"):
        chapters = (
            select(Chapter.id).where(Chapter.id == item_id)
            if kind == "chapter"
            else select(Chapter.id)
            .join(Course, Course.id == Chapter.course_id)
            .where(Course.world_id == item_id if kind == "world" else Course.id == item_id)
        )
        counts |= {
            "chapters": await _count(s, Chapter, Chapter.id.in_(chapters)),
            "quiz_sets": await _count(s, QuizSet, QuizSet.chapter_id.in_(chapters)),
            "quiz_attempts": await _count(s, QuizAttempt, QuizAttempt.chapter_id.in_(chapters)),
            "study_assets": await _count(s, StudyAsset, StudyAsset.chapter_id.in_(chapters)),
            "flashcards": await _count(s, Flashcard, Flashcard.chapter_id.in_(chapters)),
            "peer_questions": await _count(s, PeerQuestion, PeerQuestion.chapter_id.in_(chapters)),
            "tutor_sessions": await _count(s, TutorSession, TutorSession.chapter_id.in_(chapters)),
        }
    if kind == "world":
        counts |= {
            "members": await _count(s, WorldMember, WorldMember.world_id == item_id),
            "courses": await _count(s, Course, Course.world_id == item_id),
            "points_ledger_rows": await _count(s, PointsLedger, PointsLedger.world_id == item_id),
            "class_pool_rows": await _count(
                s, ClassPoolLedger, ClassPoolLedger.world_id == item_id
            ),
            "wisdom_tips": await _count(s, WisdomTip, WisdomTip.world_id == item_id),
            "jobs": await _count(s, Job, Job.world_id == item_id),
        }
    return {"counts": counts, "blocked_by": [], "documents": counts["documents"]}


@router.post("/delete/{kind}/{item_id}/dry-run")
async def delete_dry_run(kind: Kind, item_id: uuid.UUID, _: AdminActionDep, s: Session):
    _, name = await _target(s, kind, item_id)
    return {"kind": kind, "id": item_id, "confirm_text": name, **await _impact(s, kind, item_id)}


class DeleteIn(BaseModel):
    confirm: str
    reason: str = Reason


@router.delete("/delete/{kind}/{item_id}")
async def delete_item(
    kind: Kind, item_id: uuid.UUID, body: DeleteIn, admin: AdminActionDep, s: Session
):
    row, name = await _target(s, kind, item_id)
    if body.confirm != name:
        raise HTTPException(422, "Type the exact name to confirm")
    impact = await _impact(s, kind, item_id)
    if impact["blocked_by"]:
        raise HTTPException(
            409,
            "Delete or hand over these worlds first: "
            + ", ".join(b["world"] for b in impact["blocked_by"]),
        )
    docs = list(await s.scalars(select(Document).where(_doc_filter(kind, item_id))))
    doc_ids, files = [d.id for d in docs], [d.storage_path for d in docs]
    if kind == "user":
        for t in impact["worlds_transferred"]:
            await s.execute(
                update(World).where(World.id == t["world_id"]).values(creator_id=t["new_creator"])
            )
        # Ledger rows go with the student (CASCADE); pool contributions stay, anonymised (SET NULL)
    audit.record(
        s,
        admin,
        f"{kind}.delete",
        target_kind=kind,
        target_id=item_id,
        before={"name": name, **impact},
        reason=body.reason,
    )
    await s.delete(row)
    await s.commit()
    cleanup = await _cleanup(doc_ids, files)
    return {"deleted": kind, "name": name, "counts": impact["counts"], **cleanup}


async def _cleanup(doc_ids: list[uuid.UUID], files: list[str]) -> dict[str, Any]:
    """After the commit: vectors in every provider's collection, then the uploaded files."""
    from app.rag import store  # noqa: PLC0415

    failed: list[str] = []
    for doc_id in doc_ids:
        try:
            await store.delete_document_everywhere(doc_id)
        except Exception:  # the rows are gone; report it so the admin can retry by reindexing
            log.exception("Qdrant cleanup failed for document %s", doc_id)
            failed.append(str(doc_id))
    for path in files:
        try:
            (upload_root() / path).unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove upload %s", path)
    return {"vectors_deleted_for": len(doc_ids) - len(failed), "vector_cleanup_failed": failed}


# --- jobs ----------------------------------------------------------------------------------------
@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session):
    """Queued or running → cancelled, refunded exactly once (refunds are unique per job). A worker
    still running it can't save a result afterwards (its final update needs the job running)."""
    job = await _get(s, Job, job_id, lock=True)
    if job.status not in ("queued", "running"):
        raise HTTPException(409, f"The job is {job.status}")
    before = job.status
    job.status, job.finished_at, job.error = "cancelled", datetime.now(UTC), "errors.job_cancelled"
    job.lease_until, job.worker_id = None, None
    await coins.refund(s, job)
    doc_id = (job.payload or {}).get("document_id")
    if job.kind == INDEX_KIND and doc_id:
        await s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(doc_id), Document.status != "ready")
            .values(status="failed", error="errors.indexing_failed", detail=None)
        )
    audit.record(
        s,
        admin,
        "job.cancel",
        target_kind="job",
        target_id=job_id,
        before={"status": before},
        after={"status": "cancelled"},
        reason=body.reason,
    )
    await s.commit()
    return {"status": "cancelled"}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session):
    """A failed or cancelled job goes back in the queue. Its coins were refunded when it failed,
    so the retry is free for the student (a later failure refunds nothing twice)."""
    job = await _get(s, Job, job_id, lock=True)
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(
            409, f"Only failed or cancelled jobs can be retried (it is {job.status})"
        )
    before = {"status": job.status, "error": job.error, "attempts": job.attempts}
    job.status, job.error, job.attempts = "queued", None, 0
    job.not_before = job.finished_at = job.started_at = None
    job.lease_until, job.worker_id, job.stage = None, None, None
    audit.record(
        s,
        admin,
        "job.retry",
        target_kind="job",
        target_id=job_id,
        before=before,
        after={"status": "queued"},
        reason=body.reason,
    )
    await s.commit()
    return {"status": "queued"}


@router.post("/jobs/{job_id}/run-now")
async def run_now(job_id: uuid.UUID, body: ReasonIn, admin: AdminActionDep, s: Session):
    job = await _get(s, Job, job_id, lock=True)
    if job.status != "queued":
        raise HTTPException(409, f"The job is {job.status}")
    if (job.error or "") in ("deferred:quota", "deferred:offline"):
        # the error contract: wait the delay the platform stated (or the next slot)
        raise HTTPException(409, "This job waits for the platform's quota delay or the next slot")
    before = job.not_before
    job.not_before = None
    audit.record(
        s,
        admin,
        "job.run_now",
        target_kind="job",
        target_id=job_id,
        before={"not_before": before},
        after={"not_before": None},
        reason=body.reason,
    )
    await s.commit()
    return {"not_before": None}


# --- cache ---------------------------------------------------------------------------------------
CLOUD_PURGE_CONFIRM = "purge cloud entries"


class PurgeIn(BaseModel):
    key: str | None = None
    task_kind: str | None = None
    provider: Literal["cloud", "local", "mock"] | None = None
    dry_run: bool = True
    reason: str | None = OptionalReason
    confirm: str | None = None  # CLOUD_PURGE_CONFIRM, required when platform entries would go


@router.post("/cache/purge")
async def purge_cache(body: PurgeIn, admin: AdminActionDep, s: Session):
    """By key or by task kind (optionally one provider). Keys are hashes of the full request, so
    there is no purge "by chapter"; a chapter's shared outputs are edited from Content instead."""
    if not body.key and not body.task_kind:
        raise HTTPException(422, "Give a key or a task kind")
    where = []
    if body.key:
        where.append(AICache.key == body.key)
    if body.task_kind:
        where.append(AICache.task_kind == body.task_kind)
    if body.provider:
        where.append(AICache.provider == body.provider)
    n = await _count(s, AICache, *where)
    cloud = await _count(s, AICache, *where, AICache.provider == "cloud")
    warning = (
        f"{cloud} entries were made on the platform: the next identical request becomes a "
        "real call, counted as a repeated identical request in the organisers' metrics."
        if cloud
        else None
    )
    if body.dry_run:
        return {
            "dry_run": True,
            "entries": n,
            "cloud_entries": cloud,
            "warning": warning,
            "confirm_text": CLOUD_PURGE_CONFIRM if cloud else None,
        }
    if not (body.reason or "").strip():
        raise HTTPException(422, "A reason is required")
    if cloud and body.confirm != CLOUD_PURGE_CONFIRM:
        raise HTTPException(422, f'Type "{CLOUD_PURGE_CONFIRM}" to purge platform entries')
    await s.execute(delete(AICache).where(*where))
    audit.record(
        s,
        admin,
        "cache.purge",
        target_kind="cache",
        target_id=body.key or body.task_kind,
        before={"entries": n, "cloud_entries": cloud},
        after={"key": body.key, "task_kind": body.task_kind, "provider": body.provider},
        reason=body.reason,
    )
    await s.commit()
    return {"dry_run": False, "entries": n, "cloud_entries": cloud, "warning": warning}


# --- generated content ---------------------------------------------------------------------------
class ContentEdit(BaseModel):
    body: Any
    reason: str = Reason


def _questions(model, body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, list) or not body:
        raise ValueError("a non-empty list of questions")
    return [{**q, **model.model_validate(q).model_dump()} for q in body]


def _validated(kind: str, row: Any, body: Any) -> Any:
    """The app's own schemas; anything they would drop is refused rather than silently lost."""
    try:
        if kind == "quiz_sets":
            return _questions(Question, body)
        if kind == "placement_sets":
            return _questions(PlacementQuestion, body)
        if kind == "wisdom_tips":
            return TipText.model_validate(body).model_dump()
        if kind == "flashcards":
            return Card.model_validate(body).model_dump()
        check = {"notes": valid_notes, "map": valid_map, "audio_script": valid_script}[row.kind]
        clean = check(body)
        if clean is None:
            raise ValueError(f"not a usable {row.kind}")
        return clean
    except (ValidationError, ValueError, TypeError) as e:
        raise HTTPException(422, f"Invalid {kind}: {e}") from e


@router.put("/content/{kind}/{item_id}")
async def edit_content(
    kind: Literal["quiz_sets", "study_assets", "wisdom_tips", "placement_sets", "flashcards"],
    item_id: uuid.UUID,
    body: ContentEdit,
    admin: AdminActionDep,
    s: Session,
):
    row = await _get(s, CONTENT[kind], item_id, lock=True)
    before = content_body(kind, row)
    clean = _validated(kind, row, body.body)
    if kind in ("quiz_sets", "placement_sets"):
        row.questions = clean
    elif kind == "study_assets":
        row.content = clean
    elif kind == "wisdom_tips":
        row.text = clean
    else:
        row.front, row.back, row.concept = clean["front"], clean["back"], clean["concept"] or None
    row.edited_by_admin = True
    audit.record(
        s,
        admin,
        "content.edit",
        target_kind="content",
        target_id=item_id,
        before={"kind": kind, "body": before},
        after={"kind": kind, "body": clean},
        reason=body.reason,
    )
    await s.commit()
    return {"id": item_id, "edited_by_admin": True, "body": clean}


# --- arena moderation ----------------------------------------------------------------------------
async def _ask_job(s: AsyncSession, q: PeerQuestion) -> Job | None:
    return await s.scalar(
        select(Job).where(Job.kind == "ARENA_ASK", Job.payload["question_id"].astext == str(q.id))
    )


class ModerateIn(BaseModel):
    action: Literal["reject", "restore", "unpin"]
    reason: str = Reason


@router.post("/arena/questions/{question_id}")
async def moderate_question(
    question_id: uuid.UUID, body: ModerateIn, admin: AdminActionDep, s: Session
):
    q = await _get(s, PeerQuestion, question_id, lock=True)
    before = {
        "status": q.status,
        "reject_reason": q.reject_reason,
        "pinned_answer_id": q.pinned_answer_id,
    }
    if body.action == "reject":
        if q.status == "rejected":
            raise HTTPException(409, "Already rejected")
        q.status, q.reject_reason = "rejected", "admin"
        if (job := await _ask_job(s, q)) is not None:
            await coins.refund(
                s, job
            )  # the asking cost comes back, once (as when moderation rejects)
    elif body.action == "restore":
        if q.status != "rejected":
            raise HTTPException(409, "Only a rejected question can be restored")
        q.status, q.reject_reason = "open", None  # the refunded cost is not charged again
    else:
        if q.pinned_answer_id is None:
            raise HTTPException(409, "No pinned answer")
        q.pinned_answer_id = None  # the pin's points stay (they were awarded for a real event)
    after = {
        "status": q.status,
        "reject_reason": q.reject_reason,
        "pinned_answer_id": q.pinned_answer_id,
    }
    audit.record(
        s,
        admin,
        f"question.{body.action}",
        target_kind="question",
        target_id=question_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    await s.commit()
    return after


class AnswerModerateIn(BaseModel):
    action: Literal["reject", "restore", "score"]
    score: int | None = Field(None, ge=0, le=100)
    reason: str = Reason


@router.post("/arena/answers/{answer_id}")
async def moderate_answer(
    answer_id: uuid.UUID, body: AnswerModerateIn, admin: AdminActionDep, s: Session
):
    a = await _get(s, PeerAnswer, answer_id, lock=True)
    q = await _get(s, PeerQuestion, a.question_id)
    before = {"status": a.status, "ai_score": a.ai_score, "rewarded": a.rewarded}
    earned = 0
    if body.action == "reject":
        if a.status == "rejected":
            raise HTTPException(409, "Already rejected")
        a.status = "rejected"  # coins already paid stay; remove them from Users if needed
        if q.pinned_answer_id == a.id:
            q.pinned_answer_id = None
    elif body.action == "restore":
        if a.status != "rejected":
            raise HTTPException(409, "Only a rejected answer can be restored")
        a.status = "graded" if a.ai_score is not None else "failed"
        earned = await pay_good_answer(s, a, q)
    else:
        if a.status != "pending_review":
            raise HTTPException(409, "Only an answer waiting for review can be scored by hand")
        if body.score is None:
            raise HTTPException(422, "Give a score from 0 to 100")
        a.ai_score, a.ai_confidence, a.status = body.score, "admin", "graded"
        a.updated_at = datetime.now(UTC)
        earned = await pay_good_answer(s, a, q)  # once, through the normal path
        await daily.record(s, a.author_id, "teachback", chapter_id=q.chapter_id)
    after = {
        "status": a.status,
        "ai_score": a.ai_score,
        "rewarded": a.rewarded,
        "coins_earned": earned,
    }
    audit.record(
        s,
        admin,
        f"answer.{body.action}",
        target_kind="answer",
        target_id=answer_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    await s.commit()
    return after
