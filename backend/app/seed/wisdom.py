"""Three synthetic classmates who fell for the same trap in the demo world's Calculus quiz, so the
demo always has a Class Wisdom tip ready. They take the class's shared quiz set and miss its
first question; the mistakes are written as the tagging job would (no tagging call needed), then
the real Class Wisdom path runs (`check_patterns` → one WISDOM_TIP job)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import UNUSABLE_PASSWORD
from app.core import economy
from app.features.wisdom import service as wisdom
from app.models import (
    Chapter,
    Course,
    Mistake,
    QuizAttempt,
    QuizSet,
    User,
    World,
    WorldMember,
)

STUDENTS = ("seed-ana", "seed-bilel", "seed-cyrine")
COURSE = "Calculus I"
MISTAKE_TYPE = "misconception"


def _answers(questions: list[dict]) -> list[dict]:
    """Question 0: wrong twice (the trap); the rest right first time."""
    out = []
    for i, q in enumerate(questions):
        right = q["answer_index"]
        if i == 0:
            wrong = (right + 1) % len(q["options"])
            out.append({"first": wrong, "second": wrong, "status": "wrong"})
        else:
            out.append({"first": right, "status": "correct"})
    return out


async def _student(s: AsyncSession, nickname: str, world: World) -> User:
    user = await s.scalar(select(User).where(User.nickname == nickname))
    if user is None:
        user = User(nickname=nickname, password_hash=UNUSABLE_PASSWORD, ui_language="en")
        s.add(user)
        await s.flush()
    if await s.get(WorldMember, (world.id, user.id)) is None:
        s.add(WorldMember(world_id=world.id, user_id=user.id))
    return user


async def seed_wisdom(sm: async_sessionmaker, join_code: str) -> list[uuid.UUID]:
    """Idempotent. Returns the WISDOM_TIP jobs queued (empty if the tip exists or the class quiz
    set is not ready yet)."""
    async with sm() as s:
        world = await s.scalar(select(World).where(World.join_code == join_code))
        course = await s.scalar(
            select(Course).where(Course.world_id == world.id, Course.name == COURSE)
        )
        found = (
            await s.execute(  # the first chapter whose class quiz set is ready
                select(QuizSet, Chapter)
                .join(Chapter, Chapter.id == QuizSet.chapter_id)
                .where(Chapter.course_id == course.id)
                .order_by(Chapter.idx, QuizSet.language != "en", QuizSet.seed)
                .limit(1)
            )
        ).first()
        if found is None:
            return []
        qs, chapter = found
        concept = (qs.questions[0].get("concept") or chapter.title)[:80].strip().lower()
        for nickname in STUDENTS:
            user = await _student(s, nickname, world)
            done = await s.scalar(
                select(QuizAttempt.id).where(
                    QuizAttempt.user_id == user.id, QuizAttempt.quiz_set_id == qs.id
                )
            )
            if done:
                continue
            answers = _answers(qs.questions)
            score = sum(a["status"] == "correct" for a in answers)
            attempt = QuizAttempt(
                user_id=user.id,
                quiz_set_id=qs.id,
                world_id=world.id,
                course_id=course.id,
                chapter_id=chapter.id,
                level=qs.level,
                language=qs.language,
                answers=answers,
                current=len(answers),
                score=score,
                points=score * economy.POINTS["quiz_correct_first_try"],
                second_tries=1,
                status="finished",
                finished_at=datetime.now(UTC),
            )
            s.add(attempt)
            await s.flush()
            s.add(
                Mistake(
                    user_id=user.id,
                    world_id=world.id,
                    chapter_id=chapter.id,
                    attempt_id=attempt.id,
                    question_idx=0,
                    concept=concept,
                    mistake_type=MISTAKE_TYPE,
                )
            )
        await s.commit()
        return await wisdom.check_patterns(s, world.id, {(concept, MISTAKE_TYPE)})
