"""Audit N-7 (5 Nov, dependency-outage test): a Postgres restart killed the worker process. A DNS
error in claim() escaped run_forever; in docker-compose the worker had no restart policy and
stayed down (production self-healed only through a full container restart).

Now the loop survives database errors with bounded reconnects (backoff 1 → 30 s); if the
database is still unreachable after DB_OUTAGE_LIMIT_S it exits so the supervisor restarts it, and
docker-compose restarts the worker and the API."""

import socket
from pathlib import Path

import pytest
import yaml
from sqlalchemy.exc import OperationalError

from app.jobs import worker as worker_module
from app.jobs.worker import Worker


class Stop(Exception):
    pass


class FakeWorker(Worker):
    """tick() follows a script: an exception to raise, or a number of jobs started."""

    def __init__(self, script, clock):
        self.script = list(script)
        self.ticks = 0
        self.slept: list[float] = []
        self._now = clock
        self.poll_s = 0.5

    async def sweep(self):
        return 0

    async def tick(self):
        self.ticks += 1
        if not self.script:
            raise Stop
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def harness(script, step=1.0):
    t = {"now": 0.0}
    w = FakeWorker(script, clock=lambda: t["now"])

    async def sleep(s):
        w.slept.append(s)
        t["now"] += s

    w._sleep = sleep
    w._clock = lambda: t["now"]
    return w


DNS = socket.gaierror(-5, "No address associated with hostname")  # what the audit saw
DROPPED = OperationalError("SELECT 1", {}, ConnectionError("connection was closed"))


async def test_the_loop_survives_a_postgres_restart():
    w = harness([0, DNS, DROPPED, DNS, 1, 0])
    with pytest.raises(Stop):  # only the test's own end of script stops it
        await w.run_forever()
    assert w.ticks == 7
    backoff = [s for s in w.slept if s != w.poll_s]  # not the idle polls
    assert backoff == [1, 2, 4]  # while the database is away


async def test_backoff_is_capped_and_resets_once_the_database_is_back():
    w = harness([DNS] * 8 + [0, DNS])
    with pytest.raises(Stop):
        await w.run_forever()
    assert max(w.slept) == worker_module.DB_RETRY_S[-1]
    assert w.slept[-1] == 1  # the error after recovery starts the backoff again


async def test_a_long_outage_exits_so_the_supervisor_restarts_it(monkeypatch):
    monkeypatch.setattr(worker_module, "DB_OUTAGE_LIMIT_S", 60)
    w = harness([DNS] * 50)
    with pytest.raises(socket.gaierror):
        await w.run_forever()
    assert sum(w.slept) <= 60 + worker_module.DB_RETRY_S[-1]  # bounded


async def test_other_errors_are_not_swallowed():
    w = harness([ValueError("a bug")])
    with pytest.raises(ValueError):
        await w.run_forever()


def test_compose_restarts_the_worker_and_the_api():
    path = next(
        p for p in (Path("/docker-compose.yml"), Path(__file__).parents[2] / "docker-compose.yml")
        if p.exists()
    )  # fmt: skip
    services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    for name in ("worker", "backend"):
        assert services[name].get("restart") in ("unless-stopped", "always", "on-failure")


# --- audit OPT-12 (13 Nov, logs/61-chaos-db-restart.log) ---------------------------------------
# During a Postgres restart the loop survived, but Worker.execute() raised DBAPIError on its final
# write ("the database system is starting up"): the job stayed `running`, its lease expired and the
# sweep failed it with errors.job_interrupted after 83 s; a poll got a 500. Now a job rides out a
# short outage: its DB writes retry with the loop's backoff, a DB error inside the handler requeues
# it (the cache keeps what it already made), the sweep never fails a job this worker still runs,
# and the API answers 503 + Retry-After instead of 500.
from contextlib import asynccontextmanager  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

from sqlalchemy import update  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from app.jobs.registry import job  # noqa: E402
from app.jobs.service import create_job  # noqa: E402
from app.models import Job  # noqa: E402
from tests.test_job_lease import coins_of, student  # noqa: E402

