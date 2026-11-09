"""GET /api/admin/debug/bundle: one redacted Markdown file about a bug, the first thing a person or
the bug-fixer agent reads (scripts/debug_bundle.py writes it to debug/bundles/, gitignored).

Pick one of `job_id` (that job), `user` (a student id: their recent jobs) or `since` (every failed
or deferred job since then). The bundle holds the job timelines, their model calls, the prompt
traces if tracing was on, the worker heartbeat around that time and the student's invariants.
Nicknames never appear (students are `student <id8>`), and the whole text goes through the trace
redaction (keys, bearer tokens) once more before it leaves.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

from app.admin import invariants as inv
from app.admin.auth import AdminDep
from app.admin.debug import call_row
from app.api.deps import Session
from app.gateway import trace
from app.models import (
    AICallLog,
    AICallTrace,
    CoinLedger,
    Job,
    User,
    WorkerHeartbeat,
    WorldMember,
)

router = APIRouter(prefix="/debug")
MAX_JOBS = 10
TRACE_CHARS = 3000  # per traced message/reply inside a bundle


def _who(user_id: uuid.UUID | None) -> str:
    return f"student {str(user_id)[:8]}" if user_id else "class job"


def _clip(text: Any, n: int = TRACE_CHARS) -> str:
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    return s if len(s) <= n else f"{s[:n]}… [{len(s) - n} more chars]"


def _fence(text: str) -> str:
    return "```\n" + text.replace("```", "ˋˋˋ") + "\n```"


async def _jobs(s, job_id, user, since) -> list[Job]:
    if job_id:
        job = await s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Not Found")
        return [job]
    q = select(Job).order_by(Job.created_at.desc()).limit(MAX_JOBS)
    if user:
        return list(await s.scalars(q.where(Job.user_id == user)))
    return list(
        await s.scalars(
            q.where(
                Job.created_at >= since,
                or_(Job.status == "failed", Job.error.like("deferred:%")),
            )
        )
    )


async def _job_section(s, job: Job) -> list[str]:
    out = [
        f"## Job {job.kind} `{job.id}`",
        "",
        f"- {_who(job.user_id)} · lane {job.lane} · status **{job.status}** · attempts "
        f"{job.attempts} · cost {job.cost} · provider {job.provider or '—'} · quick mode "
        f"{job.quick_mode}",
        f"- error: `{job.error or '—'}` · created {job.created_at:%Y-%m-%d %H:%M:%S} UTC · "
        f"finished {job.finished_at or '—'}",
        "",
        "### Timeline",
        "",
    ]
    out.append(f"- {job.created_at.isoformat(timespec='milliseconds')} created")
    for e in job.events or []:
        extra = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "type"))
        out.append(f"- {e.get('t')} {e.get('type')}{' (' + extra + ')' if extra else ''}")
    calls = list(
        await s.scalars(select(AICallLog).where(AICallLog.job_id == job.id).order_by(AICallLog.id))
    )
    out += ["", f"### Model calls ({len(calls)})", ""]
    if calls:
        out.append(
            "| # | time | task | tier | pattern | att | outcome | status | tok in→out | ms |"
        )
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in calls:
        r = call_row(c)
        out.append(
            f"| {r['id']} | {c.ts:%H:%M:%S} | {r['task_kind']} | {r['tier']} | {r['pattern']} | "
            f"{r['attempt']} | {r['outcome']}{' (single-flight)' if r['single_flight'] else ''} | "
            f"{r['status_code'] or '—'} {r['refusal_reason'] or ''} | {r['tokens_in']}→"
            f"{r['tokens_out']} | {r['latency_ms']} |"
        )
    traces = {
        t.call_log_id: t
        for t in await s.scalars(
            select(AICallTrace).where(AICallTrace.call_log_id.in_([c.id for c in calls] or [0]))
        )
    }
    for cid, t in traces.items():
        out += ["", f"#### Trace of call {cid}", ""]
        for m in t.messages or []:
            out += [f"**{m.get('role')}**", _fence(_clip(m.get("content", "")))]
        out += ["**reply**", _fence(_clip(t.reply or "— (no reply)"))]
        if t.parsed is not None:
            out += ["**parsed JSON**", _fence(_clip(t.parsed))]
        if t.error:
            out += ["**errors**", _fence(_clip(t.error))]
    if not traces:
        out += ["", "_No prompt traces (tracing was off, or they are older than 24 h)._"]
    coins = list(await s.scalars(select(CoinLedger).where(CoinLedger.ref == str(job.id))))
    if coins:
        out += ["", "### Coins", ""]
        out += [f"- {r.kind} {r.bucket} {r.delta:+d} (day {r.day})" for r in coins]
    if job.result is not None:
        out += ["", "### Result", "", _fence(_clip(job.result, 2000))]
    return out


async def _heartbeats(s, start: datetime, end: datetime) -> list[str]:
    rows = list(
        await s.scalars(
            select(WorkerHeartbeat)
            .where(
                WorkerHeartbeat.ts >= start - timedelta(minutes=2),
                WorkerHeartbeat.ts <= end + timedelta(minutes=2),
            )
            .order_by(WorkerHeartbeat.ts)
            .limit(40)
        )
    )
    out = ["## Worker heartbeat around that time", ""]
    if not rows:
        return [*out, "_No heartbeat snapshot in that window (kept 24 h, one per 30 s)._"]
    out.append(
        "| time | worker | in flight i/b | model calls | chat tokens | rpm 60s | provider | "
        "slot | quota | last error |"
    )
    out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for h in rows:
        d = h.data
        lim = d.get("limiter") or {}
        chat = (lim.get("buckets") or {}).get("chat") or {}
        fl = d.get("in_flight") or {}
        err = (d.get("last_error") or {}).get("error", "—")
        out.append(
            f"| {h.ts:%H:%M:%S} | {h.worker_id[-6:]} | {fl.get('interactive', 0)}/"
            f"{fl.get('background', 0)} | {lim.get('active', '?')}/{lim.get('concurrency', '?')} | "
            f"{chat.get('tokens', '?')} | {(lim.get('rpm_last_60s') or {}).get('chat', '?')} | "
            f"{d.get('provider', '?')}{' offline' if d.get('offline') else ''} | "
            f"{'live' if d.get('slot_live') else 'off'} | "
            f"{(d.get('quota') or {}).get('remaining', '—')} | {err} |"
        )
    return out


async def build(
    s, *, job_id: uuid.UUID | None, user: uuid.UUID | None, since: datetime | None
) -> tuple[str, str]:
    """(file name, Markdown)."""
    if not (job_id or user or since):
        raise HTTPException(422, "give job_id, user or since")
    since = since or datetime.now(UTC) - timedelta(hours=1)
    jobs = await _jobs(s, job_id, user, since)
    now = datetime.now(UTC)
    target = (
        f"job {job_id}" if job_id else f"{_who(user)}" if user else f"failures since {since:%H:%M}"
    )
    lines = [
        f"# Debug bundle: {target}",
        "",
        f"Generated {now:%Y-%m-%d %H:%M:%S} UTC. Redacted: no nicknames, keys or tokens. Read "
        "this first, then the docs it names (CLAUDE.md, docs/ARCHITECTURE.md, docs/PLATFORM.md).",
        "",
        f"Jobs: {len(jobs)}",
        "",
    ]
    for job in jobs:
        lines += await _job_section(s, job)
        lines.append("")
    if jobs:
        start = min(j.created_at for j in jobs)
        end = max((j.finished_at or now) for j in jobs)
        lines += await _heartbeats(s, start, end)
        lines.append("")
    students = {j.user_id for j in jobs if j.user_id} | ({user} if user else set())
    for uid in students:
        if await s.get(User, uid) is None:
            continue
        lines += [f"## Invariants for {_who(uid)}", ""]
        for name, rows in (await inv.run(s, uid)).items():
            mark = "pass" if not rows else f"**FAIL** {json.dumps(rows, default=str)[:600]}"
            lines.append(f"- `{name}`: {mark}")
        lines.append("")
    text = "\n".join(lines)
    # every nickname of the students and of their classmates (a result may quote a peer)
    worlds = {j.world_id for j in jobs if j.world_id}
    members = select(WorldMember.user_id).where(WorldMember.world_id.in_(worlds or [uuid.uuid4()]))
    nicks = tuple(
        n
        for n in await s.scalars(
            select(User.nickname).where(
                or_(User.id.in_(students or [uuid.uuid4()]), User.id.in_(members))
            )
        )
        if n
    )
    text = trace.redact(text, nicks)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    key = f"job-{str(job_id)[:8]}" if job_id else f"user-{str(user)[:8]}" if user else "since"
    return f"bundle-{key}-{stamp}.md", text


@router.get("/bundle")
async def bundle(
    _: AdminDep,
    s: Session,
    job_id: uuid.UUID | None = None,
    user: uuid.UUID | None = None,
    since: datetime | None = None,  # ISO time: failed or deferred jobs since then
) -> dict[str, str]:
    name, text = await build(s, job_id=job_id, user=user, since=since)
    return {"name": name, "markdown": text}
