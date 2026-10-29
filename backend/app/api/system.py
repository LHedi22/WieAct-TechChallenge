"""Which provider serves AI right now, and whether we are in offline demo mode (banner + disabled
AI actions in the UI). The frontend never talks to the LLM; this is all it learns about it."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.health import SettingsDep
from app.core import slot
from app.core.db import get_sessionmaker
from app.gateway.providers import resolve, slot_live

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemStatus(BaseModel):
    app_env: str
    configured_provider: str  # cloud / local / mock / auto
    provider: str  # what the next job will use
    slot_live: bool
    next_slot: str | None
    offline_demo_mode: bool
    reason: str | None
    upload_max_mb: int


@router.get("/status", response_model=SystemStatus)
async def status(
    settings: SettingsDep,
    sm: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> SystemStatus:
    now = datetime.now(UTC)
    res = await resolve(settings, sm, now)
    live, _ = slot_live(settings, now)
    nxt = slot.next_slot(now, settings.LLM_SLOT_GROUP)
    forced = settings.OFFLINE_DEMO_MODE
    offline = forced == "on" or (forced == "auto" and res.offline)
    return SystemStatus(
        app_env=settings.APP_ENV,
        configured_provider=settings.LLM_PROVIDER,
        provider=res.profile.provider,
        slot_live=live,
        next_slot=nxt.label() if nxt else None,
        offline_demo_mode=offline,
        reason=res.reason or None,
        upload_max_mb=settings.UPLOAD_MAX_MB,
    )
