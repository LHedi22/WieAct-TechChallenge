"""Prompt traces for /admin/debug (`ai_call_trace`), privacy first (DECISIONS.md 2026-11-09).

- Written only while the runtime switch `trace_prompts_until` is in the future (an admin turns it
  on for N minutes, at most TRACE_MAX_MINUTES; it switches itself off).
- Each field is capped at FIELD_CAP characters.
- Anything shaped like a bearer token, an API key or a secret assignment is replaced by
  [redacted], and so is the nickname of the job's student (prompts never carry nicknames by design,
  this is the safety net).
- The worker deletes rows older than RETENTION_H.
- Never raises: tracing must not fail a student's job.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.context import current_job

log = logging.getLogger("gateway")

FIELD_CAP = 16_000  # characters per field (messages are capped as a whole)
RETENTION_H = 24
REDACTED = "[redacted]"
_SECRETS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?:ghp|gho|xox[abp])_?[A-Za-z0-9-]{16,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|admin[_-]?token|secret[_-]?key|password|authorization)"
        r"(\s*[:=]\s*)[\"']?[^\s\"',}]{4,}"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
)


def known_secrets() -> tuple[str, ...]:
    """The configured keys and tokens themselves, so a key in any format is caught."""
    from app.core.config import get_settings  # noqa: PLC0415

    s = get_settings()
    raw = [s.profile_for(p).api_key for p in ("cloud", "local", "mock")]  # type: ignore[arg-type]
    raw += [s.ADMIN_TOKEN, s.SECRET_KEY]
    values = [v.get_secret_value() if hasattr(v, "get_secret_value") else v for v in raw]
    return tuple(v for v in values if isinstance(v, str) and len(v) >= 8)


def redact(text: str, names: tuple[str, ...] = (), secrets: tuple[str, ...] | None = None) -> str:
    for value in known_secrets() if secrets is None else secrets:
        text = text.replace(value, REDACTED)
    for rx in _SECRETS:
        if rx.groups >= 2:
            text = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = rx.sub(REDACTED, text)
    for name in names:
        if name and len(name) >= 3:  # whole words only: "Sam" leaves "same" alone
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "[student]", text, flags=re.I)
    return text


def cap(text: str | None, limit: int = FIELD_CAP) -> str | None:
    if text is None or len(text) <= limit:
        return text
    cut = len(text) - limit
    return f"{text[:limit]}… [truncated {cut} chars]"


def cap_messages(
    messages: list[dict[str, Any]], names: tuple[str, ...] = (), limit: int = FIELD_CAP
) -> list[dict[str, str]]:
    """Role + redacted content of each message, the whole list within `limit` characters: each
    message gets an equal share of the budget, and a short one leaves its rest to the others."""
    texts = [redact(str(m.get("content", "")), names) for m in messages]
    roles = [str(m.get("role", "?"))[:16] for m in messages]
    budget, out = limit, []
    for i, text in enumerate(texts):
        share = budget // max(1, len(texts) - i)
        piece = cap(text, share) or ""
        budget -= min(len(text), share)
        out.append({"role": roles[i], "content": piece})
    return out


def cap_json(value: Any, names: tuple[str, ...] = ()) -> Any:
    """Parsed JSON as stored: redacted, and replaced by a capped string if it is too large."""
    if value is None:
        return None
    text = redact(json.dumps(value, ensure_ascii=False, default=str), names)
    if len(text) > FIELD_CAP:
        return {"_truncated": cap(text)}
    try:
        return json.loads(text)
    except ValueError:  # a redaction broke the JSON: keep it as text
        return {"_text": text}


async def _names(s: AsyncSession) -> tuple[str, ...]:
    ref = current_job.get()
    if ref is None or ref.user_id is None:
        return ()
    from app.models import User  # noqa: PLC0415

    nick = await s.scalar(select(User.nickname).where(User.id == ref.user_id))
    return (nick,) if nick else ()


async def write(
    sm: async_sessionmaker[AsyncSession],
    call_log_id: int | None,
    *,
    messages: list[dict[str, Any]],
    reply: str | None = None,
    parsed: Any = None,
    error: str | None = None,
) -> None:
    if call_log_id is None:
        return
    from app.models import AICallTrace  # noqa: PLC0415

    try:
        async with sm() as s:
            names = await _names(s)
            s.add(
                AICallTrace(
                    call_log_id=call_log_id,
                    messages=cap_messages(messages, names),
                    reply=cap(redact(reply, names)) if reply is not None else None,
                    parsed=cap_json(parsed, names),
                    error=cap(redact(error, names), 2000) if error else None,
                )
            )
            await s.commit()
    except Exception:  # noqa: BLE001 - tracing must never fail the user's job
        log.warning("could not write ai_call_trace row", exc_info=True)


async def note_job_error(sm: async_sessionmaker[AsyncSession], job_id, error: str) -> None:
    """Attach why a job failed (e.g. its reply failed validation) to the trace of its last call,
    when that call was traced. Nothing is written when no trace exists."""
    from app.models import AICallLog, AICallTrace  # noqa: PLC0415

    try:
        async with sm() as s:
            last = await s.scalar(
                select(AICallTrace)
                .join(AICallLog, AICallLog.id == AICallTrace.call_log_id)
                .where(AICallLog.job_id == job_id)
                .order_by(AICallLog.id.desc())
                .limit(1)
            )
            if last is None:
                return
            names = await _names(s)
            note = cap(redact(f"job failed: {error}", names), 2000)
            last.error = f"{last.error}\n{note}" if last.error else note
            await s.commit()
    except Exception:  # noqa: BLE001
        log.warning("could not note a job error on its trace", exc_info=True)


async def cleanup(sm: async_sessionmaker[AsyncSession], now: datetime | None = None) -> int:
    """Delete traces older than RETENTION_H, and replay jobs (payload or result hold prompt
    text) of the same age; returns how many traces were deleted."""
    from app.models import AICallTrace, Job  # noqa: PLC0415

    cutoff = (now or datetime.now(UTC)) - timedelta(hours=RETENTION_H)
    async with sm() as s:
        res = await s.execute(delete(AICallTrace).where(AICallTrace.created_at < cutoff))
        await s.execute(
            # any status: a replay stuck in the queue still holds an edited prompt
            delete(Job).where(Job.kind == "DEBUG_REPLAY", Job.created_at < cutoff)
        )
        await s.commit()
        return res.rowcount or 0
