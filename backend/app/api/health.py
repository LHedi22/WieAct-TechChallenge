from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session

router = APIRouter(prefix="/api", tags=["system"])

Check = Literal["ok", "error"]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class Health(BaseModel):
    status: Check
    db: Check
    qdrant: Check
    provider: str
    app_env: str


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
    settings: SettingsDep,
) -> Health:
    try:
        await session.execute(text("SELECT 1"))
        db: Check = "ok"
    except Exception:
        db = "error"
    # Postgres is required; Qdrant is reported but not fatal until RAG lands (M2).
    if db != "ok":
        response.status_code = 503
    return Health(
        status="ok" if db == "ok" else "error",
        db=db,
        qdrant=qdrant,
        provider=settings.llm.provider,
        app_env=settings.APP_ENV,
    )
