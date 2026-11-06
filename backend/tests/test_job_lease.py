"""F-RES-1 (audit 2026-11-02): a job running when the worker died stayed `running` forever, kept the
student's coins, and every classmate opening that chapter's Study pack was attached to the dead job
(recovery ran only at boot, and only for jobs older than 10 minutes).

Jobs now carry a lease (`lease_until`, `worker_id`) that the worker renews while it runs them; a
sweep (at boot and every SWEEP_S while running) fails jobs whose lease expired and refunds them
exactly once. A worker that finishes a job after it was swept changes nothing."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.features.studio import pack
from app.features.wallet import service as wallet
from app.jobs import demo
from app.jobs import worker as worker_module
from app.jobs.registry import job
from app.jobs.service import create_job
from app.jobs.worker import INTERRUPTED, Worker
from app.models import CoinLedger, Document, Job, User
from tests.test_rag_indexing import gw, rag_env, upload, world_with_courses  # noqa: F401

SLOW = "TEST_SLOW_JOB"


@job(SLOW, stages=("thinking",))
async def _slow(ctx):
    await asyncio.sleep(ctx.payload.get("sleep", 2))
    return {"ok": True}


async def student(sm, nick="LeaseStudent"):
    async with sm() as s:
        u = User(nickname=nick, password_hash="-", ui_language="en")
        s.add(u)
        await s.commit()
        return u


async def coins_of(sm, user_id):
    async with sm() as s:
        return (await wallet.balances(s, user_id)).coins


async def expire(sm, job_id):
    async with sm() as s:
        await s.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()


async def test_a_dead_workers_job_fails_and_is_refunded_exactly_once(sm):
    u = await student(sm)
    async with sm() as s:
        j = await create_job(s, kind=demo.KIND, lane="interactive", user_id=u.id, cost=8)
    assert await coins_of(sm, u.id) == 12
    dead = Worker(sm)
    claimed = await dead.claim(
        "interactive"
    )  # started seconds ago: the old 10-minute rule skips it
    assert claimed.id == j.id
    await expire(sm, j.id)  # the dead worker stops renewing

    other = Worker(sm)
    assert await other.sweep() == 1
    assert await other.sweep() == 0  # idempotent
    async with sm() as s:
        fresh = await s.get(Job, j.id)
        refunds = await s.scalar(
            select(func.count()).where(CoinLedger.ref == str(j.id), CoinLedger.kind == "refund")
        )
    assert fresh.status == "failed" and fresh.error == INTERRUPTED and fresh.finished_at
    assert refunds >= 1 and await coins_of(sm, u.id) == 20


async def test_a_live_job_keeps_its_lease_and_is_never_swept(sm, monkeypatch):
    monkeypatch.setattr(worker_module, "LEASE_S", 1.0)
    monkeypatch.setattr(worker_module, "RENEW_S", 0.2)
    async with sm() as s:
        j = await create_job(s, kind=SLOW, lane="interactive", payload={"sleep": 3})
    alive, sweeper = Worker(sm), Worker(sm)
    run = asyncio.create_task(alive.drain(timeout_s=20))
    for _ in range(12):  # keep sweeping while the 3 s job runs on a 1 s lease
        await asyncio.sleep(0.25)
        await sweeper.sweep()
    await run
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "done", fresh.error


async def test_classmates_are_not_attached_to_a_dead_study_pack(sm):
    payload = {"chapter_id": "11111111-1111-1111-1111-111111111111", "level": "advanced"}
    payload["language"] = "en"
    async with sm() as s:
        j = await create_job(s, kind=pack.KIND, lane="interactive", payload=payload)
    w = Worker(sm)
    await w.claim("interactive")
    async with sm() as s:  # while it runs, classmates share it (that part is by design)
        assert await pack.pending_generation(s, payload["chapter_id"], "advanced", "en") == j.id
    await expire(sm, j.id)
    await Worker(sm).sweep()
    async with sm() as s:  # once dead, nobody is attached to it any more
        assert await pack.pending_generation(s, payload["chapter_id"], "advanced", "en") is None


async def test_a_late_finish_after_the_sweep_changes_nothing(sm):
    u = await student(sm, "LateFinisher")
    async with sm() as s:
        j = await create_job(s, kind=demo.KIND, lane="interactive", user_id=u.id, cost=8)
    slow = Worker(sm)
    claimed = await slow.claim("interactive")
    await expire(sm, j.id)
    await Worker(sm).sweep()  # failed and refunded
    slow.execute = Worker.execute.__get__(slow)  # the slow worker now finishes the job
    await slow.execute(claimed)
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "failed" and fresh.error == INTERRUPTED
    assert await coins_of(sm, u.id) == 20  # not charged after the refund


async def test_an_interrupted_indexing_job_fails_its_document(sm, gw, tmp_path):  # noqa: F811
    user, _, chapters = await world_with_courses(sm)
    f = tmp_path / "notes.txt"
    f.write_text("Limits: factor and cancel first. " * 40)
    doc, job_id, _ = await upload(sm, user, chapters["Calculus I"], f)
    await Worker(sm).claim("background")
    async with sm() as s:
        d = await s.get(Document, doc.id)
        d.status = "parsing"
        await s.commit()
    await expire(sm, job_id)
    await Worker(sm).sweep()
    async with sm() as s:
        d = await s.get(Document, doc.id)
    assert d.status == "failed" and d.error == "errors.indexing_failed"


async def test_running_jobs_without_a_lease_expire_too(sm):
    """Rows started by older code have no lease: they count as expired LEASE_S after starting."""
    async with sm() as s:
        j = await create_job(s, kind=demo.KIND, lane="background")
        await s.execute(
            update(Job)
            .where(Job.id == j.id)
            .values(status="running", started_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await s.commit()
    assert await Worker(sm).sweep() == 1
