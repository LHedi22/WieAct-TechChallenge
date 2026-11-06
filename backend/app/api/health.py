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
EmbedCheck = Literal["ok", "error", "skipped"]  # skipped: the platform's metered endpoint
WorkerState = Literal["ok", "stale", "down", "unknown"]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class Health(BaseModel):
    # degraded = the API and database answer but something AI starts need is out: the job
    # worker, Qdrant or the embeddings model (audit N-8). `ready` = all of them are up.
    status: Literal["ok", "degraded", "error"]
    ready: bool
    db: Check
    qdrant: Check
    embeddings: EmbedCheck
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


async def probe_embeddings(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> EmbedCheck:
    """Our own embeddings model (Ollama bge-m3, or the mock) answers GET {base}/models. The
    platform is never probed: every request there uses a unit of the metered quota."""
    profile = settings.embed_profile() or settings.llm
    if profile.provider == "cloud":
        return "skipped"
    try:
        async with httpx.AsyncClient(timeout=2, transport=transport) as client:
            r = await client.get(f"{profile.base_url.rstrip('/')}/models")
        return "ok" if r.status_code == 200 else "error"
    except httpx.HTTPError:
        return "error"


async def check_embeddings(settings: SettingsDep) -> EmbedCheck:
    return await probe_embeddings(settings)


async def _health(response, session, qdrant, embeddings, worker, settings, *, need: str) -> Health:
    try:
        await session.execute(text("SELECT 1"))
        db: Check = "ok"
    except Exception:
        db = "error"
    worker_state, worker_age = worker
    ready = db == "ok" and qdrant == "ok" and embeddings != "error" and worker_state == "ok"
    status = "error" if db != "ok" else ("ok" if ready else "degraded")
    if db != "ok" or (need == "worker" and worker_state != "ok") or (need == "ready" and not ready):
        response.status_code = 503
    return Health(
        status=status,
        ready=ready,
        db=db,
        qdrant=qdrant,
        embeddings=embeddings,
        worker=worker_state,
        worker_age_s=worker_age,
        provider=settings.llm.provider,
        app_env=settings.APP_ENV,
    )


@router.get("/health/ready", response_model=Health)
async def ready(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    qdrant: Annotated[Check, Depends(check_qdrant)],
    embeddings: Annotated[EmbedCheck, Depends(check_embeddings)],
    worker: Annotated[tuple[WorkerState, int | None], Depends(check_worker)],
    settings: SettingsDep,
) -> Health:
    """Readiness (audit N-8): 503 while anything an AI start needs is out (database, Qdrant,
    embeddings, worker). For load balancers and monitoring, never for restarts: an outage of a
    dependency is not fixed by restarting the app."""
    return await _health(response, session, qdrant, embeddings, worker, settings, need="ready")


@router.get("/health", response_model=Health)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    qdrant: Annotated[Check, Depends(check_qdrant)],
    embeddings: Annotated[EmbedCheck, Depends(check_embeddings)],
    worker: Annotated[tuple[WorkerState, int | None], Depends(check_worker)],
    settings: SettingsDep,
    strict: bool = False,
) -> Health:
    """Liveness: 200 unless Postgres is down, so compose's backend healthcheck (which the worker
    waits on) and Railway's never depend on the worker, Qdrant or embeddings; the body still says
    "degraded" when one of them is out (audit N-8). `?strict=1` also answers 503 when the worker
    isn't alive: the production watchdog in start-prod.sh uses it to restart a frozen worker.
    It deliberately ignores Qdrant and embeddings, so their outage never causes a restart loop."""
    need = "worker" if strict else "db"
    return await _health(response, session, qdrant, embeddings, worker, settings, need=need)
