"""Call-log aggregates — the numbers the organisers compute on our key (docs/PLATFORM.md), for the
report and the demo. Defaults to provider=cloud so local/mock traffic never inflates them."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health import SettingsDep
from app.core.db import get_session
from app.gateway.quota import seen_header_names
from app.models import AICallLog

router = APIRouter(prefix="/api/admin", tags=["admin"])


class TierStats(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    avg_latency_ms: int


class Stats(BaseModel):
    provider: str
    calls: int  # requests sent to the platform (cache hits excluded)
    ok: int
    cache_hits: int
    repeated_identical: int  # successful calls whose exact request was already answered
    compact_share: float  # 0-1, the orchestration indicator
    by_tier: dict[str, TierStats]
    by_task: dict[str, int]
    refusals: dict[str, int]  # quota / saturated / ceiling / blocked / transient / bad_request
    fallbacks: int  # mid → compact (quick mode) answers
    quota_headers_seen: list[str]


def require_admin(
    settings: SettingsDep, x_admin_token: Annotated[str | None, Header()] = None
) -> None:
    token = settings.ADMIN_TOKEN.get_secret_value()
    if token and x_admin_token != token:
        raise HTTPException(403, "errors.forbidden")


@router.get("/stats", response_model=Stats, dependencies=[Depends(require_admin)])
async def stats(
    s: Annotated[AsyncSession, Depends(get_session)],
    provider: Literal["cloud", "local", "mock", "all"] = "cloud",
) -> Stats:
    where = [] if provider == "all" else [AICallLog.provider == provider]
    calls_q = select(AICallLog).where(*where, AICallLog.cache_hit.is_(False)).subquery()

    totals = (
        await s.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cast(calls_q.c.status_code == 200, Integer)), 0),
                func.coalesce(
                    func.sum(cast(calls_q.c.fallback & (calls_q.c.status_code == 200), Integer)), 0
                ),
            ).select_from(calls_q)
        )
    ).one()
    cache_hits = await s.scalar(select(func.count()).where(*where, AICallLog.cache_hit.is_(True)))
    tier_rows = (
        await s.execute(
            select(
                calls_q.c.model_tier,
                func.count(),
                func.coalesce(func.sum(calls_q.c.tokens_in), 0),
                func.coalesce(func.sum(calls_q.c.tokens_out), 0),
                func.coalesce(
                    func.avg(case((calls_q.c.status_code == 200, calls_q.c.latency_ms))), 0
                ),
            ).group_by(calls_q.c.model_tier)
        )
    ).all()
    by_tier = {
        t: TierStats(calls=n, tokens_in=ti, tokens_out=to, avg_latency_ms=int(lat))
        for t, n, ti, to, lat in tier_rows
    }
    task_rows = (
        await s.execute(select(calls_q.c.task_kind, func.count()).group_by(calls_q.c.task_kind))
    ).all()
    refusal_rows = (
        await s.execute(
            select(calls_q.c.refusal_reason, func.count())
            .where(calls_q.c.refusal_reason.is_not(None))
            .group_by(calls_q.c.refusal_reason)
        )
    ).all()
    dup = (
        select((func.count() - 1).label("extra"))
        .where(calls_q.c.status_code == 200, calls_q.c.request_hash.is_not(None))
        .group_by(calls_q.c.request_hash)
        .having(func.count() > 1)
        .subquery()
    )
    repeated = await s.scalar(select(func.coalesce(func.sum(dup.c.extra), 0)))
    total_calls = totals[0]
    compact = by_tier.get("compact").calls if "compact" in by_tier else 0
    return Stats(
        provider=provider,
        calls=total_calls,
        ok=totals[1],
        cache_hits=cache_hits or 0,
        repeated_identical=int(repeated or 0),
        compact_share=round(compact / total_calls, 3) if total_calls else 0.0,
        by_tier=by_tier,
        by_task=dict(task_rows),
        refusals=dict(refusal_rows),
        fallbacks=totals[2],
        quota_headers_seen=seen_header_names(),
    )
