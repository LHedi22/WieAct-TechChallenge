from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.jobs import heartbeat

router = APIRouter(prefix="/api", tags=["system"])

Check = Literal["ok", "error"]
WorkerState = Literal["ok", "stale", "down", "unknown"]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class Health(BaseModel):
    # degraded = the API and database answer but the job worker is not alive (no AI work runs)
    status: Literal["ok", "degraded", "error"]
    db: Check
    qdrant: Check
    worker: WorkerState
    worker_age_s: int | None = None  # seconds since the worker's last heartbeat
    provider: str
    app_env: str


async def check_worker(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> tuple[WorkerState, int | None]:
    try:
        return await heartbeat.worker_status(session)
    except Exception:  # noqa: BLE001 - the db check reports database trouble
        return "unknown", None


async def check_qdrant(settings: SettingsDep) -> Check:
    headers = {}
    if key := settings.QDRANT_API_KEY.get_secret_value():
        headers["api-key"] = key
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{settings.QDRANT_URL.rstrip('/')}/readyz", headers=headers)
        return "ok" if r.status_code == 200 else "error"
    except httpx.HTTPError:
        return "error"


@router.get("/health", response_model=Health)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    qdrant: Annotated[Check, Depends(check_qdrant)],
    worker: Annotated[tuple[WorkerState, int | None], Depends(check_worker)],
    settings: SettingsDep,
    strict: bool = False,
) -> Health:
    """200 unless Postgres is down, so compose's backend healthcheck (which the worker waits on)
    never depends on the worker. `?strict=1` also answers 503 when the worker isn't alive: the
    production watchdog in start-prod.sh uses it to restart a frozen worker."""
    try:
        await session.execute(text("SELECT 1"))
        db: Check = "ok"
    except Exception:
        db = "error"
    # Postgres is required; Qdrant is reported but not fatal.
    worker_state, worker_age = worker
    status = "error" if db != "ok" else ("ok" if worker_state == "ok" else "degraded")
    if db != "ok" or (strict and status != "ok"):
        response.status_code = 503
    return Health(
        status=status,
        db=db,
        qdrant=qdrant,
        worker=worker_state,
        worker_age_s=worker_age,
        provider=settings.llm.provider,
        app_env=settings.APP_ENV,
    )
