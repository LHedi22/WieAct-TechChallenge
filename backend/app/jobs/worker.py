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

Debugger (/admin/debug): every job keeps a timeline in `jobs.events` (claimed, stage, deferred,
requeued, done, failed, swept); each gateway call carries the job id and attempt through
`gateway.context.current_job`; every STATUS_S the worker rewrites its `worker_status` row (lanes,
limiter, provider, slot, quota, last error); old prompt traces are deleted every TRACE_CLEANUP_S.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy import and_, delete, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import economy_live, flags, slot
from app.core.config import get_settings
from app.gateway import Defer, EmbeddingsDown, GatewayError, OfflineMode, trace
from app.gateway.context import JobRef, current_job
from app.gateway.providers import paused_until, resolve
from app.jobs.coins import coins
from app.jobs.registry import JobContext, spec_for
from app.models import Document, Job, WorkerHeartbeat, WorkerStatus

log = logging.getLogger("worker")

MAX_ATTEMPTS = 8  # deferrals included; then the job fails and coins are refunded
LEASE_S = 60.0  # a running job's lease; renewed every RENEW_S by the worker that runs it
RENEW_S = 15.0
SWEEP_S = 30.0  # how often expired leases are looked for while the worker runs
INTERRUPTED = "errors.job_interrupted"
# A database restart (audit N-7): the loop backs off and reconnects instead of exiting; after
# DB_OUTAGE_LIMIT_S without the database it exits, so the supervisor (Railway, compose) restarts it.
DB_RETRY_S = (1, 2, 4, 8, 15, 30)
DB_OUTAGE_LIMIT_S = 300.0
DB_ERRORS = (DBAPIError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError)
STATUS_S = 2.0  # worker_status heartbeat for /admin/debug
STATUS_STALE_S = 3600  # rows of workers gone for this long are deleted
HISTORY_S = 30.0  # a worker_heartbeats snapshot (kept HISTORY_KEEP_H) for debug bundles
HISTORY_KEEP_H = 24
TRACE_CLEANUP_S = 600.0


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def event(kind: str, **fields) -> object:
    """An SQL expression appending one {t, type, …} entry to jobs.events."""
    entry = {"t": _ts(), "type": kind, **{k: v for k, v in fields.items() if v is not None}}
    return Job.events.op("||")(literal([entry], type_=JSONB))


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
        self._status_at = self._traces_at = self._history_at = float("-inf")
        self.last_error: dict[str, str] | None = None
        self.started = _ts()

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
                    events=event("claimed", worker=self.worker_id),
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
                job.events = [
                    *(job.events or []),
                    {"t": _ts(), "type": "swept", "error": INTERRUPTED},
                ]
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
        # Debugger housekeeping: a failure here is logged, never allowed to stop job processing.
        if now - self._status_at >= STATUS_S:
            self._status_at = now
            try:
                await self.write_status()
            except Exception:  # noqa: BLE001
                log.warning("could not write worker_status", exc_info=True)
        if now - self._traces_at >= TRACE_CLEANUP_S:
            self._traces_at = now
            try:
                if removed := await trace.cleanup(self.sm):
                    log.info("deleted %d prompt traces older than %dh", removed, trace.RETENTION_H)
            except Exception:  # noqa: BLE001
                log.warning("could not clean up prompt traces", exc_info=True)

    def _gateway(self):
        gw = getattr(self, "gateway", None)
        if gw is None:
            from app.gateway import get_gateway  # noqa: PLC0415

            gw = get_gateway()
        return gw

    async def status(self) -> dict:
        """This worker's live state for /admin/debug (written to worker_status)."""
        settings = get_settings()
        data: dict = {
            "worker_id": self.worker_id,
            "started_at": self.started,
            "in_flight": {lane: len(ts) for lane, ts in self.running.items()},
            "lane_limits": dict(self.limits),
            "job_ids": sorted(str(j) for j in self.job_ids),
            "last_error": self.last_error,
        }
        try:
            gw = self._gateway()
            data["limiter"] = gw.limiter.snapshot()
            res = await resolve(settings, self.sm)
            data["provider"] = res.profile.provider
            data["offline"] = res.offline
            data["offline_reason"] = res.reason or None
            q = gw.quota.get(res.profile.provider)
            data["quota"] = {
                "remaining": q.remaining,
                "reset_s": q.reset_s,
                "low": q.low,
                "background_pause_s": round(gw._background_pause(), 1),
            }
        except Exception as e:  # noqa: BLE001 - the heartbeat reports, it never fails the loop
            data["status_error"] = type(e).__name__
        now = datetime.now(UTC)
        data["slot_live"] = slot.current_slot(now, settings.LLM_SLOT_GROUP) is not None
        current = await flags.load(self.sm)
        data["flags"] = {
            "force_quick": flags.force_quick(settings, current),
            "offline_demo_mode": flags.offline_setting(settings, current),
            "pause_background_lane": current.pause_background_lane,
            "llm_max_rpm": flags.max_rpm(settings, current),
            "trace_prompts": current.trace_active(),
        }
        return data

    async def write_status(self) -> None:
        data = await self.status()
        now = datetime.now(UTC)
        async with self.sm() as s:
            stmt = insert(WorkerStatus).values(worker_id=self.worker_id, data=data, updated_at=now)
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=[WorkerStatus.worker_id],
                    set_={"data": stmt.excluded.data, "updated_at": now},
                )
            )
            await s.execute(
                delete(WorkerStatus).where(
                    WorkerStatus.updated_at < now - timedelta(seconds=STATUS_STALE_S)
                )
            )
            loop_now = asyncio.get_running_loop().time()
            if loop_now - self._history_at >= HISTORY_S:
                self._history_at = loop_now
                s.add(WorkerHeartbeat(worker_id=self.worker_id, ts=now, data=data))
                await s.execute(
                    delete(WorkerHeartbeat).where(
                        WorkerHeartbeat.ts < now - timedelta(hours=HISTORY_KEEP_H)
                    )
                )
            await s.commit()

    async def _set_stage(self, job_id: uuid.UUID, stage: str) -> None:
        async with self.sm() as s:
            await s.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(stage=stage, events=event("stage", stage=stage))
            )
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
        detail: str | None = None  # why it failed, for the trace of its last call
        self.job_ids.add(job.id)
        token = current_job.set(JobRef(job.id, job.attempts or 1, job.user_id))
        try:
            result = await spec_for(job.kind).handler(ctx)
            status = "done"
            values = {"result": result, "error": None, "quick_mode": ctx.quick_mode}
        except Defer as d:
            if isinstance(d, EmbeddingsDown) and job.lane == "interactive":
                # audit N-9: the embeddings endpoint is down; a student isn't kept waiting
                # through cooldowns, and no call is spent: fail now, coins refunded.
                values = {"error": d.user_key}
                log.info("job %s failed fast: embeddings breaker open", job.id)
            elif job.attempts < MAX_ATTEMPTS:
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
            await flags.load(self.sm, fresh=True)  # the admin switch may have ended it < 3 s ago
            if job.attempts < MAX_ATTEMPTS and not (await paused_until(get_settings(), self.sm))[0]:
                status = "queued"
                values = {"not_before": None, "error": None}
                log.info("job %s requeued: offline demo mode just ended", job.id)
            elif job.lane == "background" and nxt is not None:
                status = "queued"
                values = {"not_before": nxt.start, "error": "deferred:offline"}
                log.info("job %s waits for the next slot (%s)", job.id, nxt.label())
            else:
                values = {"error": e.user_key}
        except GatewayError as e:
            values = {"error": e.user_key}
            detail = f"{type(e).__name__}: {e}"
            log.warning("job %s failed: %s", job.id, type(e).__name__)
        except Exception as e:
            values = {"error": "errors.ai_failed"}
            detail = f"{type(e).__name__}: {e}"
            log.exception("job %s crashed", job.id)
        finally:
            current_job.reset(token)
            self.job_ids.discard(job.id)
        if status == "failed":
            self.last_error = {
                "t": _ts(),
                "job_id": str(job.id),
                "kind": job.kind,
                "error": str(values.get("error")),
            }
            if detail:
                await trace.note_job_error(self.sm, job.id, detail)
        err = values.get("error")
        if status == "queued":
            delay = None
            if values.get("not_before"):
                delay = round((values["not_before"] - datetime.now(UTC)).total_seconds(), 1)
            values["events"] = event("deferred" if err else "requeued", reason=err, delay_s=delay)
        else:
            values["events"] = event(
                status,
                error=err if status == "failed" else None,
                quick_mode=bool(values.get("quick_mode")) or None,
            )
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

    async def _lanes(self) -> tuple[str, ...]:
        """The admin switch `pause_background_lane` (core/flags.py, read every ~3 s, no restart):
        background jobs stay queued; jobs already running finish."""
        paused = (await flags.load(self.sm)).pause_background_lane
        return ("interactive",) if paused else ("interactive", "background")

    async def tick(self) -> int:
        """Claim as many jobs as lane limits allow; returns how many were started."""
        await self.maintain()
        await economy_live.refresh(self.sm)  # admin overrides of economy.py, every ~3 s
        started = 0
        for lane in await self._lanes():
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
        sleep = getattr(self, "_sleep", asyncio.sleep)
        clock = getattr(self, "_clock", time.monotonic)
        booted = False
        down_since: float | None = None
        retries = 0
        while True:
            try:
                if not booted:
                    swept = await self.sweep()
                    if swept:
                        log.info("failed and refunded %d jobs left by a dead worker", swept)
                    self._swept_at = asyncio.get_running_loop().time()
                    booted = True
                started = await self.tick()
            except DB_ERRORS as e:
                now = clock()
                down_since = now if down_since is None else down_since
                if now - down_since >= DB_OUTAGE_LIMIT_S:
                    log.error(
                        "database unreachable for %.0fs; exiting to be restarted", now - down_since
                    )
                    raise
                wait = DB_RETRY_S[min(retries, len(DB_RETRY_S) - 1)]
                retries += 1
                log.warning("database unavailable (%s); retrying in %ss", type(e).__name__, wait)
                await sleep(wait)
                continue
            if down_since is not None:
                log.info("database back after %.0fs", clock() - down_since)
                down_since, retries = None, 0
            if not started:
                await sleep(self.poll_s)

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
                        Job.lane.in_(await self._lanes()),
                        or_(Job.not_before.is_(None), and_(Job.not_before <= now)),
                    )
                    .limit(1)
                )
            if ready is None:
                return
        raise TimeoutError("worker did not drain")
