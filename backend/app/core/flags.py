"""Runtime switches an admin flips without a restart (`runtime_flags` table, /admin Switches page).

The API and the worker are separate processes, so the switches live in Postgres and both read them
through `load()`, which caches them for TTL_S seconds: a change applies everywhere within ~3 s.
The switches work inside the production guards, never around them:

- `force_quick_until`: until then, interactive mid tasks that allow fallback are answered by the
  compact model as Quick mode (a real call, logged `forced`, counted apart from real fallbacks).
- `offline_demo_mode`: auto (= OFFLINE_DEMO_MODE from the environment) / on / off. The environment
  wins when it says `on`; `off` never makes calls possible where the guards forbid them
  (production outside the slot stays offline).
- `pause_background_lane`: the worker claims no background job; interactive jobs still run.
- `llm_max_rpm_override`: may only lower LLM_MAX_RPM, never raise it.
- `trace_prompts_until`: until then, the gateway stores capped, redacted prompts and replies in
  `ai_call_trace` (gateway/trace.py) for /admin/debug. Off by default; it switches itself off.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import RuntimeFlag

log = logging.getLogger("flags")

TTL_S = 3.0
FORCE_QUICK_MAX_MINUTES = 60
TRACE_MAX_MINUTES = 120
OfflineSetting = Literal["auto", "on", "off"]


class Flags(BaseModel):
    force_quick_until: datetime | None = None
    offline_demo_mode: OfflineSetting = "auto"
    pause_background_lane: bool = False
    llm_max_rpm_override: int | None = Field(None, ge=1)
    trace_prompts_until: datetime | None = None

    def force_quick_active(self, now: datetime | None = None) -> bool:
        if self.force_quick_until is None:
            return False
        return (now or datetime.now(UTC)) < self.force_quick_until

    def trace_active(self, now: datetime | None = None) -> bool:
        if self.trace_prompts_until is None:
            return False
        return (now or datetime.now(UTC)) < self.trace_prompts_until


KEYS: tuple[str, ...] = tuple(Flags.model_fields)
_cache: tuple[float, Flags] | None = None


def invalidate() -> None:
    """Forget the cached flags (this process only; others refresh within TTL_S)."""
    global _cache
    _cache = None


def current() -> Flags:
    """The last flags this process loaded (defaults before the first load). Sync callers only."""
    return _cache[1] if _cache else Flags()


def _parse(rows: dict[str, Any]) -> Flags:
    values: dict[str, Any] = {}
    for key, value in rows.items():
        if key not in KEYS:
            continue
        try:  # one bad row never hides the others
            Flags(**{key: value})
        except ValidationError:
            log.warning("ignoring invalid runtime flag %s", key)
            continue
        values[key] = value
    return Flags(**values)


async def load(sm: async_sessionmaker[AsyncSession], *, fresh: bool = False) -> Flags:
    global _cache
    now = time.monotonic()
    if not fresh and _cache is not None and now - _cache[0] < TTL_S:
        return _cache[1]
    try:
        async with sm() as s:
            rows = {r.key: r.value for r in await s.scalars(select(RuntimeFlag))}
    except Exception:  # a switch must never take the app down: keep the last known values
        log.warning("could not read runtime_flags; using the last known values", exc_info=True)
        return current()
    flags = _parse(rows)
    _cache = (now, flags)
    return flags


async def rows(s: AsyncSession) -> dict[str, RuntimeFlag]:
    return {r.key: r for r in await s.scalars(select(RuntimeFlag))}


async def write(s: AsyncSession, key: str, value: Any, actor: str) -> None:
    """Upsert one switch in the caller's transaction, with its admin_actions row."""
    if key not in KEYS:
        raise KeyError(key)
    stmt = insert(RuntimeFlag).values(key=key, value=value, updated_by=actor)
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=[RuntimeFlag.key],
            set_={
                "value": stmt.excluded.value,
                "updated_by": actor,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    invalidate()


# --- effective values (environment + switches) ------------------------------------------------
def offline_setting(settings: Settings, flags: Flags) -> OfflineSetting:
    """OFFLINE_DEMO_MODE=on in the environment always wins; otherwise a switch set to on/off wins
    over the environment, and auto keeps the environment's value."""
    if settings.OFFLINE_DEMO_MODE == "on":
        return "on"
    if flags.offline_demo_mode != "auto":
        return flags.offline_demo_mode
    return settings.OFFLINE_DEMO_MODE


def force_quick(settings: Settings, flags: Flags, now: datetime | None = None) -> bool:
    """FORCE_QUICK_MODE=on keeps it on for a dev session (production refuses to start with it)."""
    if settings.FORCE_QUICK_MODE == "on" and settings.APP_ENV != "production":
        return True
    return flags.force_quick_active(now)


def max_rpm(settings: Settings, flags: Flags) -> int:
    if flags.llm_max_rpm_override is None:
        return settings.LLM_MAX_RPM
    return max(1, min(settings.LLM_MAX_RPM, flags.llm_max_rpm_override))
