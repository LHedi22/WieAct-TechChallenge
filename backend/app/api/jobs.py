import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.jobs import service
from app.jobs.service import JobView, NotCancellable
from app.models import Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _job(s: AsyncSession, job_id: uuid.UUID) -> Job:
    # M3 adds ownership checks once users can sign in; job ids are unguessable UUIDs.
    job = await s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "errors.job_not_found")
    return job


@router.get("/{job_id}", response_model=JobView)
async def get_job(job_id: uuid.UUID, s: Session) -> JobView:
    """Polled by the UI every 1.5 s (no streaming on the platform)."""
    return await service.view(s, await _job(s, job_id))


@router.post("/{job_id}/cancel", response_model=JobView)
async def cancel_job(job_id: uuid.UUID, s: Session) -> JobView:
    """ "Cancel and keep my coins" — only while the job is still in the queue."""
    job = await _job(s, job_id)
    try:
        await service.cancel(s, job)
    except NotCancellable as e:
        raise HTTPException(409, "errors.job_not_cancellable") from e
    return await service.view(s, job)
