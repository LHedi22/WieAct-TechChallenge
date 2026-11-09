"""/api/admin/debug/*: the AI pipeline inspector (read-only, admin auth; DECISIONS.md 2026-11-09).

- live: the worker's heartbeat (worker_status), queues, calls per minute, flags, last 50 calls
- jobs/{id}: one job's timeline (jobs.events), its calls, its coin rows, its result
- calls/{id}: one ai_call_log row + its trace (only while tracing was on) + the repair call
- calls/{id}/replay: rerun a traced call on mock or local (DEBUG_REPLAY job); never cloud
- routing: actual calls per task kind × tier × pattern next to the routing table

Nothing here makes a model call or writes ai_call_log; replays are jobs whose rows are `debug`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.admin import audit
from app.admin.auth import AdminActionDep, AdminDep
from app.api.deps import Session
from app.api.health import SettingsDep
from app.core import flags
from app.gateway.router import ROUTES
from app.gateway.types import TaskKind
from app.jobs import replay as replay_job
from app.jobs.service import AIPaused, create_job
from app.models import (
    AdminAction,
    AICallLog,
    AICallTrace,
    ClassPoolLedger,
    CoinLedger,
    Job,
    User,
    WorkerStatus,
)

router = APIRouter(prefix="/debug")
FRESH_S = 10  # a worker_status row older than this is shown as stale
Outcome = Literal["ok", "cache", "503", "quota", "400", "fallback", "forced", "repair", "error"]


def outcome(r: AICallLog) -> str:
    """One colour per call on the Live strip."""
    if r.cache_hit:
        return "cache"
    if r.task_kind == TaskKind.JSON_REPAIR.value:
        return "repair"
    if r.status_code == 200:
        if r.forced:
            return "forced"
        return "fallback" if r.fallback else "ok"
    if r.refusal_reason == "saturated" or r.status_code == 503:
        return "503"
    if r.refusal_reason == "quota" or r.status_code == 429:
        return "quota"
    if r.refusal_reason == "ceiling" or r.status_code == 400:
        return "400"
    return "error"


def call_row(r: AICallLog) -> dict[str, Any]:
    return {
        "id": r.id,
        "ts": r.ts,
        "task_kind": r.task_kind,
        "lane": r.lane,
        "tier": r.model_tier,
        "provider": r.provider,
        "model": r.model,
        "pattern": r.pattern,
        "status_code": r.status_code,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "latency_ms": r.latency_ms,
        "cache_hit": r.cache_hit,
        "single_flight": r.single_flight,
        "fallback": r.fallback,
        "forced": r.forced,
        "refusal_reason": r.refusal_reason,
        "request_hash": r.request_hash,
        "job_id": r.job_id,
        "attempt": r.attempt,
        "debug": r.debug,
        "outcome": outcome(r),
    }


def replay_availability(settings) -> dict[str, Any]:
    """Replays never reach the platform: a replayed request would count against our key."""
    if settings.APP_ENV == "production":
        return {
            "available": False,
            "targets": [],
            "reason": "Production runs on the platform only, and a replay there would count "
            "against our key as a repeated identical request. Replay a trace in development.",
        }
    targets = ["mock"]
    if settings.profile_for("local").base_url:
        targets.append("local")
    return {"available": True, "targets": targets, "reason": None}


# --- live ----------------------------------------------------------------------------------------
@router.get("/live")
async def live(_: AdminDep, s: Session, settings: SettingsDep) -> dict[str, Any]:
    now = datetime.now(UTC)
    workers = [
        {
            "worker_id": w.worker_id,
            "updated_at": w.updated_at,
            "age_s": round((now - w.updated_at).total_seconds(), 1),
            "fresh": (now - w.updated_at).total_seconds() <= FRESH_S,
            **w.data,
        }
        for w in await s.scalars(select(WorkerStatus).order_by(WorkerStatus.updated_at.desc()))
    ]
    queue = []
    for lane in ("interactive", "background"):
        ready = await s.scalar(
            select(func.count()).where(
                Job.status == "queued",
                Job.lane == lane,
                or_(Job.not_before.is_(None), Job.not_before <= now),
            )
        )
        waiting = await s.scalar(
            select(func.count()).where(
                Job.status == "queued", Job.lane == lane, Job.not_before > now
            )
        )
        running = await s.scalar(
            select(func.count()).where(Job.status == "running", Job.lane == lane)
        )
        nxt = await s.scalar(
            select(func.min(Job.not_before)).where(
                Job.status == "queued", Job.lane == lane, Job.not_before > now
            )
        )
        queue.append(
            {
                "lane": lane,
                "ready": ready or 0,
                "waiting": waiting or 0,
                "running": running or 0,
                "next_not_before": nxt,
            }
        )
    since = now - timedelta(minutes=15)
    minute = func.date_trunc("minute", AICallLog.ts)
    per_minute = (
        await s.execute(
            select(minute, AICallLog.model_tier, func.count())
            .where(
                AICallLog.ts >= since,
                AICallLog.cache_hit.is_(False),
                AICallLog.debug.is_(False),
            )
            .group_by(minute, AICallLog.model_tier)
            .order_by(minute)
        )
    ).all()
    last = await s.scalars(select(AICallLog).order_by(AICallLog.id.desc()).limit(50))
    stored = await flags.rows(s)
    return {
        "now": now,
        "workers": workers,
        "queue": queue,
        "calls_per_minute": [{"minute": m, "tier": t, "calls": n} for m, t, n in per_minute],
        "flags": {k: (r.value if r else None) for k, r in ((k, stored.get(k)) for k in flags.KEYS)},
        "trace_on": _trace_on(stored, now),
        "app_env": settings.APP_ENV,
        "last_calls": [call_row(r) for r in last],
    }


def _trace_on(stored: dict, now: datetime) -> bool:
    row = stored.get("trace_prompts_until")
    if row is None or not row.value:
        return False
    try:
        return datetime.fromisoformat(str(row.value)) > now
    except ValueError:
        return False


# --- job timeline --------------------------------------------------------------------------------
@router.get("/jobs/{job_id}")
async def job_timeline(job_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    job = await s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Not Found")
    nickname = await s.scalar(select(User.nickname).where(User.id == job.user_id))
    calls = list(
        await s.scalars(select(AICallLog).where(AICallLog.job_id == job_id).order_by(AICallLog.id))
    )
    traced = set(
        await s.scalars(
            select(AICallTrace.call_log_id).where(
                AICallTrace.call_log_id.in_([c.id for c in calls] or [0])
            )
        )
    )
    ref = str(job_id)
    coins = await s.scalars(
        select(CoinLedger).where(CoinLedger.ref == ref).order_by(CoinLedger.created_at)
    )
    pool = await s.scalars(
        select(ClassPoolLedger).where(ClassPoolLedger.ref == ref).order_by(ClassPoolLedger.id)
    )
    events = [{"t": job.created_at, "type": "created", "lane": job.lane, "cost": job.cost}]
    events += list(job.events or [])
    return {
        "job": {
            "id": job.id,
            "kind": job.kind,
            "lane": job.lane,
            "status": job.status,
            "stage": job.stage,
            "stages": job.stages,
            "attempts": job.attempts,
            "not_before": job.not_before,
            "cost": job.cost,
            "quick_mode": job.quick_mode,
            "provider": job.provider,
            "error": job.error,
            "user_id": job.user_id,
            "user": nickname,
            "world_id": job.world_id,
            "worker_id": job.worker_id,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        },
        "events": events,
        "calls": [{**call_row(c), "traced": c.id in traced} for c in calls],
        "coins": [
            {
                "created_at": r.created_at,
                "day": r.day,
                "bucket": r.bucket,
                "kind": r.kind,
                "delta": r.delta,
            }
            for r in coins
        ],
        "pool": [{"kind": r.kind, "delta": r.delta, "world_id": r.world_id} for r in pool],
        "result": job.result,
    }


# --- calls ---------------------------------------------------------------------------------------
@router.get("/calls")
async def calls(
    _: AdminDep,
    s: Session,
    job_id: uuid.UUID | None = None,
    task_kind: str = "",
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    q = select(AICallLog).order_by(AICallLog.id.desc()).limit(limit)
    if job_id:
        q = q.where(AICallLog.job_id == job_id)
    if task_kind:
        q = q.where(AICallLog.task_kind == task_kind)
    return [call_row(r) for r in await s.scalars(q)]


def trace_view(t: AICallTrace | None) -> dict[str, Any] | None:
    if t is None:
        return None
    reply = t.reply
    stripped = None
    if reply is not None and "<think>" in reply:
        from app.gateway.jsonfix import strip_think  # noqa: PLC0415

        stripped = strip_think(reply)
    return {
        "created_at": t.created_at,
        "messages": t.messages,
        "reply": reply,
        "reply_without_think": stripped,
        "parsed": t.parsed,
        "error": t.error,
    }


@router.get("/calls/{call_id}")
async def call_detail(call_id: int, _: AdminDep, s: Session, settings: SettingsDep) -> dict:
    row = await s.get(AICallLog, call_id)
    if row is None:
        raise HTTPException(404, "Not Found")
    t = await s.get(AICallTrace, call_id)
    repair = None
    if row.job_id is not None and row.task_kind != TaskKind.JSON_REPAIR.value:
        nxt = await s.scalar(
            select(AICallLog)
            .where(AICallLog.job_id == row.job_id, AICallLog.id > row.id)
            .order_by(AICallLog.id)
            .limit(1)
        )
        if nxt is not None and nxt.task_kind == TaskKind.JSON_REPAIR.value:
            repair = {**call_row(nxt), "trace": trace_view(await s.get(AICallTrace, nxt.id))}
    return {
        "call": call_row(row),
        "trace": trace_view(t),
        "repair": repair,
        "replay": replay_availability(settings) if t is not None else None,
        "tracing_note": None
        if t is not None
        else "No trace: tracing was off when this call ran, or the trace is older than 24 h.",
    }


class ReplayIn(BaseModel):
    target: Literal["mock", "local"] = "mock"
    # edited prompt; omitted = the traced messages as they were sent
    messages: list[dict[str, str]] | None = Field(None, max_length=40)
    response_format: Literal["json", "text"] | None = None


@router.post("/calls/{call_id}/replay")
async def replay(
    call_id: int, body: ReplayIn, admin: AdminActionDep, s: Session, settings: SettingsDep
) -> dict[str, Any]:
    avail = replay_availability(settings)
    if not avail["available"] or body.target not in avail["targets"]:
        raise HTTPException(409, avail["reason"] or f"{body.target} is not configured here")
    row = await s.get(AICallLog, call_id)
    t = await s.get(AICallTrace, call_id)
    if row is None or t is None:
        raise HTTPException(404, "No trace for this call")
    try:
        kind = TaskKind(row.task_kind)
    except ValueError as e:
        raise HTTPException(422, "this task kind can't be replayed") from e
    if kind == TaskKind.EMBED:
        raise HTTPException(422, "embeddings calls can't be replayed")
    fmt = body.response_format or ("json" if t.parsed is not None else "text")
    payload = {
        "call_log_id": call_id,
        "target": body.target,
        "task_kind": kind.value,
        "tier": row.model_tier if row.model_tier in ("compact", "mid") else None,
        "messages": body.messages or t.messages,
        "response_format": fmt,
        "edited": body.messages is not None,
    }
    try:
        job = await create_job(s, kind=replay_job.KIND, lane="interactive", payload=payload)
    except AIPaused as e:
        raise HTTPException(409, "AI actions are paused (offline demo mode): replay later") from e
    job.provider = body.target  # never counted under cloud
    audit.record(
        s,
        admin,
        "debug.replay",
        target_kind="ai_call",
        target_id=str(call_id),
        before=None,
        after={"target": body.target, "edited": body.messages is not None, "job_id": str(job.id)},
        reason=None,
    )
    await s.commit()
    return {"job_id": job.id}


@router.get("/replays/{job_id}")
async def replay_result(job_id: uuid.UUID, _: AdminDep, s: Session) -> dict[str, Any]:
    job = await s.get(Job, job_id)
    if job is None or job.kind != replay_job.KIND:
        raise HTTPException(404, "Not Found")
    return {
        "job_id": job.id,
        "status": job.status,
        "error": job.error,
        "result": job.result,
        "edited": (job.payload or {}).get("edited", False),
    }


# --- routing check -------------------------------------------------------------------------------
ALLOWED_MID = {"escalation"}  # the table says compact, but this pattern escalates to mid on purpose


@router.get("/routing")
async def routing(
    _: AdminDep,
    s: Session,
    hours: int = Query(24, ge=1, le=24 * 14),
    provider: Literal["cloud", "local", "mock", "all"] = "all",
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    where = [AICallLog.ts >= since, AICallLog.cache_hit.is_(False), AICallLog.debug.is_(False)]
    if provider != "all":
        where.append(AICallLog.provider == provider)
    rows = (
        await s.execute(
            select(
                AICallLog.task_kind,
                AICallLog.model_tier,
                AICallLog.pattern,
                func.count(),
            )
            .where(*where)
            .group_by(AICallLog.task_kind, AICallLog.model_tier, AICallLog.pattern)
        )
    ).all()
    table = {k.value: {"tier": r.tier, "pattern": r.pattern} for k, r in ROUTES.items()}
    table[TaskKind.EMBED.value] = {"tier": "embed", "pattern": "batch"}
    kinds: dict[str, dict[str, Any]] = {}
    for kind, tier, pattern, n in rows:
        expected = table.get(kind)
        k = kinds.setdefault(kind, {"task_kind": kind, "expected": expected, "actual": []})
        flag = None
        if expected and tier == "mid" and expected["tier"] == "compact":
            flag = None if expected["pattern"] in ALLOWED_MID else "mid_where_compact"
        elif expected and tier == "compact" and expected["tier"] == "mid":
            flag = "fallback" if pattern in ("fallback", "forced-fallback") else "compact_where_mid"
        k["actual"].append({"tier": tier, "pattern": pattern, "calls": n, "flag": flag})
    for kind, route in table.items():
        kinds.setdefault(kind, {"task_kind": kind, "expected": route, "actual": []})

    # repeated identical requests: the same request answered twice (organisers' cache indicator)
    dup_rows = (
        await s.execute(
            select(
                AICallLog.request_hash,
                func.min(AICallLog.task_kind),
                func.count(),
                func.min(AICallLog.ts),
                func.max(AICallLog.ts),
                func.array_agg(AICallLog.id),
            )
            .where(*where, AICallLog.status_code == 200, AICallLog.request_hash.is_not(None))
            .group_by(AICallLog.request_hash)
            .having(func.count() > 1)
            .order_by(func.count().desc())
            .limit(100)
        )
    ).all()
    repeats = []
    for h, kind, n, first, last, ids in dup_rows:
        purged = await s.scalar(
            select(func.count()).where(
                and_(
                    AdminAction.action.like("cache.%"),
                    AdminAction.ts >= first,
                    AdminAction.ts <= last,
                )
            )
        )
        repeats.append(
            {
                "request_hash": h,
                "task_kind": kind,
                "calls": n,
                "first": first,
                "last": last,
                "call_ids": sorted(ids)[:20],
                "purge_between": bool(purged),
            }
        )
    return {
        "since": since,
        "provider": provider,
        "kinds": sorted(kinds.values(), key=lambda k: k["task_kind"]),
        "repeats": repeats,
        "flags": sum(
            1 for k in kinds.values() for a in k["actual"] if a["flag"] not in (None, "fallback")
        )
        + sum(1 for r in repeats if not r["purge_between"]),
    }
