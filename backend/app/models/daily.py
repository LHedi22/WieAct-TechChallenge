import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class DailyState(Base):
    """One row per student per Tunis day: the 3 challenges and their progress.
    `challenges[i]` = {type, world_id, course_id, chapter_id, title, target, progress, done, why}.
    A rule-based plan is written at once; the DAILY_PLAN job (plan-once, mid) may replace it while
    no progress has been made."""

    __tablename__ = "daily_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    challenges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {message} from the AI plan
    planned_by: Mapped[str] = mapped_column(String(8), default="rule")  # rule | ai
    plan_job_id: Mapped[uuid.UUID | None] = mapped_column()
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class WisdomTip(Base):
    """An anonymous Class Wisdom tip: the trap behind a mistake that WISDOM_THRESHOLD distinct
    students of a world made. Written once (one mid call for all the world's languages), reused."""

    __tablename__ = "wisdom_tips"
    __table_args__ = (UniqueConstraint("world_id", "concept", "mistake_type", "language"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL")
    )
    concept: Mapped[str] = mapped_column(String(80))
    mistake_type: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8))
    text: Mapped[dict[str, Any]] = mapped_column(JSONB)  # {trap, why, right}
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at()
