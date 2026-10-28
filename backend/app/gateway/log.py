"""ai_call_log writer: one row per call or cache hit — the same numbers the organisers compute on
our key (calls per model, compact/mid split, tokens, repeats, refusals and how they were handled).
Never stores prompts, headers or keys."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AICallLog

log = logging.getLogger("gateway")


async def write(sm: async_sessionmaker[AsyncSession], **fields) -> None:
    try:
        async with sm() as s:
            s.add(AICallLog(**fields))
            await s.commit()
    except Exception:  # logging must never fail the user's job
        log.exception("could not write ai_call_log row")
