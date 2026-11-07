"""Admin side, read-only: users, worlds, content, arena, jobs, cache and the admin log.

Server-side search, filters and pagination (PAGE_SIZE per page). Nothing here writes: wallets are
summed from the ledger the way the student's own wallet would show them (the day's free coins are
counted even before the student's first visit of the day writes the `daily` row)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import AdminDep
from app.api.deps import Session
from app.core import economy
from app.core.wallet_rules import tunis_day
from app.features.wallet.service import _pass_until, current_streak
from app.models import (
    AdminAction,
    AICache,
    Chapter,
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
    PlacementSet,
    PointsLedger,
    Presence,
    QuizAttempt,
    QuizSet,
    StudyAsset,
    TutorSession,
    User,
    WisdomTip,
    World,
    WorldMember,
)

router = APIRouter()
PAGE_SIZE = 50
PageQ = Query(1, ge=1, le=10_000)


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


async def _fetch(s: AsyncSession, q: Select, page: int) -> tuple[list[Any], int]:
    total = await s.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = (await s.execute(q.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE))).all()
    return list(rows), int(total or 0)


async def _page(s: AsyncSession, q: Select, page: int, row) -> Page:
    rows, total = await _fetch(s, q, page)
    return Page(items=[row(r) for r in rows], total=total, page=page, page_size=PAGE_SIZE)


def _uuid(value: str | None, name: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(422, f"{name} is not a valid id") from e


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- wallets (read-only, from the ledgers) -----------------------------------------------
async def wallets(s: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not user_ids:
        return {}
    today = tunis_day()
    rows = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.bucket, func.sum(CoinLedger.delta))
            .where(
                CoinLedger.user_id.in_(user_ids),
                (CoinLedger.bucket != "free") | (CoinLedger.day == today),
            )
            .group_by(CoinLedger.user_id, CoinLedger.bucket)
        )
    ).all()
    has_daily = set(
        await s.scalars(
            select(CoinLedger.user_id).where(
                CoinLedger.user_id.in_(user_ids),
                CoinLedger.kind == "daily",
                CoinLedger.day == today,
            )
        )
    )
    passes = (
        await s.execute(
            select(CoinLedger.user_id, CoinLedger.created_at).where(
                CoinLedger.user_id.in_(user_ids),
                CoinLedger.bucket == "pass",
                CoinLedger.kind.in_(("purchased", "admin")),
                CoinLedger.delta == 0,
            )
        )
    ).all()
    out: dict[uuid.UUID, dict[str, Any]] = {
        u: {"free": 0, "earned": 0, "purchased": 0, "pass_until": None} for u in user_ids
    }
    for uid, bucket, total in rows:
        if bucket in ("free", "earned", "purchased"):
            out[uid][bucket] = int(total or 0)
    for uid in user_ids:
        if uid not in has_daily:
            out[uid]["free"] += economy.DAILY_FREE_COINS  # what their next visit will show
    by_user: dict[uuid.UUID, list[datetime]] = {}
    for uid, ts in passes:
        by_user.setdefault(uid, []).append(ts)
    for uid, stamps in by_user.items():
        out[uid]["pass_until"] = _pass_until(stamps)
    for w in out.values():
        w["coins"] = w["free"] + w["earned"] + w["purchased"]
        w["pass_active"] = bool(w["pass_until"] and w["pass_until"] > datetime.now(UTC))
    return out


async def pass_end_overrides(s: AsyncSession, user_ids: list[uuid.UUID]) -> dict:
    """An admin may end an Exam Pass early (an `admin` row with ref `pass_end`)."""
    rows = (
        await s.execute(
            select(CoinLedger.user_id, func.max(CoinLedger.created_at))
            .where(
                CoinLedger.user_id.in_(user_ids),
                CoinLedger.kind == "admin",
                CoinLedger.ref == "pass_end",
            )
            .group_by(CoinLedger.user_id)
        )
    ).all()
    return dict(rows)


async def wallet_view(s: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    w = await wallets(s, user_ids)
    ended = await pass_end_overrides(s, user_ids) if user_ids else {}
    for uid, end in ended.items():
        until = w[uid]["pass_until"]
        if until and end and end < until:
            w[uid]["pass_until"] = end
            w[uid]["pass_active"] = end > datetime.now(UTC)
    return w


# --- users ---------------------------------------------------------------------------------------
@router.get("/users", response_model=Page)
async def users(
    _: AdminDep,
    s: Session,
    q: str = "",
    language: str = "",
    world_id: str = "",
    page: int = PageQ,
) -> Page:
    worlds_n = (
        select(func.count()).where(WorldMember.user_id == User.id).correlate(User).scalar_subquery()
    )
    points = (
        select(func.coalesce(func.sum(PointsLedger.delta), 0))
        .where(PointsLedger.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    seen = (
        select(func.max(Presence.seen_at))
        .where(Presence.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    daily_seen = (
        select(func.max(DailyState.seen_at))
        .where(DailyState.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    stmt = select(User, worlds_n, points, seen, daily_seen).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where(User.nickname.ilike(_like(q.strip())))
    if language:
        stmt = stmt.where(User.ui_language == language)
    if wid := _uuid(world_id, "world_id"):
        stmt = stmt.where(
            User.id.in_(select(WorldMember.user_id).where(WorldMember.world_id == wid))
        )
    rows, total = await _fetch(s, stmt, page)
    w = await wallet_view(s, [r[0].id for r in rows])
    items = []
    for user, n_worlds, pts, seen_at, dseen in rows:
        last = max((t for t in (seen_at, dseen) if t is not None), default=None)
        items.append(
            {
                "id": user.id,
                "nickname": user.nickname,
                "created_at": user.created_at,
                "ui_language": user.ui_language,
                "worlds": n_worlds,
                "wallet": w[user.id],
                "points": int(pts or 0),
                "streak": await current_streak(s, user.id),
                "last_seen": last,
                "dev_user": user.password_hash == "!",
            }
        )
    return Page(items=items, total=total, page=page, page_size=PAGE_SIZE)


@router.get("/users/{user_id}")
async def user_detail(user_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Not Found")
    w = (await wallet_view(s, [user_id]))[user_id]
    worlds = (
        await s.execute(
            select(World.id, World.name, World.join_code, WorldMember.joined_at)
            .join(WorldMember, WorldMember.world_id == World.id)
            .where(WorldMember.user_id == user_id)
            .order_by(WorldMember.joined_at)
        )
    ).all()
    levels = (
        await s.execute(
            select(Course.id, Course.name, CourseLevel.level, CourseLevel.placed_at)
            .join(CourseLevel, CourseLevel.course_id == Course.id)
            .where(CourseLevel.user_id == user_id)
        )
    ).all()
    coins = await s.scalars(
        select(CoinLedger)
        .where(CoinLedger.user_id == user_id)
        .order_by(CoinLedger.created_at.desc())
        .limit(PAGE_SIZE)
    )
    pts = await s.scalars(
        select(PointsLedger)
        .where(PointsLedger.user_id == user_id)
        .order_by(PointsLedger.created_at.desc())
        .limit(PAGE_SIZE)
    )
    jobs = await s.scalars(
        select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc()).limit(20)
    )

    async def count(col) -> int:
        return int(await s.scalar(select(func.count()).where(col == user_id)) or 0)

    return {
        "id": user.id,
        "nickname": user.nickname,
        "ui_language": user.ui_language,
        "created_at": user.created_at,
        "session_epoch": user.session_epoch,
        "dev_user": user.password_hash == "!",
        "wallet": w,
        "points": int(
            await s.scalar(
                select(func.coalesce(func.sum(PointsLedger.delta), 0)).where(
                    PointsLedger.user_id == user_id
                )
            )
            or 0
        ),
        "streak": await current_streak(s, user_id),
        "worlds": [{"id": i, "name": n, "join_code": c, "joined_at": j} for i, n, c, j in worlds],
        "levels": [
            {"course_id": i, "course": n, "level": lv, "placed_at": at} for i, n, lv, at in levels
        ],
        "counts": {
            "quiz_attempts": await count(QuizAttempt.user_id),
            "tutor_sessions": await count(TutorSession.user_id),
            "questions": await count(PeerQuestion.author_id),
            "answers": await count(PeerAnswer.author_id),
            "jobs": await count(Job.user_id),
        },
        "coin_ledger": [
            {
                "created_at": r.created_at,
                "day": r.day,
                "bucket": r.bucket,
                "kind": r.kind,
                "delta": r.delta,
                "ref": r.ref,
            }
            for r in coins
        ],
        "points_ledger": [
            {"created_at": r.created_at, "delta": r.delta, "reason": r.reason, "ref": r.ref}
            for r in pts
        ],
        "jobs": [_job_row(j) for j in jobs],
    }


# --- worlds --------------------------------------------------------------------------------------
def _pool_balance():
    return (
        select(func.coalesce(func.sum(ClassPoolLedger.delta), 0))
        .where(ClassPoolLedger.world_id == World.id)
        .correlate(World)
        .scalar_subquery()
    )


@router.get("/worlds", response_model=Page)
async def worlds(_: AdminDep, s: Session, q: str = "", page: int = PageQ) -> Page:
    members = (
        select(func.count())
        .where(WorldMember.world_id == World.id)
        .correlate(World)
        .scalar_subquery()
    )
    courses = (
        select(func.count()).where(Course.world_id == World.id).correlate(World).scalar_subquery()
    )
    docs = (
        select(func.count()).where(Document.world_id == World.id).correlate(World).scalar_subquery()
    )
    failed = (
        select(func.count())
        .where(Document.world_id == World.id, Document.status == "failed")
        .correlate(World)
        .scalar_subquery()
    )
    stmt = (
        select(World, User.nickname, members, courses, docs, failed, _pool_balance())
        .join(User, User.id == World.creator_id, isouter=True)
        .order_by(World.name)
    )
    if q:
        stmt = stmt.where(or_(World.name.ilike(_like(q)), World.join_code.ilike(_like(q))))
    return await _page(
        s,
        stmt,
        page,
        lambda r: {
            "id": r[0].id,
            "name": r[0].name,
            "join_code": r[0].join_code,
            "creator": r[1],
            "members": r[2],
            "courses": r[3],
            "documents": r[4],
            "failed_documents": r[5],
            "pool": int(r[6] or 0),
        },
    )


@router.get("/worlds/{world_id}")
async def world_detail(world_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "Not Found")
    creator = await s.get(User, world.creator_id) if world.creator_id else None
    members = (
        await s.execute(
            select(User.id, User.nickname, WorldMember.joined_at)
            .join(WorldMember, WorldMember.user_id == User.id)
            .where(WorldMember.world_id == world_id)
            .order_by(WorldMember.joined_at)
        )
    ).all()
    courses = list(
        await s.scalars(select(Course).where(Course.world_id == world_id).order_by(Course.name))
    )
    chapters = list(
        await s.scalars(
            select(Chapter)
            .where(Chapter.course_id.in_([c.id for c in courses]))
            .order_by(Chapter.idx)
        )
    )
    documents = list(
        await s.scalars(
            select(Document).where(Document.world_id == world_id).order_by(Document.created_at)
        )
    )
    pool = (
        await s.execute(
            select(ClassPoolLedger, User.nickname)
            .join(User, User.id == ClassPoolLedger.user_id, isouter=True)
            .where(ClassPoolLedger.world_id == world_id)
            .order_by(ClassPoolLedger.created_at.desc())
            .limit(PAGE_SIZE)
        )
    ).all()
    balance = await s.scalar(
        select(func.coalesce(func.sum(ClassPoolLedger.delta), 0)).where(
            ClassPoolLedger.world_id == world_id
        )
    )
    docs_by_chapter: dict[uuid.UUID, list[dict]] = {}
    for d in documents:
        docs_by_chapter.setdefault(d.chapter_id, []).append(
            {
                "id": d.id,
                "filename": d.filename,
                "kind": d.kind,
                "size": d.size,
                "status": d.status,
                "progress": d.progress,
                "error": d.error,
                "page_count": d.page_count,
                "tagged_by": d.tagged_by,
                "created_at": d.created_at,
            }
        )
    return {
        "id": world.id,
        "name": world.name,
        "join_code": world.join_code,
        "creator": creator.nickname if creator else None,
        "members": [{"id": i, "nickname": n, "joined_at": j} for i, n, j in members],
        "courses": [
            {
                "id": c.id,
                "name": c.name,
                "exam_date": c.exam_date,
                "chapters": [
                    {
                        "id": ch.id,
                        "idx": ch.idx,
                        "title": ch.title,
                        "documents": docs_by_chapter.get(ch.id, []),
                    }
                    for ch in chapters
                    if ch.course_id == c.id
                ],
            }
            for c in courses
        ],
        "pool": {
            "balance": int(balance or 0),
            "history": [
                {
                    "created_at": row.created_at,
                    "kind": row.kind,
                    "delta": row.delta,
                    "ref": row.ref,
                    "by": nick,
                }
                for row, nick in pool
            ],
        },
    }


# --- content -------------------------------------------------------------------------------------
ContentKind = Literal["quiz_sets", "study_assets", "wisdom_tips", "placement_sets", "flashcards"]
CONTENT = {
    "quiz_sets": QuizSet,
    "study_assets": StudyAsset,
    "wisdom_tips": WisdomTip,
    "placement_sets": PlacementSet,
    "flashcards": Flashcard,
}


def _content_row(kind: str, r: Any) -> dict[str, Any]:
    base = {
        "id": r.id,
        "created_at": r.created_at,
        "provider": getattr(r, "provider", None),
        "edited_by_admin": getattr(r, "edited_by_admin", False),
        "world_id": getattr(r, "world_id", None),
        "chapter_id": getattr(r, "chapter_id", None),
        "level": getattr(r, "level", None),
        "language": getattr(r, "language", None),
    }
    if kind == "quiz_sets":
        base["summary"] = f"{len(r.questions or [])} questions"
    elif kind == "study_assets":
        base["summary"] = r.kind
    elif kind == "wisdom_tips":
        base["summary"] = f"{r.concept} · {r.mistake_type} · {r.student_count} students"
    elif kind == "placement_sets":
        base["summary"] = f"{len(r.questions or [])} questions"
        base["course_id"] = r.course_id
    else:
        base["summary"] = r.front[:80]
        base["source"] = r.source
        base["personal"] = r.user_id is not None
    return base


@router.get("/content", response_model=Page)
async def content(
    _: AdminDep,
    s: Session,
    kind: ContentKind = "quiz_sets",
    world_id: str = "",
    chapter_id: str = "",
    level: str = "",
    language: str = "",
    asset_kind: str = "",
    page: int = PageQ,
) -> Page:
    model = CONTENT[kind]
    stmt = select(model).order_by(model.created_at.desc())
    wid, cid = _uuid(world_id, "world_id"), _uuid(chapter_id, "chapter_id")
    if wid:
        if kind == "placement_sets":
            stmt = stmt.where(model.course_id.in_(select(Course.id).where(Course.world_id == wid)))
        elif kind == "flashcards":
            stmt = stmt.where(
                model.chapter_id.in_(
                    select(Chapter.id)
                    .join(Course, Course.id == Chapter.course_id)
                    .where(Course.world_id == wid)
                )
            )
        else:
            stmt = stmt.where(model.world_id == wid)
    if cid and hasattr(model, "chapter_id"):
        stmt = stmt.where(model.chapter_id == cid)
    if level and hasattr(model, "level"):
        stmt = stmt.where(model.level == level)
    if language and hasattr(model, "language"):
        stmt = stmt.where(model.language == language)
    if asset_kind and kind == "study_assets":
        stmt = stmt.where(model.kind == asset_kind)
    return await _page(s, stmt, page, lambda r: _content_row(kind, r[0]))


def content_body(kind: str, r: Any) -> Any:
    return {
        "quiz_sets": lambda: r.questions,
        "study_assets": lambda: r.content,
        "wisdom_tips": lambda: r.text,
        "placement_sets": lambda: r.questions,
        "flashcards": lambda: {"front": r.front, "back": r.back, "concept": r.concept},
    }[kind]()


@router.get("/content/{kind}/{item_id}")
async def content_item(kind: ContentKind, item_id: uuid.UUID, _: AdminDep, s: Session) -> dict:
    row = await s.get(CONTENT[kind], item_id)
    if row is None:
        raise HTTPException(404, "Not Found")
    return {**_content_row(kind, row), "body": content_body(kind, row)}


# --- arena ---------------------------------------------------------------------------------------
@router.get("/arena/questions", response_model=Page)
async def arena_questions(
    _: AdminDep, s: Session, status: str = "", world_id: str = "", q: str = "", page: int = PageQ
) -> Page:
    answers = (
        select(func.count())
        .where(PeerAnswer.question_id == PeerQuestion.id)
        .correlate(PeerQuestion)
        .scalar_subquery()
    )
    stmt = (
        select(PeerQuestion, User.nickname, answers)
        .join(User, User.id == PeerQuestion.author_id)
        .order_by(PeerQuestion.created_at.desc())
    )
    if status:
        stmt = stmt.where(PeerQuestion.status == status)
    if wid := _uuid(world_id, "world_id"):
        stmt = stmt.where(PeerQuestion.world_id == wid)
    if q:
        stmt = stmt.where(PeerQuestion.text.ilike(_like(q)))
    return await _page(
        s,
        stmt,
        page,
        lambda r: {
            "id": r[0].id,
            "created_at": r[0].created_at,
            "author": r[1],
            "text": r[0].text,
            "language": r[0].language,
            "status": r[0].status,
            "reject_reason": r[0].reject_reason,
            "pinned_answer_id": r[0].pinned_answer_id,
            "answers": r[2],
            "world_id": r[0].world_id,
            "chapter_id": r[0].chapter_id,
        },
    )


@router.get("/arena/answers", response_model=Page)
async def arena_answers(
    _: AdminDep, s: Session, status: str = "", question_id: str = "", page: int = PageQ
) -> Page:
    stmt = (
        select(PeerAnswer, User.nickname, PeerQuestion.text, PeerQuestion.pinned_answer_id)
        .join(User, User.id == PeerAnswer.author_id)
        .join(PeerQuestion, PeerQuestion.id == PeerAnswer.question_id)
        .order_by(PeerAnswer.created_at.desc())
    )
    if status:
        stmt = stmt.where(PeerAnswer.status == status)
    if qid := _uuid(question_id, "question_id"):
        stmt = stmt.where(PeerAnswer.question_id == qid)
    return await _page(
        s,
        stmt,
        page,
        lambda r: {
            "id": r[0].id,
            "created_at": r[0].created_at,
            "author": r[1],
            "question_id": r[0].question_id,
            "question": r[2],
            "pinned": r[3] == r[0].id,
            "text": r[0].text,
            "status": r[0].status,
            "ai_score": r[0].ai_score,
            "ai_confidence": r[0].ai_confidence,
            "reviewed_by_mid": r[0].reviewed_by_mid,
            "rewarded": r[0].rewarded,
            "feedback": r[0].ai_feedback,
        },
    )


# --- jobs ----------------------------------------------------------------------------------------
def _job_row(j: Job) -> dict[str, Any]:
    return {
        "id": j.id,
        "kind": j.kind,
        "lane": j.lane,
        "status": j.status,
        "stage": j.stage,
        "attempts": j.attempts,
        "not_before": j.not_before,
        "cost": j.cost,
        "error": j.error,
        "quick_mode": j.quick_mode,
        "provider": j.provider,
        "user_id": j.user_id,
        "world_id": j.world_id,
        "created_at": j.created_at,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
    }


@router.get("/jobs", response_model=Page)
async def jobs(
    _: AdminDep,
    s: Session,
    lane: str = "",
    status: str = "",
    kind: str = "",
    user_id: str = "",
    page: int = PageQ,
) -> Page:
    stmt = select(Job, User.nickname).join(User, User.id == Job.user_id, isouter=True)
    stmt = stmt.order_by(Job.created_at.desc())
    if lane:
        stmt = stmt.where(Job.lane == lane)
    if status:
        stmt = stmt.where(Job.status == status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if uid := _uuid(user_id, "user_id"):
        stmt = stmt.where(Job.user_id == uid)
    return await _page(s, stmt, page, lambda r: {**_job_row(r[0]), "user": r[1]})


@router.get("/jobs/summary")
async def jobs_summary(_: AdminDep, s: Session) -> list[dict[str, Any]]:
    rows = (
        await s.execute(select(Job.lane, Job.status, func.count()).group_by(Job.lane, Job.status))
    ).all()
    return [{"lane": lane, "status": st, "count": n} for lane, st, n in rows]


@router.get("/jobs/{job_id}")
async def job_detail(job_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    job = await s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Not Found")
    return {**_job_row(job), "stages": job.stages, "payload": job.payload, "result": job.result}


# --- cache ---------------------------------------------------------------------------------------
@router.get("/cache", response_model=Page)
async def cache(
    _: AdminDep, s: Session, task_kind: str = "", provider: str = "", q: str = "", page: int = PageQ
) -> Page:
    size = func.pg_column_size(AICache.content)
    stmt = select(AICache, size).order_by(AICache.created_at.desc())
    if task_kind:
        stmt = stmt.where(AICache.task_kind == task_kind)
    if provider:
        stmt = stmt.where(AICache.provider == provider)
    if q:
        stmt = stmt.where(AICache.key.ilike(_like(q)))
    now = datetime.now(UTC)
    return await _page(
        s,
        stmt,
        page,
        lambda r: {
            "key": r[0].key,
            "task_kind": r[0].task_kind,
            "provider": r[0].provider,
            "model": r[0].model,
            "model_tier": r[0].model_tier,
            "hits": r[0].hits,
            "created_at": r[0].created_at,
            "age_s": int((now - r[0].created_at).total_seconds()),
            "size_bytes": int(r[1] or 0),
        },
    )


@router.get("/cache/summary")
async def cache_summary(_: AdminDep, s: Session) -> list[dict[str, Any]]:
    rows = (
        await s.execute(
            select(
                AICache.task_kind,
                AICache.provider,
                func.count(),
                func.coalesce(func.sum(AICache.hits), 0),
                func.coalesce(func.sum(func.pg_column_size(AICache.content)), 0),
            ).group_by(AICache.task_kind, AICache.provider)
        )
    ).all()
    return [
        {"task_kind": k, "provider": p, "entries": n, "hits": int(h), "size_bytes": int(b)}
        for k, p, n, h, b in rows
    ]


# --- admin log -----------------------------------------------------------------------------------
@router.get("/actions", response_model=Page)
async def actions(
    _: AdminDep,
    s: Session,
    action: str = "",
    target_kind: str = "",
    target_id: str = "",
    actor: str = "",
    page: int = PageQ,
) -> Page:
    stmt = select(AdminAction).order_by(AdminAction.ts.desc(), AdminAction.id.desc())
    if action:
        stmt = stmt.where(AdminAction.action.ilike(_like(action)))
    if target_kind:
        stmt = stmt.where(AdminAction.target_kind == target_kind)
    if target_id:
        stmt = stmt.where(cast(AdminAction.target_id, String) == target_id)
    if actor:
        stmt = stmt.where(AdminAction.actor.ilike(_like(actor)))
    return await _page(
        s,
        stmt,
        page,
        lambda r: {
            "id": r[0].id,
            "ts": r[0].ts,
            "actor": r[0].actor,
            "action": r[0].action,
            "target_kind": r[0].target_kind,
            "target_id": r[0].target_id,
            "before": r[0].before,
            "after": r[0].after,
            "reason": r[0].reason,
        },
    )
