import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Profile(Base):
    """Level, style and goals only — nothing that lets the AI treat students differently by who
    they are (PRODUCT.md §Privacy). The avatar is pixel art built from a few options."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    university: Mapped[str | None] = mapped_column(String(80))
    field: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int | None] = mapped_column(Integer)
    style_visual: Mapped[int] = mapped_column(Integer, default=25)
    style_practice: Mapped[int] = mapped_column(Integer, default=25)
    style_listening: Mapped[int] = mapped_column(Integer, default=25)
    style_teaching: Mapped[int] = mapped_column(Integer, default=25)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list)
    daily_minutes: Mapped[int | None] = mapped_column(Integer)
    reminder_time: Mapped[time | None] = mapped_column(Time)
    goal: Mapped[str | None] = mapped_column(String(16))  # pass | grade | deep
    leaderboard_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {skin, outfit, extra}
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CourseLevel(Base):
    __tablename__ = "course_levels"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[str] = mapped_column(String(12))  # beginner | intermediate | advanced
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    goal: Mapped[str | None] = mapped_column(String(16))


class ChapterMastery(Base):
    __tablename__ = "chapter_mastery"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), primary_key=True
    )
    mastery: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    weak: Mapped[bool] = mapped_column(Boolean, default=False)


class PlacementSet(Base):
    """8 placement questions per course + language, generated once and shared by the class.
    Answers never leave the server."""

    __tablename__ = "placement_sets"
    __table_args__ = (UniqueConstraint("course_id", "language"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(8))
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class Presence(Base):
    """'On this island now': refreshed by the island view; read with a 2-minute window."""

    __tablename__ = "presence"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL")
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
