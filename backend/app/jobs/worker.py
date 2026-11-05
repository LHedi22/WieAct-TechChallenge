"""The job runner (one process: `python -m app.worker`).

Postgres is the queue: `SELECT … FOR UPDATE SKIP LOCKED`, interactive lane first, `not_before`
respected. Background jobs in flight are capped at the LLM concurrency so they can never hold every
slot while a student waits; interactive jobs are always claimed. A gateway `Defer` (quota, 503,
network) puts the job back in the queue with `not_before`, and the loading screen shows the ETA.

Leases (audit F-RES-1): a claimed job gets `worker_id` + `lease_until`, renewed every RENEW_S while
this worker runs it. `sweep()` (at boot and every SWEEP_S) fails running jobs whose lease expired,
because their worker died or froze, and refunds them once. A second worker (e.g. during a deploy)
only ever touches expired leases, and a worker that finishes a job after it was swept changes
nothing (its final update requires it to still own the job).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import slot
from app.core.config import get_settings
from app.gateway import Defer, GatewayError, OfflineMode
from app.jobs.coins import coins
from app.jobs.registry import JobContext, spec_for
from app.models import Document, Job

log = logging.getLogger("worker")

MAX_ATTEMPTS = 8  # deferrals included; then the job fails and coins are refunded
LEASE_S = 60.0  # a running job's lease; renewed every RENEW_S by the worker that runs it
RENEW_S = 15.0
SWEEP_S = 30.0  # how often expired leases are looked for while the worker runs
INTERRUPTED = "errors.job_interrupted"


class Worker:
    def __init__(
        self,
        sm: async_sessionmaker[AsyncSession],
        *,
        background_slots: int = 2,
        interactive_slots: int = 6,
        poll_s: float = 0.5,
    ) -> None:
        self.sm = sm
        self.limits = {"interactive": interactive_slots, "background": background_slots}
        self.running: dict[str, set[asyncio.Task]] = {"interactive": set(), "background": set()}
        self.poll_s = poll_s
        self.worker_id = f"{socket.gethostname()[:32]}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.job_ids: set[uuid.UUID] = set()  # jobs this worker is executing (their leases)
        self._renewed_at = self._swept_at = 0.0

    async def claim(self, lane: str) -> Job | None:
        now = datetime.now(UTC)
        async with self.sm() as s:
            pick = (
                select(Job.id)
                .where(
                    Job.status == "queued",
                    Job.lane == lane,
                    or_(Job.not_before.is_(None), Job.not_before <= now),
                )
                .order_by(Job.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = await s.scalar(
                update(Job)
                .where(Job.id == pick.scalar_subquery())
                .values(
                    status="running",
                    started_at=now,
                    attempts=Job.attempts + 1,
                    worker_id=self.worker_id,
                    lease_until=now + timedelta(seconds=LEASE_S),
                )
                .returning(Job)
            )
            await s.commit()
            return job

    async def sweep(self) -> int:
        """Fail running jobs whose lease expired and refund them (exactly once: the job leaves
        `running` in the same transaction, and refunds are unique per job). Rows from older code
        have no lease and count as expired LEASE_S after they started."""
        now = datetime.now(UTC)
        legacy_cutoff = now - timedelta(seconds=LEASE_S)
        async with self.sm() as s:
            dead = list(
                await s.scalars(
                    select(Job)
                    .where(
                        Job.status == "running",
                        or_(
                            Job.lease_until < now,
                            and_(
                                Job.lease_until.is_(None),
                                or_(Job.started_at.is_(None), Job.started_at < legacy_cutoff),
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            for job in dead:
                job.status, job.error, job.finished_at = "failed", INTERRUPTED, now
                await coins.refund(s, job)
                doc_id = (job.payload or {}).get("document_id")
                if job.kind == "INDEX_DOCUMENT" and doc_id:
                    await s.execute(
                        update(Document)
                        .where(Document.id == uuid.UUID(doc_id), Document.status != "ready")
                        .values(status="failed", error="errors.indexing_failed", detail=None)
                    )
                log.warning("job %s (%s) lost its worker; failed and refunded", job.id, job.kind)
            await s.commit()
        return len(dead)

    async def renew(self) -> None:
        """Extend the leases of the jobs this worker is running."""
        if not self.job_ids:
            return
        async with self.sm() as s:
            await s.execute(
                update(Job)
                .where(
                    Job.id.in_(self.job_ids),
                    Job.worker_id == self.worker_id,
                    Job.status == "running",
                )
                .values(lease_until=datetime.now(UTC) + timedelta(seconds=LEASE_S))
            )
            await s.commit()

    async def maintain(self) -> None:
        """Renew own leases and sweep expired ones when due (called from every tick)."""
        now = asyncio.get_running_loop().time()
        if now - self._renewed_at >= RENEW_S:
            self._renewed_at = now
            await self.renew()
        if now - self._swept_at >= SWEEP_S:
            self._swept_at = now
            await self.sweep()

    async def _set_stage(self, job_id: uuid.UUID, stage: str) -> None:
        async with self.sm() as s:
            await s.execute(update(Job).where(Job.id == job_id).values(stage=stage))
            await s.commit()

    async def execute(self, job: Job) -> None:
        ctx = JobContext(
            job_id=job.id,
            kind=job.kind,
            lane=job.lane,
            payload=job.payload or {},
            set_stage=lambda stage: self._set_stage(job.id, stage),
            attempts=job.attempts or 1,
        )
        status, values = "failed", {}
        self.job_ids.add(job.id)
        try:
            result = await spec_for(job.kind).handler(ctx)
            status = "done"
            values = {"result": result, "error": None, "quick_mode": ctx.quick_mode}
        except Defer as d:
            if job.attempts < MAX_ATTEMPTS:
                status = "queued"
                values = {
                    "not_before": datetime.now(UTC) + timedelta(seconds=d.delay_s),
                    "error": f"deferred:{d.reason}",
                }
                log.info("job %s deferred %.0fs (%s)", job.id, d.delay_s, d.reason)
            else:
                values = {"error": d.user_key}
        except OfflineMode as e:
            # Offline demo mode began after the job was queued. A student waiting on a loading
            # screen gets the offline message and a refund; background work waits for the slot.
            nxt = slot.next_slot(datetime.now(UTC), get_settings().LLM_SLOT_GROUP)
            if job.lane == "background" and nxt is not None:
                status = "queued"
                values = {"not_before": nxt.start, "error": "deferred:offline"}
                log.info("job %s waits for the next slot (%s)", job.id, nxt.label())
            else:
                values = {"error": e.user_key}
        except GatewayError as e:
            values = {"error": e.user_key}
            log.warning("job %s failed: %s", job.id, type(e).__name__)
        except Exception:
            values = {"error": "errors.ai_failed"}
            log.exception("job %s crashed", job.id)
        finally:
            self.job_ids.discard(job.id)
        if status in ("done", "failed"):
            values["finished_at"] = datetime.now(UTC)
        if status == "queued":
            values.update(lease_until=None, worker_id=None)
        async with self.sm() as s:
            owned = await s.execute(
                update(Job)
                .where(Job.id == job.id, Job.status == "running", Job.worker_id == self.worker_id)
                .values(status=status, **values)
            )
            if owned.rowcount == 0:  # swept while we worked: already failed and refunded
                log.warning("job %s finished after its lease was swept; result dropped", job.id)
                await s.rollback()
                return
            fresh = await s.get(Job, job.id)
            if status == "done":
                await coins.commit(s, fresh)
            elif status == "failed":
                await coins.refund(s, fresh)
            await s.commit()

    async def tick(self) -> int:
        """Claim as many jobs as lane limits allow; returns how many were started."""
        await self.maintain()
        started = 0
        for lane in ("interactive", "background"):
            while len(self.running[lane]) < self.limits[lane]:
                job = await self.claim(lane)
                if job is None:
                    break
                t = asyncio.create_task(self.execute(job))
                self.running[lane].add(t)
                t.add_done_callback(self.running[lane].discard)
                started += 1
        return started

    async def run_forever(self) -> None:
        swept = await self.sweep()
        if swept:
            log.info("failed and refunded %d jobs left by a dead worker", swept)
        self._swept_at = asyncio.get_running_loop().time()
        while True:
            if not await self.tick():
                await asyncio.sleep(self.poll_s)

    async def drain(self, timeout_s: float = 30) -> None:
        """Tests: run until no queued-and-ready job is left and nothing is running."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await self.tick()
            busy = [t for ts in self.running.values() for t in ts]
            if busy:
                await asyncio.wait(busy, timeout=0.2)
                continue
            async with self.sm() as s:
                now = datetime.now(UTC)
                ready = await s.scalar(
                    select(Job.id)
                    .where(
                        Job.status == "queued",
                        or_(Job.not_before.is_(None), and_(Job.not_before <= now)),
                    )
                    .limit(1)
                )
            if ready is None:
                return
        raise TimeoutError("worker did not drain")
