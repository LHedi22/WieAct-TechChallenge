from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
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
    refusal_reason: Mapped[str | None] = mapped_column(String(64))
