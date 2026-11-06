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
