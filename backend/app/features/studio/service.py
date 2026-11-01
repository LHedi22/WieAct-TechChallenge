"""Study Studio: what exists for a chapter + level + language, generating the pack (paid by the
student or the Class Pool, free when it exists or a classmate is already generating it), the
flashcard queue and reviews (spaced repetition, free), and personal cards from a quiz (no AI)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import economy
from app.features.daily import service as daily
from app.features.pool import service as pool
from app.features.quiz.service import LEVELS
from app.features.studio import pack, srs
from app.features.worlds.service import NotFound, member_chapter
from app.jobs.service import create_job
from app.models import (
    Chapter,
    Course,
    Flashcard,
    FlashcardReview,
    QuizAttempt,
    QuizSet,
    User,
)

Pay = Literal["me", "pool"]
QUEUE_MAX = 30
MISSED = ("wrong", "second", "skipped")


class Rejected(Exception):
    def __init__(self, key: str, status: int = 400) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


def _check_level(level: str) -> None:
    if level not in LEVELS:
        raise Rejected("errors.level_invalid")


async def price(s: AsyncSession, chapter_id: uuid.UUID, level: str, language: str) -> dict:
    """What Confirm will cost (DESIGN.md: "Free" when the class already has the pack). Filling a
    part that failed earlier is free too: the class already paid for the pack."""
    missing = await pack.missing(s, chapter_id, level, language)
    if "notes" not in missing or await pack.pending_generation(s, chapter_id, level, language):
        return {"cost": economy.COST["cached_content"], "cached": not missing}
    return {"cost": economy.COST["generate_shared_asset"], "cached": False}


async def status(s: AsyncSession, user: User, chapter: Chapter, level: str) -> dict[str, Any]:
    _check_level(level)
    language = user.ui_language
    course = await s.get(Course, chapter.course_id)
    found = await pack.assets(s, chapter.id, level, language)
    counts = (await queue(s, user, chapter, level))["counts"]
    return {
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "level": level,
        "language": language,
        "notes": found["notes"].content if "notes" in found else None,
        "map": found["map"].content if "map" in found else None,
        "missing": await pack.missing(s, chapter.id, level, language),
        "pending_job_id": await pack.pending_generation(s, chapter.id, level, language),
        "cards": counts,
        "pool_balance": await pool.balance(s, course.world_id),
        **await price(s, chapter.id, level, language),
    }


async def generate(
    s: AsyncSession, user: User, chapter: Chapter, level: str, pay: Pay
) -> dict[str, Any]:
    """Queue the pack (interactive: the student is waiting). Does nothing when it is complete;
    shares a classmate's running job; charges only when the notes do not exist yet."""
    _check_level(level)
    language = user.ui_language
    missing = await pack.missing(s, chapter.id, level, language)
    if not missing:
        return {"job_id": None, "cost": 0, "cached": True}
    job_id = await pack.pending_generation(s, chapter.id, level, language)
    if job_id:
        return {"job_id": job_id, "cost": 0, "cached": False}
    course = await s.get(Course, chapter.course_id)
    cost = economy.COST["generate_shared_asset"] if "notes" in missing else 0
    job = await create_job(  # reserves from the wallet, or from the pool (LedgerCoins.reserve)
        s,
        kind=pack.KIND,
        lane="interactive",
        payload={
            "chapter_id": str(chapter.id),
            "level": level,
            "language": language,
            "paid_by": pay if cost else None,
        },
        user_id=user.id,
        world_id=course.world_id,
        cost=cost,
    )
    return {"job_id": job.id, "cost": cost, "cached": False}


# --- flashcards --------------------------------------------------------------------------------
def _state(r: FlashcardReview | None) -> srs.State | None:
    return srs.State(r.interval_s, r.ease, r.reps) if r else None


