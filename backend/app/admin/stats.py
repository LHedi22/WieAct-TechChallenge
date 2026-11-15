"""Call-log aggregates — the numbers the organisers compute on our key (docs/PLATFORM.md), for the
report and the demo. Defaults to provider=cloud so local/mock traffic never inflates them.

Quick-mode answers an admin forced (core/flags.py) are counted in `forced_fallbacks`, never in
`fallbacks`: the report must only claim fallbacks the platform actually caused."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Integer, and_, case, cast, exists, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import AdminDep
from app.core.db import get_session
from app.gateway.quota import seen_header_names
from app.gateway.router import official
from app.jobs import prefetch as prefetch_jobs
from app.models import AICallLog, Job, QuizAttempt

router = APIRouter()


class TierStats(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    avg_latency_ms: int


class CapUse(BaseModel):
    # answered prefetch mid calls today (Tunis day) + those expected from queued prefetch jobs,
    # never above the cap; what running jobs add past it is `over` ("40/40 (+3 finishing)")
    used: int
    cap: int
    over: int
    refused: int  # refused attempts (503, 429, timeout): no model time, so not counted in `used`


class WorldCapUse(CapUse):
    world_id: uuid.UUID


class CreatorCapUse(CapUse):
    creator_id: uuid.UUID


class MidToday(BaseModel):
    """The three daily prefetch mid caps (PREFETCH_MAX_MID_PER_{DAY,WORLD,CREATOR}_…)."""

    all: CapUse
    worlds: list[WorldCapUse]
    creators: list[CreatorCapUse]


class TimeToContent(BaseModel):
    p50: float
    p95: float
    n: int  # done prefetch jobs a student opened


class PrefetchStats(BaseModel):
    """Background prefetch, one chapter ahead (Group E, app/jobs/prefetch.py)."""

    jobs: int
    done: int
    failed: int
    waiting: int  # queued or running
    promoted: int  # a student needed it before it was ready ("Get it now" / joined)
    calls: dict[str, int]  # platform requests made by prefetch jobs, per tier
    quiz_sets_used: int  # prefetched quiz sets a student later started (the waste check)
    opened: int  # prefetch jobs whose content a student was served or joined (jobs.opened_at)
    hit_rate: float | None  # opened ÷ done (done ones): how much of what was prefetched got used
    # seconds from opening to content, 0 when it was ready first
    time_to_content_s: TimeToContent
    mid_today: MidToday


class Stats(BaseModel):
    provider: str
    calls: int  # requests sent to the platform (cache hits excluded)
    ok: int
    cache_hits: int
    repeated_identical: int  # successful calls whose exact request was already answered
    compact_share: float  # 0-1, the orchestration indicator (forced Quick-mode calls left out)
    by_tier: dict[str, TierStats]
    by_task: dict[str, int]
    # chat calls per official orchestration pattern (PLATFORM.md); `none` = no pattern (OPT-08)
    by_pattern: dict[str, int]
    refusals: dict[str, int]  # quota / saturated / ceiling / blocked / transient / bad_request
    fallbacks: int  # mid → compact (quick mode) answers the platform caused (503, timeout)
    forced_fallbacks: int  # Quick-mode answers an admin switched on (never counted above)
    quota_headers_seen: list[str]
    prefetch: PrefetchStats


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
    pattern_rows = (
        await s.execute(
            select(calls_q.c.pattern, func.count())
            .where(calls_q.c.model_tier != "embed")
            .group_by(calls_q.c.pattern)
        )
    ).all()
    by_pattern: dict[str, int] = {}
    for pattern, n in pattern_rows:
        name = official(pattern)
        if name in ("plan-once", "execute-compact"):
            name = "plan-once / execute-compact"  # one official pattern, two halves
        by_pattern[name] = by_pattern.get(name, 0) + n
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
    prefetch = await _prefetch(s, calls_q)
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
        by_pattern=by_pattern,
        refusals=dict(refusal_rows),
        fallbacks=totals[2],
        forced_fallbacks=totals[3],
        quota_headers_seen=seen_header_names(),
        prefetch=prefetch,
    )


async def _prefetch(s: AsyncSession, calls_q) -> PrefetchStats:
    is_prefetch = Job.payload["prefetch"].astext == "true"
    by_status = select(Job.status, func.count()).where(is_prefetch).group_by(Job.status)
    rows = dict((await s.execute(by_status)).all())
    promoted = await s.scalar(
        select(func.count()).where(is_prefetch, Job.events.op("@>")([{"type": "promoted"}]))
    )
    tier_calls = (
        await s.execute(
            select(calls_q.c.model_tier, func.count())
            .join(Job, Job.id == calls_q.c.job_id)
            .where(is_prefetch)
            .group_by(calls_q.c.model_tier)
        )
    ).all()
    chapter = cast(Job.payload["chapter_id"].astext, QuizAttempt.chapter_id.type)
    used = await s.scalar(
        select(func.count()).where(
            is_prefetch,
            Job.kind == "QUIZ_POOL",
            Job.status == "done",
            exists().where(
                and_(
                    QuizAttempt.chapter_id == chapter,
                    QuizAttempt.level == Job.payload["level"].astext,
                    QuizAttempt.language == Job.payload["language"].astext,
                    QuizAttempt.created_at >= Job.finished_at,
                )
            ),
        )
    )
    opened = await s.scalar(select(func.count()).where(is_prefetch, Job.opened_at.is_not(None)))
    wait = func.greatest(0, extract("epoch", Job.finished_at - Job.opened_at))
    p50, p95, n = (
        await s.execute(
            select(
                func.percentile_cont(0.5).within_group(wait),
                func.percentile_cont(0.95).within_group(wait),
                func.count(),
            ).where(is_prefetch, Job.status == "done", Job.opened_at.is_not(None))
        )
    ).one()
    done = rows.get("done", 0)
    return PrefetchStats(
        jobs=sum(rows.values()),
        done=rows.get("done", 0),
        failed=rows.get("failed", 0),
        waiting=rows.get("queued", 0) + rows.get("running", 0),
        promoted=promoted or 0,
        calls=dict(tier_calls),
        quiz_sets_used=used or 0,
        opened=opened or 0,
        hit_rate=round(n / done, 3) if done else None,  # done jobs a student opened
        time_to_content_s={
            "p50": round(float(p50 or 0), 1),
            "p95": round(float(p95 or 0), 1),
            "n": n,
        },
        mid_today=await prefetch_jobs.mid_today(s),
    )
