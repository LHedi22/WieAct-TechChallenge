"""Runtime switches (core/flags.py): read and flip them; every change writes admin_actions.

The provider is shown read-only: provider switching never appears on the admin side (production
runs on the platform only; in development the top bar's switch already exists)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.admin import audit
from app.admin.auth import AdminActionDep, AdminDep
from app.api.deps import Session
from app.api.health import SettingsDep
from app.core import flags, slot
from app.core.db import get_sessionmaker
from app.gateway.providers import paused_until, resolve
from app.models import Job

router = APIRouter()
Sessionmaker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
SwitchKey = Literal[
    "force_quick_mode", "offline_demo_mode", "pause_background_lane", "llm_max_rpm_override"
]
STORED = {  # API key → runtime_flags key
    "force_quick_mode": "force_quick_until",
    "offline_demo_mode": "offline_demo_mode",
    "pause_background_lane": "pause_background_lane",
    "llm_max_rpm_override": "llm_max_rpm_override",
}


class Switch(BaseModel):
    key: SwitchKey
    value: Any  # what the admin set (None = never set: the default applies)
    effective: Any  # what the app does now, environment included
    env_note: str | None  # e.g. "OFFLINE_DEMO_MODE=on in the environment wins"
    updated_at: datetime | None
    updated_by: str | None


class Switches(BaseModel):
    switches: list[Switch]
    app_env: str
    configured_provider: str  # read-only: LLM_PROVIDER
    provider: str  # read-only: what the next job uses
    offline_now: bool
    llm_max_rpm: int  # the configured ceiling an override may only lower
    force_quick_max_minutes: int


class SwitchIn(BaseModel):
    # force_quick_mode: minutes (0 = off) · offline_demo_mode: auto|on|off ·
    # pause_background_lane: bool · llm_max_rpm_override: int or null (= configured rate)
    value: Any = None
    reason: str | None = Field(None, max_length=500)


def _validate(key: SwitchKey, value: Any, settings) -> Any:
    """The stored value for `key`, or 422 with a plain message."""
    if key == "force_quick_mode":
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(422, "force_quick_mode takes minutes (0 = off)")
        if not 0 <= value <= flags.FORCE_QUICK_MAX_MINUTES:
            raise HTTPException(422, f"0 to {flags.FORCE_QUICK_MAX_MINUTES} minutes")
        return (datetime.now(UTC) + timedelta(minutes=value)).isoformat() if value else None
    if key == "offline_demo_mode":
        if value not in ("auto", "on", "off"):
            raise HTTPException(422, "offline_demo_mode is auto, on or off")
        return value
    if key == "pause_background_lane":
        if not isinstance(value, bool):
            raise HTTPException(422, "pause_background_lane is true or false")
        return value
    # llm_max_rpm_override: only ever lowers the configured rate
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(422, "llm_max_rpm_override is a whole number or null")
    if not 1 <= value <= settings.LLM_MAX_RPM:
        raise HTTPException(
            422, f"llm_max_rpm_override may only lower LLM_MAX_RPM (1 to {settings.LLM_MAX_RPM})"
        )
    return value


async def _view(s: AsyncSession, settings, sm) -> Switches:
    stored = await flags.rows(s)
    current = await flags.load(sm, fresh=True)
    res = await resolve(settings, sm)
    effective: dict[str, Any] = {
        "force_quick_mode": flags.force_quick(settings, current),
        "offline_demo_mode": flags.offline_setting(settings, current),
        "pause_background_lane": current.pause_background_lane,
        "llm_max_rpm_override": flags.max_rpm(settings, current),
    }
    notes: dict[str, str | None] = {
        "force_quick_mode": "FORCE_QUICK_MODE=on in the environment keeps it on"
        if settings.FORCE_QUICK_MODE == "on" and settings.APP_ENV != "production"
        else None,
        "offline_demo_mode": "OFFLINE_DEMO_MODE=on in the environment wins"
        if settings.OFFLINE_DEMO_MODE == "on"
        else f"auto = environment ({settings.OFFLINE_DEMO_MODE})",
        "pause_background_lane": None,
        "llm_max_rpm_override": f"configured rate: {settings.LLM_MAX_RPM} per minute",
    }
    out = []
    for key, flag in STORED.items():
        row = stored.get(flag)
        out.append(
            Switch(
                key=key,  # type: ignore[arg-type]
                value=row.value if row else None,
                effective=effective[key],
                env_note=notes[key],
                updated_at=row.updated_at if row else None,
                updated_by=row.updated_by if row else None,
            )
        )
    return Switches(
        switches=out,
        app_env=settings.APP_ENV,
        configured_provider=settings.LLM_PROVIDER,
        provider=res.profile.provider,
        offline_now=res.offline,
        llm_max_rpm=settings.LLM_MAX_RPM,
        force_quick_max_minutes=flags.FORCE_QUICK_MAX_MINUTES,
    )


@router.get("/switches", response_model=Switches)
async def read_switches(_: AdminDep, s: Session, settings: SettingsDep, sm: Sessionmaker):
    return await _view(s, settings, sm)


@router.put("/switches/{key}", response_model=Switches)
async def set_switch(
    key: SwitchKey,
    body: SwitchIn,
    admin: AdminActionDep,
    s: Session,
    settings: SettingsDep,
    sm: Sessionmaker,
) -> Switches:
    value = _validate(key, body.value, settings)
    flag = STORED[key]
    before = (await flags.rows(s)).get(flag)
    await flags.write(s, flag, value, admin.actor)
    audit.record(
        s,
        admin,
        "switch.set",
        target_kind="switch",
        target_id=key,
        before=before.value if before else None,
        after=value,
        reason=body.reason,
    )
    await s.commit()
    flags.invalidate()
    if key == "offline_demo_mode":
        await _release_offline_waits(s, admin, settings, sm)
    return await _view(s, settings, sm)


async def _release_offline_waits(s: AsyncSession, admin, settings, sm) -> None:
    """Offline parks background jobs until the next slot (`not_before` = its start). When the
    switch ends the pause, they run now instead of waiting for that slot. Quota and saturation
    waits (error `deferred:quota` …) and other planned delays keep their `not_before`."""
    offline, _ = await paused_until(settings, sm)
    if offline:
        return
    now = datetime.now(UTC)
    nxt = slot.next_slot(now, settings.LLM_SLOT_GROUP)
    parked = Job.error == "deferred:offline"
    if nxt is not None:  # queued while offline: create_job set not_before to the slot start
        parked = or_(parked, and_(Job.error.is_(None), Job.not_before == nxt.start))
    res = await s.execute(
        update(Job)
        .where(Job.status == "queued", Job.lane == "background", Job.not_before > now, parked)
        .values(not_before=None, error=None)
        .returning(Job.id)
    )
    released = [str(i) for i in res.scalars()]
    if released:
        audit.record(
            s,
            admin,
            "jobs.release_offline",
            target_kind="job",
            target_id=None,
            before={"waiting_for_slot": len(released)},
            after={"released": len(released)},
            reason="offline demo mode switched off",
        )
    await s.commit()


# --- the force-Quick endpoints of VIDEO.md's curl (kept; now backed by the switch) ----------
class ForceQuickIn(BaseModel):
    minutes: int = Field(ge=1, le=flags.FORCE_QUICK_MAX_MINUTES)


class ForceQuickOut(BaseModel):
    active: bool
    until: datetime | None


async def _force_quick_out(sm, settings) -> ForceQuickOut:
    current = await flags.load(sm, fresh=True)
    on = flags.force_quick(settings, current)
    return ForceQuickOut(active=on, until=current.force_quick_until if on else None)


@router.get("/force-quick", response_model=ForceQuickOut)
async def force_quick_state(_: AdminDep, settings: SettingsDep, sm: Sessionmaker):
    return await _force_quick_out(sm, settings)


@router.post("/force-quick", response_model=ForceQuickOut)
async def force_quick_on(
    body: ForceQuickIn, admin: AdminActionDep, s: Session, settings: SettingsDep, sm: Sessionmaker
) -> ForceQuickOut:
    await set_switch("force_quick_mode", SwitchIn(value=body.minutes), admin, s, settings, sm)
    return await _force_quick_out(sm, settings)


@router.delete("/force-quick", response_model=ForceQuickOut)
async def force_quick_off(
    admin: AdminActionDep, s: Session, settings: SettingsDep, sm: Sessionmaker
) -> ForceQuickOut:
    await set_switch("force_quick_mode", SwitchIn(value=0), admin, s, settings, sm)
    return await _force_quick_out(sm, settings)
