"""Dev-only endpoints (not mounted in production)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
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
