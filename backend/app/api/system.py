"""Which provider serves AI right now, and whether we are in offline demo mode (banner + disabled
AI actions in the UI). The frontend never talks to the LLM; this is all it learns about it.

Development only: PUT /api/system/provider picks the competition platform ("cloud") or our own
Ollama ("local") at runtime (`core/provider_choice.py`) and queues a REFRESH_CONTENT job that
re-tags and re-indexes the class material with it (`rag/refresh.py`)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import CurrentUser, Session
from app.api.health import SettingsDep
from app.core import flags, provider_choice, slot
from app.core.db import get_sessionmaker
from app.core.provider_choice import Choice
from app.gateway.providers import paused_until, resolve, slot_live
from app.jobs.service import AIPaused, create_job
from app.models import Job
from app.rag.refresh import KIND as REFRESH_KIND

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemStatus(BaseModel):
    app_env: str
    configured_provider: str  # cloud / local / mock / auto
    provider: str  # what the next job will use
    provider_choice: str | None  # cloud / local picked in the UI (development), None = .env
    can_choose_provider: bool  # development only
    cloud_configured: bool  # the platform key and URL are set (never the key itself)
    slot_live: bool
    next_slot: str | None
    next_slot_start: datetime | None  # the banner shows it in the student's own locale
    offline_demo_mode: bool
    reason: str | None
    upload_max_mb: int
    quick_mode_forced: bool  # admin switch: interactive mid answers come as Quick mode
    background_paused: bool  # admin switch: background work (tagging, tips, plans) waits


class ProviderIn(BaseModel):
    provider: Choice


class ProviderOut(BaseModel):
    provider_choice: str
    refresh_job_id: str | None  # re-tagging / re-indexing the class material (None: paused)


Sessionmaker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]


@router.get("/status", response_model=SystemStatus)
async def status(settings: SettingsDep, sm: Sessionmaker) -> SystemStatus:
    now = datetime.now(UTC)
    res = await resolve(settings, sm, now)
    live, _ = slot_live(settings, now)
    nxt = slot.next_slot(now, settings.LLM_SLOT_GROUP)
    switches = await flags.load(sm)
    forced = flags.offline_setting(settings, switches)
    chosen = provider_choice.get()
    # A provider picked in the UI is paused whenever it can't run, whatever OFFLINE_DEMO_MODE says
    # "off" (environment or admin switch) never hides a pause the guards impose: production
    # outside the slot or a blocked key still shows the banner and disables AI actions
    offline = forced == "on" or res.offline
    return SystemStatus(
        app_env=settings.APP_ENV,
        configured_provider=settings.LLM_PROVIDER,
        provider=res.profile.provider,
        provider_choice=chosen,
        can_choose_provider=settings.APP_ENV != "production",
        cloud_configured=settings.cloud_configured,
        slot_live=live,
        next_slot=nxt.label() if nxt else None,
        next_slot_start=nxt.start if nxt else None,
        offline_demo_mode=offline,
        reason=res.reason or None,
        upload_max_mb=settings.UPLOAD_MAX_MB,
        quick_mode_forced=flags.force_quick(settings, switches),
        background_paused=switches.pause_background_lane,
    )


@router.put("/provider", response_model=ProviderOut)
async def choose_provider(
    body: ProviderIn, settings: SettingsDep, sm: Sessionmaker, s: Session, user: CurrentUser
) -> ProviderOut:
    if settings.APP_ENV == "production":  # the platform only; nothing to choose
        raise HTTPException(403, "errors.forbidden")
    provider_choice.set_choice(body.provider)
    _, resume_at = await paused_until(settings, sm)
    queued = await s.scalar(
        select(Job).where(Job.kind == REFRESH_KIND, Job.status == "queued").limit(1)
    )
    if queued is not None:  # one refresh is enough: it reads the choice when it runs
        queued.not_before = resume_at
        await s.commit()
        return ProviderOut(provider_choice=body.provider, refresh_job_id=str(queued.id))
    try:
        job = await create_job(s, kind=REFRESH_KIND, lane="background", user_id=user.id)
    except AIPaused:  # no next slot to wait for: the refresh is queued by the next switch
        return ProviderOut(provider_choice=body.provider, refresh_job_id=None)
    return ProviderOut(provider_choice=body.provider, refresh_job_id=str(job.id))
