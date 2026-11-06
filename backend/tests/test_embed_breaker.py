"""Audit N-9 (5 Nov, dependency-outage test): during an embeddings outage ONE interactive Tutor
start made 16 embedding calls in 46 s (8 job attempts × 1 call + 1 inline retry), and each call
uses a unit of the separately metered embeddings quota.

Now a short circuit breaker per provider guards the endpoint: after BREAKER_FAILS consecutive
failures it opens for BREAKER_OPEN_S (doubling per trip, capped), and no call is made while it is
open: interactive work fails fast (coins refunded), background work waits for the cooldown. After
the cooldown one probe call decides: success closes it, failure reopens it for longer."""

from datetime import UTC, datetime, timedelta

import pytest

from app.gateway import Defer
from app.gateway import breaker as breaker_module
from app.gateway.errors import EmbeddingsDown
from tests.test_gateway_contract import log_rows, make_gateway, make_settings
from tests.test_gateway_embed import set_cfg


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 5, 12, tzinfo=UTC)

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += timedelta(seconds=s)


async def attempts(gw, n, lane="interactive"):
    """n job attempts of an interactive start that needs one query embedding."""
    outcomes = []
    for _ in range(n):
        try:
            await gw.embed(["limit 0/0"], lane)
            outcomes.append("ok")
        except EmbeddingsDown:
            outcomes.append("down")
        except Defer as d:
            outcomes.append(f"defer:{d.reason}")
    return outcomes


async def test_an_outage_costs_a_bounded_number_of_calls(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    clock = Clock()
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm}, now=clock)
    out = await attempts(gw, 8)  # what MAX_ATTEMPTS used to allow
    calls = len(await log_rows(sm))
    assert calls <= breaker_module.BREAKER_FAILS  # before the fix: 16
    assert out[-1] == "down"  # interactive: fail fast (refund), no more calls


async def test_background_waits_out_the_cooldown_without_calling(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    clock = Clock()
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm}, now=clock)
    await attempts(gw, 3, "background")
    before = len(await log_rows(sm))
    with pytest.raises(Defer) as e:
        await gw.embed(["chunk"], "background")
    assert e.value.reason == "embeddings_down" and e.value.delay_s > 1
    assert len(await log_rows(sm)) == before


async def test_one_probe_after_the_cooldown_closes_it(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    clock = Clock()
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm}, now=clock)
    await attempts(gw, 4)
    set_cfg(mock_llm, p_503_embed=0.0)  # the model is back
    assert await attempts(gw, 1) == ["down"]  # still cooling down: no call
    clock.advance(breaker_module.BREAKER_OPEN_S + 1)
    assert await attempts(gw, 2) == ["ok", "ok"]


async def test_a_failed_probe_reopens_for_longer(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    clock = Clock()
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm}, now=clock)
    await attempts(gw, 4)
    clock.advance(breaker_module.BREAKER_OPEN_S + 1)
    before = len(await log_rows(sm))
    await attempts(gw, 3)
    assert len(await log_rows(sm)) == before + 1  # exactly one probe
    clock.advance(breaker_module.BREAKER_OPEN_S + 1)  # the second trip waits twice as long
    assert await attempts(gw, 1) == ["down"]


def test_cooldown_doubles_and_is_capped():
    b = breaker_module.Breaker()
    now = datetime(2026, 11, 5, tzinfo=UTC)
    waits = []
    for _ in range(6):
        for _ in range(breaker_module.BREAKER_FAILS):
            b.failure(now)
        waits.append(b.remaining(now))
        now += timedelta(seconds=b.remaining(now) + 1)
        assert b.remaining(now) == 0  # half-open: one probe allowed
    assert waits[0] == breaker_module.BREAKER_OPEN_S
    assert waits[1] == 2 * breaker_module.BREAKER_OPEN_S
    assert max(waits) == breaker_module.BREAKER_MAX_OPEN_S


@pytest.mark.parametrize("lane", ["interactive", "background"])
async def test_the_worker_fails_interactive_fast_and_requeues_background(sm, monkeypatch, lane):
    """An open breaker never turns into ungrounded output: EmbeddingsDown is a Defer, so features
    re-raise it; the worker fails a student's job at once (refund) or waits out the cooldown."""
    import app.gateway as gateway_module
    from app.jobs import demo
    from app.jobs.service import create_job
    from app.jobs.worker import Worker
    from app.models import Job

    async def down(task):
        raise EmbeddingsDown(120)

    monkeypatch.setattr(gateway_module, "run", down)
    async with sm() as s:
        job = await create_job(s, kind=demo.KIND, lane=lane)
    await Worker(sm).drain(timeout_s=5)
    async with sm() as s:
        row = await s.get(Job, job.id)
    if lane == "interactive":
        assert row.status == "failed" and row.error == "errors.quota_queue" and row.attempts == 1
    else:
        assert row.status == "queued" and row.error == "deferred:embeddings_down"
        assert (row.not_before - datetime.now(UTC)).total_seconds() > 100
