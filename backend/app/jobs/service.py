"""Jobs: create, read (with queue position + ETA for the loading screen), cancel."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.jobs.coins import coins
from app.jobs.registry import spec_for
from app.models import AICallLog, Job

LANE_RANK = {"interactive": 0, "background": 1}
DEFAULT_CALL_S = 8.0  # until the call log has history


class JobView(BaseModel):
    id: uuid.UUID
    kind: str
    lane: str
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    stage: str | None
    stages: list[str]
    queue_position: int | None  # 1 = next to run; None when not queued
    eta_s: int | None
    waiting_reason: str | None  # quota / saturated / … while deferred
    quick_mode: bool
    cost: int
    result: dict[str, Any] | None
    error: str | None  # i18n key, never a raw model error
    created_at: datetime
    finished_at: datetime | None


async def create_job(
    s: AsyncSession,
    *,
    kind: str,
    lane: str,
    payload: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
    world_id: uuid.UUID | None = None,
    cost: int = 0,
) -> Job:
    spec = spec_for(kind)
    job = Job(
        kind=kind,
        lane=lane,
        status="queued",
        payload=payload or {},
        stages=list(spec.stages),
        user_id=user_id,
        world_id=world_id,
        cost=cost,
    )
    s.add(job)
    await s.flush()
    await coins.reserve(s, job)
    await s.commit()
    return job


async def _avg_call_s(s: AsyncSession) -> float:
    recent = (
        select(AICallLog.latency_ms)
        .where(AICallLog.status_code == 200, AICallLog.latency_ms > 0)
        .order_by(AICallLog.id.desc())
        .limit(30)
        .subquery()
    )
    avg = await s.scalar(select(func.avg(recent.c.latency_ms)))
    return float(avg) / 1000 if avg else DEFAULT_CALL_S


async def queue_position(s: AsyncSession, job: Job) -> int:
    """Jobs that will run before this one (higher-priority lane, or same lane and older) + 1."""
    ahead = await s.scalar(
        select(func.count()).where(
            Job.status == "queued",
            Job.id != job.id,
            or_(
                and_(Job.lane == "interactive", job.lane == "background"),
                and_(Job.lane == job.lane, Job.created_at < job.created_at),
            ),
        )
    )
    return int(ahead or 0) + 1


async def view(s: AsyncSession, job: Job) -> JobView:
    position = eta = None
    waiting = None
    if job.status == "queued":
        position = await queue_position(s, job)
        per_call = await _avg_call_s(s)
        concurrency = max(1, get_settings().LLM_MAX_CONCURRENCY)
        eta_f = position * per_call / concurrency
        if job.not_before:
            eta_f = max(eta_f, (job.not_before - datetime.now(UTC)).total_seconds() + per_call)
        eta = max(1, round(eta_f))
        if job.error and job.error.startswith("deferred:"):
            waiting = job.error.split(":", 1)[1]
    return JobView(
        id=job.id,
        kind=job.kind,
        lane=job.lane,
        status=job.status,  # type: ignore[arg-type]
        stage=job.stage,
        stages=job.stages or [],
        queue_position=position,
        eta_s=eta,
        waiting_reason=waiting,
        quick_mode=job.quick_mode,
        cost=job.cost,
        result=job.result,
        error=None if (job.error or "").startswith("deferred:") else job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


class NotCancellable(Exception):
    pass


async def cancel(s: AsyncSession, job: Job) -> Job:
    """ "Cancel and keep my coins": only while still queued (a running call can't be recalled)."""
    if job.status != "queued":
        raise NotCancellable(job.status)
    job.status = "cancelled"
    job.finished_at = datetime.now(UTC)
    await coins.refund(s, job)
    await s.commit()
    return job