async def queue(
    s: AsyncSession, user: User, chapter: Chapter, level: str, now: datetime | None = None
) -> dict[str, Any]:
    """Cards to study now: due ones first (oldest due first), then new ones. The deck of the
    class's pack for this level + the student's own quiz cards for the chapter."""
    now = now or datetime.now(UTC)
    found = await pack.assets(s, chapter.id, level, user.ui_language)
    deck = found["notes"].id if "notes" in found else None
    cards = list(
        await s.scalars(
            select(Flashcard)
            .where(
                Flashcard.chapter_id == chapter.id,
                or_(Flashcard.asset_id == deck, Flashcard.user_id == user.id)
                if deck
                else Flashcard.user_id == user.id,
            )
            .order_by(Flashcard.created_at, Flashcard.id)
        )
    )
    reviews = {
        r.card_id: r
        for r in await s.scalars(
            select(FlashcardReview).where(
                FlashcardReview.user_id == user.id,
                FlashcardReview.card_id.in_([c.id for c in cards]),
            )
        )
    }
    due = sorted(
        (c for c in cards if c.id in reviews and reviews[c.id].due_at <= now),
        key=lambda c: reviews[c.id].due_at,
    )
    new = [c for c in cards if c.id not in reviews]
    later = [reviews[c.id].due_at for c in cards if c.id in reviews and reviews[c.id].due_at > now]
    items = [
        {
            "id": c.id,
            "front": c.front,
            "back": c.back,
            "concept": c.concept,
            "source": c.source,
            "stage": srs.stage(_state(reviews.get(c.id))),
            "intervals": srs.preview(_state(reviews.get(c.id)) or srs.State()),
        }
        for c in (due + new)[:QUEUE_MAX]
    ]
    stages = [srs.stage(_state(reviews[c.id])) for c in due]
    return {
        "cards": items,
        "counts": {
            "new": len(new),
            "learning": stages.count("learning"),
            "review": stages.count("review"),
            "total": len(cards),
        },
        "next_due_at": min(later) if later else None,
    }


async def _card_for(s: AsyncSession, user: User, card_id: uuid.UUID) -> Flashcard:
    card = await s.get(Flashcard, card_id)
    if card is None or (card.user_id is not None and card.user_id != user.id):
        raise Rejected("errors.card_not_found", 404)
    try:
        await member_chapter(s, user, card.chapter_id)
    except NotFound as e:
        raise Rejected("errors.card_not_found", 404) from e
    return card


async def review(
    s: AsyncSession, user: User, card_id: uuid.UUID, grade: srs.Grade, now: datetime | None = None
) -> dict[str, Any]:
    """Grade one card (free, COST.flashcard_review); counts toward a `flashcards` challenge."""
    now = now or datetime.now(UTC)
    card = await _card_for(s, user, card_id)
    row = await s.get(FlashcardReview, (user.id, card.id), with_for_update=True)
    state, due = srs.review(_state(row) or srs.State(), grade, now)
    if row is None:
        row = FlashcardReview(user_id=user.id, card_id=card.id)
        s.add(row)
    row.interval_s, row.ease, row.reps = state.interval_s, state.ease, state.reps
    row.due_at, row.updated_at = due, now
    await daily.record(s, user.id, "flashcards", chapter_id=card.chapter_id, now=now)
    await s.flush()
    return {"card_id": card.id, "due_at": due, "interval_s": state.interval_s}


async def from_quiz(s: AsyncSession, user: User, attempt: QuizAttempt) -> dict[str, Any]:
    """ "Turn these into flashcards": each missed question becomes a personal card (question on the
    front, the right option and the explanation on the back). No AI call; idempotent."""
    if attempt.status != "finished":
        raise Rejected("errors.quiz_not_finished")
    qs = await s.get(QuizSet, attempt.quiz_set_id)
    have = set(
        await s.scalars(
            select(Flashcard.ref).where(
                Flashcard.user_id == user.id, Flashcard.ref.like(f"{attempt.id}:%")
            )
        )
    )
    added = 0
    for i, (q, a) in enumerate(zip(qs.questions, attempt.answers, strict=True)):
        ref = f"{attempt.id}:{i}"
        if a["status"] not in MISSED or ref in have:
            continue
        right = q["options"][q["answer_index"]]
        back = f"{right}\n\n{q['explanation']}".strip() if q.get("explanation") else right
        s.add(
            Flashcard(
                chapter_id=attempt.chapter_id,
                user_id=user.id,
                front=q["question"],
                back=back,
                concept=(q.get("concept") or None) and q["concept"][:80],
                source="quiz",
                ref=ref,
            )
        )
        added += 1
    await s.flush()
    return {"added": added, "chapter_id": attempt.chapter_id, "level": attempt.level}
