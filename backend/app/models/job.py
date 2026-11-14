import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Job(Base):
    """Every AI action is a job, run by the worker; the UI polls GET /api/jobs/{id}."""

    __tablename__ = "jobs"
    __table_args__ = (
        # Worker picks by lane priority, respecting not_before (SELECT … FOR UPDATE SKIP LOCKED).
        Index("ix_jobs_queue", "status", "lane", "not_before"),
        Index("ix_jobs_lease", "status", "lease_until"),
        # Inside a lane, lower priority first, then oldest (Group E, migration 0018).
        Index("ix_jobs_queue_priority", "status", "lane", "priority", "created_at"),
        # One queued/running job per shared class asset (audit OPT-01, migration 0017).
        Index(
            "uq_jobs_share_key_active",
            "share_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND share_key IS NOT NULL"),
        ),
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
    # Lower runs first inside a lane: 10 needed now, 50 next-chapter prefetch, 100 default.
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default=text("100"))
    # queued | running | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # handler input
    provider: Mapped[str | None] = mapped_column(String(8))  # resolved when the job runs
    stage: Mapped[str | None] = mapped_column(String(48))
    stages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    quick_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lease of a running job (audit F-RES-1): the worker that runs it renews lease_until; the
    # sweep fails and refunds jobs whose lease expired (their worker died or froze).
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(64))
    # The class asset this job makes, e.g. "STUDY_PACK:<chapter>:<level>:<language>" (OPT-01).
    share_key: Mapped[str | None] = mapped_column(String(200))
    # Timeline for /admin/debug: [{t, type: claimed|stage|deferred|requeued|done|failed|swept, …}]
    events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
