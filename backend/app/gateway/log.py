"""ai_call_log writer: one row per call or cache hit — the same numbers the organisers compute on
our key (calls per model, compact/mid split, tokens, repeats, refusals and how they were handled).
Never stores prompts, headers or keys (prompts go to ai_call_trace, only while tracing is on).

Each row carries the running job and attempt (gateway/context.py); a replay from /admin/debug is
marked `debug` and left out of every metric."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.context import current_job, debug_target
from app.models import AICallLog

log = logging.getLogger("gateway")


async def write(sm: async_sessionmaker[AsyncSession], **fields) -> int | None:
    """Write one row; returns its id (None if it could not be written)."""
    if (ref := current_job.get()) is not None:
        fields.setdefault("job_id", ref.job_id)
        fields.setdefault("attempt", ref.attempt)
    if debug_target.get() is not None:
        fields["debug"] = True
    try:
        async with sm() as s:
            row = AICallLog(**fields)
            s.add(row)
            await s.commit()
            return row.id
    except Exception:  # logging must never fail the user's job
        log.exception("could not write ai_call_log row")
        return None
