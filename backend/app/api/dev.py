"""Dev-only endpoints (not mounted in production)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.db import get_session
from app.features.worlds.service import NotFound, member_world
from app.jobs import demo, service

router = APIRouter(prefix="/api/dev", tags=["dev"])


class DemoJobIn(BaseModel):
    lane: Literal["interactive", "background"] = "interactive"
    language: Literal["en", "fr", "ar", "ar-TN"] = "en"
    cache_key: str | None = Field(None, description="set to make the result shareable/cached")


class JobCreated(BaseModel):
    job_id: str
    cost: int
    cached: bool


@router.post("/demo-jobs", response_model=JobCreated, status_code=202)
async def create_demo_job(
    body: DemoJobIn, s: Annotated[AsyncSession, Depends(get_session)]
) -> JobCreated:
    job = await service.create_job(
        s,
        kind=demo.KIND,
        lane=body.lane,
        payload={"language": body.language, "cache_key": body.cache_key},
    )
    return JobCreated(job_id=str(job.id), cost=job.cost, cached=False)


class SearchIn(BaseModel):
    world_id: uuid.UUID
    query: str = Field(min_length=1, max_length=300)
    k: int = Field(8, ge=1, le=20)


@router.post("/search-jobs", response_model=JobCreated, status_code=202)
async def create_search_job(
    body: SearchIn, s: Annotated[AsyncSession, Depends(get_session)], user: CurrentUser
) -> JobCreated:
    """Vector search in a world (the M2 Done-when check); poll GET /api/jobs/{id} for hits."""
    try:
        await member_world(s, user, body.world_id)
    except NotFound as e:
        raise HTTPException(404, e.key) from e
    job = await service.create_job(
        s,
        kind="DEV_SEARCH",
        lane="interactive",
        payload={"world_id": str(body.world_id), "query": body.query, "k": body.k},
        user_id=user.id,
        world_id=body.world_id,
    )
    return JobCreated(job_id=str(job.id), cost=0, cached=False)
