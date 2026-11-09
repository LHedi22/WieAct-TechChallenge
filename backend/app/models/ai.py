import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at


class AICache(Base):
    """Shareable AI outputs, generated once. Keys include provider and model so local/mock
    results never stand in for cloud ones."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_kind: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_tier: Mapped[str] = mapped_column(String(8))  # compact | mid
    provider: Mapped[str] = mapped_column(String(8), index=True)  # cloud | local | mock
    model: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()
    hits: Mapped[int] = mapped_column(Integer, default=0)


class AICallLog(Base):
    """One row per gateway call; mirrors the metrics the organisers compute on our key."""

    __tablename__ = "ai_call_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    task_kind: Mapped[str] = mapped_column(String(32))
    lane: Mapped[str | None] = mapped_column(String(16))
    model_tier: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(8), index=True)
    model: Mapped[str] = mapped_column(String(128))
    pattern: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    # Quick mode switched on by an admin (core/flags.py): counted apart from real fallbacks
    forced: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    refusal_reason: Mapped[str | None] = mapped_column(String(64))
    # Hash of (provider, model, messages, params): repeats are the organisers' cache indicator.
    request_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # The job that made the call and its attempt (claim number), set from the running job.
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    attempt: Mapped[int | None] = mapped_column(Integer)
    # A replay from /admin/debug (mock or local only): kept out of every metric and export.
    debug: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # A cache read after waiting on an identical request in flight (single-flight follower).
    single_flight: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AICallTrace(Base):
    """Prompt and reply of one call, written only while the `trace_prompts_until` switch is on
    (gateway/trace.py): fields capped, keys and the student's nickname redacted, rows deleted after
    24 h by the worker. Off by default."""

    __tablename__ = "ai_call_trace"

    call_log_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ai_call_log.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    messages: Mapped[Any] = mapped_column(JSONB, nullable=True)
    reply: Mapped[str | None] = mapped_column(Text)
    parsed: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)


class WorkerStatus(Base):
    """The worker's live state (limiter, lanes, provider), rewritten every ~2 s: the limiter lives
    in the worker process, so this row is how the API sees it."""

    __tablename__ = "worker_status"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class WorkerHeartbeat(Base):
    """A worker_status snapshot every 30 s, kept 24 h: debug bundles show the worker around the
    time of a bug (scripts/debug_bundle.py)."""

    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
