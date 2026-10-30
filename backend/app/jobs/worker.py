"""The job runner (one process: `python -m app.worker`).

Postgres is the queue: `SELECT … FOR UPDATE SKIP LOCKED`, interactive lane first, `not_before`
respected. Background jobs in flight are capped at the LLM concurrency so they can never hold every
slot while a student waits; interactive jobs are always claimed. A gateway `Defer` (quota, 503,
network) puts the job back in the queue with `not_before`, and the loading screen shows the ETA.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway import Defer, GatewayError
from app.jobs.coins import coins
from app.jobs.registry import JobContext, spec_for
from app.models import Job

log = logging.getLogger("worker")

MAX_ATTEMPTS = 8  # deferrals included; then the job fails and coins are refunded
STALE_AFTER = timedelta(minutes=10)


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
                .values(status="running", started_at=now, attempts=Job.attempts + 1)
                .returning(Job)
            )
            await s.commit()
            return job

    async def recover_stale(self) -> int:
        """Jobs left `running` by a crashed worker go back to the queue."""
        cutoff = datetime.now(UTC) - STALE_AFTER
        async with self.sm() as s:
            res = await s.execute(
                update(Job)
                .where(
                    Job.status == "running", or_(Job.started_at.is_(None), Job.started_at < cutoff)
                )
                .values(status="queued")
            )
            await s.commit()
            return res.rowcount or 0

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
        )
        status, values = "failed", {}
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
        except GatewayError as e:
            values = {"error": e.user_key}
            log.warning("job %s failed: %s", job.id, type(e).__name__)
        except Exception:
            values = {"error": "errors.ai_failed"}
            log.exception("job %s crashed", job.id)
        if status in ("done", "failed"):
            values["finished_at"] = datetime.now(UTC)
        async with self.sm() as s:
            await s.execute(update(Job).where(Job.id == job.id).values(status=status, **values))
            fresh = await s.get(Job, job.id)
            if status == "done":
                await coins.commit(s, fresh)
            elif status == "failed":
                await coins.refund(s, fresh)
            await s.commit()

    async def tick(self) -> int:
        """Claim as many jobs as lane limits allow; returns how many were started."""
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
        recovered = await self.recover_stale()
        if recovered:
            log.info("requeued %d stale jobs", recovered)
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