STARTING_UP = DBAPIError("SELECT 1", {}, ConnectionError("the database system is starting up"))
FLAKY_KIND, DB_DOWN_KIND = "TEST_DB_FLAKY_END", "TEST_DB_DOWN_MID_JOB"


class FlakySM:
    """A sessionmaker whose next `fail` sessions can't connect (Postgres restarting)."""

    def __init__(self, sm):
        self.sm, self.fail = sm, 0

    def __call__(self):
        if self.fail:
            self.fail -= 1
            return _refused()
        return self.sm()


@asynccontextmanager
async def _refused():
    raise ConnectionRefusedError(111, "Connect call failed")
    yield  # pragma: no cover


FLAKY: dict[str, FlakySM] = {}


@job(FLAKY_KIND, stages=("thinking",))
async def _db_goes_away_at_the_end(ctx):
    FLAKY["sm"].fail = 3  # the database restarts just as the answer is ready
    return {"ok": True}


@job(DB_DOWN_KIND, stages=("thinking",))
async def _db_goes_away_mid_job(ctx):
    if ctx.attempts == 1:
        raise STARTING_UP  # e.g. set_stage / a cache read while Postgres restarts
    return {"ok": True, "attempt": ctx.attempts}


@pytest.fixture
def quick_backoff(monkeypatch):
    monkeypatch.setattr(worker_module, "DB_RETRY_S", (0.01, 0.02))


async def test_the_final_write_rides_out_a_short_outage(sm, quick_backoff):
    u = await student(sm, "OutageRider")
    async with sm() as s:
        j = await create_job(s, kind=FLAKY_KIND, lane="interactive", user_id=u.id, cost=8)
    FLAKY["sm"] = flaky = FlakySM(sm)
    w = Worker(flaky)
    claimed = await w.claim("interactive")
    await w.execute(claimed)
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "done", fresh.error
    assert fresh.result == {"ok": True}
    assert await coins_of(sm, u.id) == 12  # charged once, not refunded


async def test_a_db_error_inside_the_handler_requeues_instead_of_failing(sm, quick_backoff):
    u = await student(sm, "MidJobOutage")
    async with sm() as s:
        j = await create_job(s, kind=DB_DOWN_KIND, lane="interactive", user_id=u.id, cost=8)
    w = Worker(sm)
    await w.execute(await w.claim("interactive"))
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "queued" and fresh.error == "deferred:database"
    assert fresh.worker_id is None and fresh.lease_until is None
    assert await coins_of(sm, u.id) == 12  # still reserved, not refunded
    async with sm() as s:  # ready again a moment later
        await s.execute(update(Job).where(Job.id == j.id).values(not_before=None))
        await s.commit()
    await w.drain(timeout_s=10)
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "done" and fresh.result == {"ok": True, "attempt": 2}


async def test_the_sweep_never_fails_a_job_this_worker_still_runs(sm):
    async with sm() as s:
        j = await create_job(s, kind=FLAKY_KIND, lane="interactive")
    w = Worker(sm)
    await w.claim("interactive")
    w.job_ids.add(j.id)  # still executing, but renew() failed while the database was away
    async with sm() as s:
        await s.execute(
            update(Job)
            .where(Job.id == j.id)
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert await w.sweep() == 0  # back from the outage: renew, don't fail our own job
    async with sm() as s:
        fresh = await s.get(Job, j.id)
    assert fresh.status == "running"
    assert await Worker(sm).sweep() == 1  # another worker still reclaims a dead one's job


async def test_the_api_answers_503_with_retry_after_while_the_database_is_down(monkeypatch):
    import httpx  # noqa: PLC0415

    from app.core import economy_live  # noqa: PLC0415
    from app.core.db import get_session  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415

    app = create_app()

    async def down():
        raise ConnectionRefusedError(111, "Connect call failed")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = down
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await api.get("/api/auth/me", headers={"X-Dev-User": "Poller"})
    assert r.status_code == 503, r.text
    assert r.headers["retry-after"] == "5" and r.json() == {"detail": "errors.unavailable"}

    async def refresh_down(_sm):
        raise STARTING_UP

    monkeypatch.setattr(economy_live, "refresh", refresh_down)  # the middleware's own read
    r = await api.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
