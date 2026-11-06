import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.db import get_session
from app.jobs import service
from app.jobs.service import JobView, NotCancellable
from app.models import Job, User, WorldMember

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Class-level work that classmates are attached to (a shared pending pack, the class quiz pool…).
# Their results hold ids and counts, nothing personal. Every other kind is owner-only.
SHARED_KINDS = frozenset(
    {"STUDY_PACK", "AUDIO_EPISODE", "QUIZ_POOL", "PLACEMENT", "INDEX_DOCUMENT", "WISDOM_TIP"}
)


async def _job(s: AsyncSession, job_id: uuid.UUID, user: User, *, cancel: bool = False) -> Job:
    """The job if this user may see it (audit F-ACL-2): its owner, or, for class-level kinds, a
    member of its world. Only the owner may cancel. Anything else is 404 (no existence leak)."""
    job = await s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "errors.job_not_found")
    if job.user_id == user.id:
        return job
    shared = not cancel and job.kind in SHARED_KINDS and job.world_id is not None
    if shared and await s.get(WorldMember, (job.world_id, user.id)) is not None:
        return job
    raise HTTPException(404, "errors.job_not_found")


@router.get("/{job_id}", response_model=JobView)
async def get_job(job_id: uuid.UUID, s: Session, user: CurrentUser) -> JobView:
    """Polled by the UI every 1.5 s (no streaming on the platform)."""
    return await service.view(s, await _job(s, job_id, user))


@router.post("/{job_id}/cancel", response_model=JobView)
async def cancel_job(job_id: uuid.UUID, s: Session, user: CurrentUser) -> JobView:
    """ "Cancel and keep my coins" — only while the job is still in the queue, only by its owner."""
    job = await _job(s, job_id, user, cancel=True)
    try:
        await service.cancel(s, job)
    except NotCancellable as e:
        raise HTTPException(409, "errors.job_not_cancellable") from e
    return await service.view(s, job)
