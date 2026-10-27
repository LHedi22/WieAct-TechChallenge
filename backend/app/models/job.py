import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Job(Base):
    """Every AI action is a job, run by the worker; the UI polls GET /api/jobs/{id}."""

    __tablename__ = "jobs"
    __table_args__ = (
        # Worker picks by lane priority, respecting not_before (SELECT … FOR UPDATE SKIP LOCKED).
        Index("ix_jobs_queue", "status", "lane", "not_before"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    world_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    lane: Mapped[str] = mapped_column(String(16))  # interactive | background
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    stage: Mapped[str | None] = mapped_column(String(48))
    stages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    quick_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
