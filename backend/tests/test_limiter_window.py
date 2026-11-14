"""Audit OPT-04: the token bucket (capacity 3, 18/min refill) let one 60 s window carry 3 + 18 = 21
chat calls, over the platform's 20 per minute (both mock load runs, independent logger). A hard
sliding-window cap now holds whatever LLM_MAX_RPM or the burst is set to."""

import asyncio
import time

import pytest

from app.gateway import limiter as limiter_module
from app.gateway.limiter import Limiter


async def test_no_60s_window_carries_more_than_20_calls_whatever_the_rpm():
    lim = Limiter(6000, 2, burst=100)  # a mis-set LLM_MAX_RPM and burst
    for _ in range(20):
        async with lim.slot("interactive"):
            pass
    with pytest.raises(TimeoutError):  # the 21st waits for the oldest call to leave the window
        await asyncio.wait_for(lim.acquire("interactive"), timeout=0.5)
    assert lim.calls_last_60s() == 20


async def test_the_window_frees_a_slot_once_the_oldest_call_is_60s_old():
    lim = Limiter(6000, 2, burst=100)
    now = time.monotonic()
    lim._recent["chat"].extend([now - 59.8] + [now - 1] * 19)
    started = time.monotonic()
    async with lim.slot("interactive"):
        pass
    assert 0.1 <= time.monotonic() - started < 2.5
    assert limiter_module.PLATFORM_CALLS_PER_MIN == 20


async def test_the_window_keeps_a_margin_for_arrival_skew():
    """Found re-running the load test: the limiter counts at acquire, the platform at arrival.
    The first call of a run also sets up the client and connection after acquire, so at the
    server call 1 and call 21 were 59.98 s apart (logger). The 21st now waits for the oldest call
    to be 60 s + WINDOW_MARGIN_S old."""
    lim = Limiter(6000, 2, burst=100)
    now = time.monotonic()
    lim._recent["chat"].extend([now - 60.3] + [now - 1] * 19)
    started = time.monotonic()
    async with lim.slot("interactive"):
        pass
    assert time.monotonic() - started >= 0.4
    assert limiter_module.WINDOW_MARGIN_S >= 0.7
