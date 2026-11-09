"""Call-log aggregates — the numbers the organisers compute on our key (docs/PLATFORM.md), for the
report and the demo. Defaults to provider=cloud so local/mock traffic never inflates them.

Quick-mode answers an admin forced (core/flags.py) are counted in `forced_fallbacks`, never in
`fallbacks`: the report must only claim fallbacks the platform actually caused."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import AdminDep
from app.core.db import get_session
from app.gateway.quota import seen_header_names
from app.models import AICallLog

router = APIRouter()


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
    compact_share: float  # 0-1, the orchestration indicator (forced Quick-mode calls left out)
    by_tier: dict[str, TierStats]
    by_task: dict[str, int]
    refusals: dict[str, int]  # quota / saturated / ceiling / blocked / transient / bad_request
    fallbacks: int  # mid → compact (quick mode) answers the platform caused (503, timeout)
    forced_fallbacks: int  # Quick-mode answers an admin switched on (never counted above)
    quota_headers_seen: list[str]


@router.get("/stats", response_model=Stats)
async def stats(
    _: AdminDep,
    s: Annotated[AsyncSession, Depends(get_session)],
    provider: Literal["cloud", "local", "mock", "all"] = "cloud",
) -> Stats:
    # replays from /admin/debug (mock or local only) are never part of the numbers
    where = [AICallLog.debug.is_(False)]
    if provider != "all":
        where.append(AICallLog.provider == provider)
    calls_q = select(AICallLog).where(*where, AICallLog.cache_hit.is_(False)).subquery()

    totals = (
        await s.execute(
            select(
                func.count(),
                func.coalesce(func.sum(cast(calls_q.c.status_code == 200, Integer)), 0),
                func.coalesce(
                    func.sum(
                        cast(
                            calls_q.c.fallback & ~calls_q.c.forced & (calls_q.c.status_code == 200),
                            Integer,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(cast(calls_q.c.forced & (calls_q.c.status_code == 200), Integer)), 0
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
    compact = by_tier["compact"].calls if "compact" in by_tier else 0
    mid = by_tier["mid"].calls if "mid" in by_tier else 0
    # Forced Quick-mode calls (always compact) are an admin's choice, not orchestration: the split
    # leaves them out so the switch can't make the compact share look better than it is.
    forced_calls = int(
        await s.scalar(select(func.count()).select_from(calls_q).where(calls_q.c.forced)) or 0
    )
    compact -= forced_calls
    chat_calls = compact + mid  # the compact/mid split ignores embeddings (own endpoint + quota)
    return Stats(
        provider=provider,
        calls=total_calls,
        ok=totals[1],
        cache_hits=cache_hits or 0,
        repeated_identical=int(repeated or 0),
        compact_share=round(compact / chat_calls, 3) if chat_calls else 0.0,
        by_tier=by_tier,
        by_task=dict(task_rows),
        refusals=dict(refusal_rows),
        fallbacks=totals[2],
        forced_fallbacks=totals[3],
        quota_headers_seen=seen_header_names(),
    )
