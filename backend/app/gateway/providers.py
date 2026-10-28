"""Which provider serves this job (ARCHITECTURE.md §Providers). Evaluated per job, so slot
boundaries need no restart.

- cloud / local / mock: as configured.
- auto: cloud while our slot is live, the cloud profile is configured and no 401 "Key is blocked"
  has been logged since the slot started; otherwise local.
- production (cloud only): outside the slot or after a 401 → offline demo mode (cached cloud
  results only, no new calls).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import slot
from app.core.config import LLMProfile, Settings
from app.models import AICallLog


@dataclass(frozen=True)
class Resolution:
    profile: LLMProfile
    offline: bool = False  # True: serve cache only
    reason: str = ""


def slot_live(settings: Settings, now: datetime | None = None) -> tuple[bool, datetime | None]:
    """(live, slot start). LLM_SLOT_FORCE overrides outside production (tests, demos of auto)."""
    now = now or datetime.now(UTC)
    if settings.APP_ENV != "production" and settings.LLM_SLOT_FORCE:
        live = settings.LLM_SLOT_FORCE == "live"
        return live, (now - timedelta(hours=12)) if live else None
    current = slot.current_slot(now, settings.LLM_SLOT_GROUP)
    return (current is not None), (current.start if current else None)


async def cloud_blocked_since(sm: async_sessionmaker[AsyncSession], since: datetime) -> bool:
    async with sm() as s:
        q = select(
            exists().where(
                AICallLog.provider == "cloud",
                AICallLog.status_code == 401,
                AICallLog.ts >= since,
            )
        )
        return bool(await s.scalar(q))


async def resolve(
    settings: Settings, sm: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> Resolution:
    configured = settings.LLM_PROVIDER
    if configured in ("local", "mock"):
        return Resolution(settings.profile_for(configured))

    live, start = slot_live(settings, now)
    blocked = bool(start) and await cloud_blocked_since(sm, start)
    cloud = settings.profile_for("cloud")

    if configured == "cloud":
        if settings.APP_ENV == "production" and (not live or blocked):
            return Resolution(cloud, offline=True, reason="blocked" if blocked else "outside_slot")
        return Resolution(cloud)

    # auto
    if live and settings.cloud_configured and not blocked:
        return Resolution(cloud)
    reason = "blocked" if blocked else ("outside_slot" if not live else "cloud_not_configured")
    return Resolution(settings.profile_for("local"), reason=reason)
