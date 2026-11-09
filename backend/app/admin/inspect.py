"""/api/admin/debug/students/*: everything one student's account holds, checked against the rules
(read-only; changes go through the admin actions on /admin/users). No nickname leaves the admin
side; nothing here writes (the wallet endpoint's function runs in a savepoint that is rolled back,
because it writes today's refill row).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.admin import invariants as inv
from app.admin.auth import AdminDep
from app.admin.browse import wallets
from app.api.deps import Session
from app.core import economy
from app.core.wallet_rules import split_spend, tunis_day
from app.features.leaderboard.service import board
from app.features.wallet.service import Balances, balances, current_streak
from app.models import (
    Chapter,
    ChapterMastery,
    CoinLedger,
    Course,
    CourseLevel,
    DailyState,
    FlashcardReview,
    Job,
    PeerAnswer,
    PeerQuestion,
    PointsLedger,
    QuizAttempt,
    TutorSession,
    User,
    WorldMember,
)

router = APIRouter(prefix="/debug/students")
LIMIT = 50  # rows per activity list


def _row(obj: Any, *names: str) -> dict[str, Any]:
    return {n: getattr(obj, n) for n in names}


async def _wallet(s, user_id: uuid.UUID) -> Balances:
    """`wallet.service.balances` as the wallet endpoint runs it, without keeping its write."""
    nested = await s.begin_nested()
    try:
        return await balances(s, user_id)
    finally:
        await nested.rollback()


async def _user(s, user_id: uuid.UUID) -> User:
    user = await s.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Not Found")
    return user


@router.get("/{user_id}")
async def student(user_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    user = await _user(s, user_id)
    now = datetime.now()
    b = await _wallet(s, user_id)
    today = tunis_day()

    ledger = list(
        await s.scalars(
            select(CoinLedger)
            .where(CoinLedger.user_id == user_id)
            .order_by(CoinLedger.day.desc(), CoinLedger.created_at)
        )
    )
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in ledger:
        by_day[str(r.day)].append(_row(r, "created_at", "bucket", "kind", "delta", "ref"))
    days = [
        {
            "day": d,
            "rows": rows,
            "net": sum(x["delta"] for x in rows),
            "earned": sum(x["delta"] for x in rows if x["kind"] == "earned"),
        }
        for d, rows in by_day.items()
    ]

    points_rows = list(
        await s.scalars(
            select(PointsLedger)
            .where(PointsLedger.user_id == user_id)
            .order_by(PointsLedger.created_at.desc())
            .limit(200)
        )
    )
    total_points = await s.scalar(
        select(func.coalesce(func.sum(PointsLedger.delta), 0)).where(
            PointsLedger.user_id == user_id
        )
    )
    worlds = list(
        await s.scalars(select(WorldMember.world_id).where(WorldMember.user_id == user_id))
    )
    ranks = []
    for scope, wid in [("global", None), *(("world", w) for w in worlds)]:
        for period in ("week", "all"):
            bd = await board(s, user, scope, period, wid)  # type: ignore[arg-type]
            ranks.append(
                {
                    "scope": scope,
                    "world_id": wid,
                    "period": period,
                    "rank": bd.me.rank if bd.me else None,
                    "points": bd.me.points if bd.me else 0,
                    "opted_in": bd.opted_in,
                }
            )

    levels = (
        await s.execute(
            select(CourseLevel, Course.name)
            .join(Course, Course.id == CourseLevel.course_id)
            .where(CourseLevel.user_id == user_id)
        )
    ).all()
    mastery = (
        await s.execute(
            select(ChapterMastery, Chapter.title, Chapter.course_id)
            .join(Chapter, Chapter.id == ChapterMastery.chapter_id)
            .where(ChapterMastery.user_id == user_id)
        )
    ).all()
    daily = await s.get(DailyState, (user_id, today))

    attempts = await s.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user_id)
        .order_by(QuizAttempt.id.desc())
        .limit(LIMIT)
    )
    tutors = await s.scalars(
        select(TutorSession)
        .where(TutorSession.user_id == user_id)
        .order_by(TutorSession.id.desc())
        .limit(LIMIT)
    )
    questions = await s.scalars(
        select(PeerQuestion).where(PeerQuestion.author_id == user_id).limit(LIMIT)
    )
    answers = await s.scalars(
        select(PeerAnswer).where(PeerAnswer.author_id == user_id).limit(LIMIT)
    )
    reviews = await s.scalars(
        select(FlashcardReview)
        .where(FlashcardReview.user_id == user_id)
        .order_by(FlashcardReview.updated_at.desc())
        .limit(LIMIT)
    )
    jobs = await s.scalars(
        select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc()).limit(LIMIT)
    )
    checks = await inv.run(s, user_id)

    return {
        "user": {
            "id": user.id,
            "nickname": user.nickname,
            "ui_language": user.ui_language,
            "created_at": user.created_at,
        },
        "wallet": {
            "free": b.free,
            "earned": b.earned,
            "purchased": b.purchased,
            "coins": b.coins,
            "today": today,
            "earned_today": b.earned_today,
            "daily_earn_cap": economy.DAILY_EARN_CAP,
            "pass_until": b.pass_until,
            "pass_active": b.pass_active(datetime.now(b.pass_until.tzinfo))
            if b.pass_until
            else False,
            "pass_used_today": b.pass_used_today,
            "pass_daily_limit": economy.EXAM_PASS_DAILY_LIMIT,
            "has_daily_row_today": any(r.kind == "daily" and r.day == today for r in ledger),
            "spending_order": economy.SPENDING_ORDER,
            "days": days,
        },
        "points": {
            "total": int(total_points or 0),
            "streak": await current_streak(s, user_id),
            "rows": [
                _row(r, "created_at", "world_id", "delta", "reason", "ref") for r in points_rows
            ],
            "ranks": ranks,
        },
        "learning": {
            "levels": [
                {
                    "course_id": cl.course_id,
                    "course": name,
                    "level": cl.level,
                    "placed_at": cl.placed_at,
                    "goal": cl.goal,
                }
                for cl, name in levels
            ],
            "mastery": [
                {
                    "chapter_id": m.chapter_id,
                    "chapter": title,
                    "course_id": cid,
                    "mastery": m.mastery,
                    "weak": m.weak,
                }
                for m, title, cid in mastery
            ],
        },
        "daily": None
        if daily is None
        else _row(daily, "date", "challenges", "plan", "planned_by", "plan_job_id", "seen_at"),
        "activity": {
            "quiz_attempts": [
                _row(
                    a,
                    "id",
                    "chapter_id",
                    "level",
                    "language",
                    "status",
                    "current",
                    "score",
                    "points",
                    "second_tries",
                    "answers",
                    "finished_at",
                )
                for a in attempts
            ],
            "tutor_sessions": [
                {
                    **_row(
                        t,
                        "id",
                        "chapter_id",
                        "level",
                        "language",
                        "status",
                        "hints_used",
                        "stuck_count",
                        "escalate_next",
                        "ideas",
                        "summary",
                        "ended_at",
                    ),
                    "turns": len(t.turns or []),
                    "escalations": sum(1 for x in (t.turns or []) if x.get("tier") == "mid"),
                    "turn_list": t.turns,
                }
                for t in tutors
            ],
            "peer_questions": [
                _row(q, "id", "chapter_id", "text", "language", "status", "reject_reason")
                for q in questions
            ],
            "peer_answers": [
                _row(
                    a,
                    "id",
                    "question_id",
                    "status",
                    "ai_score",
                    "ai_confidence",
                    "reviewed_by_mid",
                    "rewarded",
                )
                for a in answers
            ],
            "flashcard_reviews": [
                _row(r, "card_id", "due_at", "interval_s", "ease", "reps", "updated_at")
                for r in reviews
            ],
            "jobs": [
                _row(
                    j,
                    "id",
                    "kind",
                    "lane",
                    "status",
                    "cost",
                    "error",
                    "quick_mode",
                    "attempts",
                    "created_at",
                    "finished_at",
                )
                for j in jobs
            ],
        },
        "invariants": [
            {"check": name, "ok": not rows, "description": inv.DESCRIPTIONS[name], "rows": rows}
            for name, rows in checks.items()
        ],
        "admin_wallet_view": (await wallets(s, [user_id]))[user_id],
        "generated_at": now,
    }


Activity = Literal[
    "quiz", "study_pack", "audio", "tutor_session", "teachback_solo", "peer_question"
]
POOL_PAYABLE = {"study_pack", "audio"}


@router.get("/{user_id}/price")
async def explain_price(
    user_id: uuid.UUID,
    _: AdminDep,
    s: Session,
    activity: Activity,
    chapter_id: uuid.UUID | None = None,
    level: str = Query("intermediate"),
) -> dict[str, Any]:
    """What the student would pay right now and why, with the app's own pricing functions."""
    user = await _user(s, user_id)
    language = user.ui_language
    steps: list[str] = []
    chapter = await s.get(Chapter, chapter_id) if chapter_id else None
    if activity in ("quiz", "study_pack", "audio") and chapter is None:
        raise HTTPException(422, "this activity needs a chapter_id")
    world_id = None
    if chapter is not None:
        world_id = await s.scalar(select(Course.world_id).where(Course.id == chapter.course_id))

    if activity == "quiz":
        from app.features.quiz import service as quiz  # noqa: PLC0415

        base = await quiz.price(s, user, chapter.id, level, language)
        steps.append(
            "An unseen class quiz set exists: free."
            if base["cached"]
            else f"No unseen set for {level}/{language}: a new set costs {base['cost']}."
        )
    elif activity == "study_pack":
        from app.features.studio import service as studio  # noqa: PLC0415

        base = await studio.price(s, chapter.id, level, language)
        steps.append(
            "The class already has (or is making) these notes: free."
            if base["cost"] == 0
            else f"No notes for {level}/{language} yet: a pack costs {base['cost']}."
        )
    elif activity == "audio":
        from app.features.audio import service as audio  # noqa: PLC0415

        base = await audio.price(s, chapter.id, level, language)
        steps.append(
            "The class already has this episode: free."
            if base["cost"] == 0
            else f"No episode for {level}/{language} yet: it costs {base['cost']}."
        )
    else:
        base = {"cost": economy.COST[activity], "cached": False}
        steps.append(f"{activity} costs {base['cost']} (economy.COST, nothing to reuse).")
    cost = int(base["cost"])

    b = await _wallet(s, user_id)
    now = datetime.now(b.pass_until.tzinfo) if b.pass_until else None
    result: dict[str, Any] = {
        "activity": activity,
        "language": language,
        "level": level,
        "base_cost": cost,
        "cached": bool(base.get("cached")),
        "wallet": {"free": b.free, "earned": b.earned, "purchased": b.purchased},
        "exam_pass": False,
        "pool": None,
        "split": {},
        "pays": cost,
        "affordable": True,
    }
    if cost == 0:
        steps.append("Nothing is charged.")
        result["pays"] = 0
        return {**result, "steps": steps}
    if now is not None and b.pass_active(now) and b.pass_left_today > 0:
        steps.append(
            f"Exam Pass active ({b.pass_used_today}/{economy.EXAM_PASS_DAILY_LIMIT} used today): "
            "a 0-coin pass row is written instead of coins."
        )
        result.update(exam_pass=True, pays=0)
        return {**result, "steps": steps}
    if b.pass_until is not None and now is not None and b.pass_active(now):
        steps.append("Exam Pass active but today's limit is used up: coins are charged.")
    if activity in POOL_PAYABLE and world_id is not None:
        from app.features.pool import service as pool  # noqa: PLC0415

        balance = await pool.balance(s, world_id)
        result["pool"] = {"balance": balance, "can_pay": balance >= cost}
        steps.append(
            f"Class pool holds {balance}: the student may pay from it instead."
            if balance >= cost
            else f"Class pool holds {balance}, less than {cost}: personal coins only."
        )
    split = split_spend(cost, free=b.free, earned=b.earned, purchased=b.purchased)
    if split is None:
        steps.append(f"Only {b.coins} coins: the start would answer 402 errors.insufficient_coins.")
        result["affordable"] = False
    else:
        order = ", ".join(f"{n} {k}" for k, n in split.items() if n)
        steps.append(f"Paid in spending order {economy.SPENDING_ORDER}: {order}.")
        result["split"] = split
    return {**result, "steps": steps}
