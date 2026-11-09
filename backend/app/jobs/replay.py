"""DEBUG_REPLAY job: rerun one traced call on mock or local, optionally with an edited prompt.

A job like every AI action (the gateway's limiter lives in the worker). The gateway itself refuses a
replay whose target is cloud or that runs in production (gateway/context.py `debug_target`), never
reads or writes the cache, and marks the log rows `debug`, so /api/admin/stats, export_stats.py and
the routing check never count them. A replay to the platform would be a repeated identical
request on our key: that is why there is no way to send one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import update

from app import gateway
from app.core.db import get_sessionmaker
from app.gateway import Task, TaskKind
from app.gateway.context import debug_target
from app.jobs.registry import JobContext, job
from app.models import Job

KIND = "DEBUG_REPLAY"
TARGETS = ("mock", "local")


@job(KIND, stages=("replaying",))
async def replay(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    target = p.get("target")
    if target not in TARGETS:
        raise gateway.RequestRejected("replays run on mock or local only", refusal="debug_cloud")
    await ctx.set_stage("replaying")
    messages = p["messages"]
    # The prompt (course text, student answers) leaves the job row once read; the job and its
    # result are deleted with the traces after 24 h (gateway/trace.py cleanup).
    async with get_sessionmaker()() as s:
        kept = {k: v for k, v in p.items() if k != "messages"}
        await s.execute(update(Job).where(Job.id == ctx.job_id).values(payload=kept))
        await s.commit()
    token = debug_target.set(target)
    try:
        result = await gateway.run(
            Task(
                kind=TaskKind(p["task_kind"]),
                lane="interactive",
                messages=messages,
                language=p.get("language") or "en",
                cache_key=None,  # never from or into the class cache
                response_format=p.get("response_format", "json"),
                tier=p.get("tier"),
                allow_fallback=False,  # show what this tier answers, no Quick mode
            )
        )
    except gateway.Defer as d:
        # the prompt already left the payload: fail now rather than come back without it
        raise gateway.RequestRejected(
            f"the {target} model was busy ({d.reason}): replay again", refusal="debug_deferred"
        ) from d
    finally:
        debug_target.reset(token)
    return {
        "call_log_id": p.get("call_log_id"),
        "target": target,
        "content": result.content,
        "model": result.model,
        "model_tier": result.model_tier,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
        "notes": result.notes,
    }
