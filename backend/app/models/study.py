import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class QuizAttempt(Base):
    """One student working through one quiz set. `answers[i]` = {first, second, status}, status
    pending | correct | second | wrong | skipped. Graded here, never in the UI."""

    __tablename__ = "quiz_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    quiz_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quiz_sets.id", ondelete="CASCADE"), index=True
    )
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12))
    language: Mapped[str] = mapped_column(String(8))
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    current: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    second_tries: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="in_progress")  # | finished
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Mistake(Base):
    """A tagged wrong answer (concept, mistake_type): weak spots, challenges, Class Wisdom."""

    __tablename__ = "mistakes"
    __table_args__ = (Index("ix_mistakes_pattern", "world_id", "concept", "mistake_type"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quiz_attempts.id", ondelete="SET NULL")
    )
    question_idx: Mapped[int | None] = mapped_column(Integer)
    concept: Mapped[str] = mapped_column(String(80))
    mistake_type: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_at()


class TutorSession(Base):
    """A Socratic Tutor session: goal + 3 ideas to discover, hints used (max 3), turns."""

    __tablename__ = "tutor_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12))
    language: Mapped[str] = mapped_column(String(8))
    goal: Mapped[str | None] = mapped_column(Text)
    ideas: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # [{text, found}]
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    stuck_count: Mapped[int] = mapped_column(Integer, default=0)
    escalate_next: Mapped[bool] = mapped_column(default=False)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    pending_job_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(12), default="active")  # | ended
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
