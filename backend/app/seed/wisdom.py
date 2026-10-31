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


def _answers(questions: list[dict], trap: int = 0) -> list[dict]:
    """The trap question: wrong twice; the rest right first time."""
    out = []
    for i, q in enumerate(questions):
        right = q["answer_index"]
        if i == trap:
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


def trap_concept(question: dict, chapter: Chapter) -> str:
    """The concept a mistake on this question is counted under (the tagging job's rule)."""
    return (question.get("concept") or chapter.title)[:80].strip().lower()


async def class_quiz_set(
    s: AsyncSession, world: World, course_name: str
) -> tuple[Course, QuizSet, Chapter] | None:
    """The first chapter's class quiz set of a course, or None while it isn't ready."""
    course = await s.scalar(
        select(Course).where(Course.world_id == world.id, Course.name == course_name)
    )
    if course is None:
        return None
    found = (
        await s.execute(
            select(QuizSet, Chapter)
            .join(Chapter, Chapter.id == QuizSet.chapter_id)
            .where(Chapter.course_id == course.id)
            .order_by(Chapter.idx, QuizSet.language != "en", QuizSet.seed)
            .limit(1)
        )
    ).first()
    return None if found is None else (course, found[0], found[1])


async def seed_wisdom(
    sm: async_sessionmaker,
    join_code: str,
    *,
    course_name: str = COURSE,
    trap: int = 0,
    students: tuple[str, ...] = STUDENTS,
) -> list[uuid.UUID]:
    """Idempotent. `students` all miss question `trap` of the course's class quiz set. Returns the
    WISDOM_TIP jobs queued (empty if the tip exists or the class quiz set is not ready yet)."""
    async with sm() as s:
        world = await s.scalar(select(World).where(World.join_code == join_code))
        found = await class_quiz_set(s, world, course_name)
        if found is None:
            return []
        course, qs, chapter = found
        concept = trap_concept(qs.questions[trap], chapter)
        for nickname in students:
            user = await _student(s, nickname, world)
            done = await s.scalar(
                select(Mistake.id).where(
                    Mistake.user_id == user.id,
                    Mistake.world_id == world.id,
                    Mistake.concept == concept,
                    Mistake.mistake_type == MISTAKE_TYPE,
                )
            )
            if done:
                continue
            answers = _answers(qs.questions, trap)
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
                    question_idx=trap,
                    concept=concept,
                    mistake_type=MISTAKE_TYPE,
                )
            )
        await s.commit()
        return await wisdom.check_patterns(s, world.id, {(concept, MISTAKE_TYPE)})
