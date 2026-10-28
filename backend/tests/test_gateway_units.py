"""Pure gateway pieces: error classification, quota headers, limiter, JSON repair, routing."""

import asyncio
import time

import pytest

from app.gateway.errors import classify, retry_after
from app.gateway.jsonfix import extract_json, strip_think
from app.gateway.limiter import Limiter
from app.gateway.quota import QuotaState, parse
from app.gateway.router import ROUTES
from app.gateway.types import TaskKind

# --- error contract classification ---------------------------------------------------------------


def test_quota_by_status_with_retry_after():
    e = classify(429, {"Retry-After": "7"}, "team quota exhausted")
    assert (e.kind, e.retry_after_s) == ("quota", 7.0)


def test_quota_recognised_by_message_with_unknown_status():
    e = classify(403, {}, "Team quota exhausted, retry in 12 s")
    assert (e.kind, e.retry_after_s) == ("quota", 12.0)


def test_quota_delay_from_reset_header_ms():
    assert retry_after({"x-ratelimit-reset-ms": "2500"}) == 2.5


def test_quota_default_delay_when_nothing_stated():
    assert classify(429, {}, "slow down").retry_after_s == 30.0


def test_503_saturated_with_retry_after():
    e = classify(503, {"retry-after": "3"}, "model class mid saturated")
    assert (e.kind, e.retry_after_s) == ("saturated", 3.0)


def test_400_ceiling_names_the_limit_not_the_request():
    msg = "max_tokens 2000 exceeds the maximum response length of 1024 tokens"
    e = classify(400, {}, msg)
    assert (e.kind, e.ceiling, e.ceiling_on_input) == ("ceiling", 1024, False)


def test_400_input_ceiling():
    e = classify(400, {}, "prompt is too long: context limit 4096 tokens")
    assert e.kind == "ceiling" and e.ceiling_on_input and e.ceiling == 4096


def test_401_blocked_and_network_transient():
    assert classify(401, {}, "Key is blocked").kind == "blocked"
    assert classify(None, {}, "ConnectError").kind == "transient"
    assert classify(502, {}, "bad gateway").kind == "transient"


def test_plain_400_is_bad_request():
    assert classify(400, {}, "messages must be a list").kind == "bad_request"


# --- quota headers --------------------------------------------------------------------------------


def test_quota_headers_parsed_tolerantly():
    s = parse({"x-ratelimit-remaining": "2", "x-ratelimit-reset-ms": "4000", "Server": "x"})
    assert s.remaining == 2 and s.reset_s == 4.0 and s.low


def test_quota_headers_other_names():
    s = parse({"RateLimit-Remaining-Requests": "15", "RateLimit-Reset": "20"})
    assert s.remaining == 15 and s.reset_s == 20 and not s.low


def test_no_quota_headers():
    assert parse({"content-type": "application/json"}) is None


def test_low_quota_stops_pausing_after_reset():
    s = QuotaState(remaining=1, reset_s=0.0, observed_at=time.monotonic() - 1)
    assert not s.low


# --- limiter --------------------------------------------------------------------------------------


async def test_limiter_never_exceeds_concurrency():
    lim = Limiter(rpm=6000, concurrency=2, burst=50)
    active = peak = 0

    async def call():
        nonlocal active, peak
        async with lim.slot("background"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*[call() for _ in range(12)])
    assert peak == 2 and lim.max_active == 2


async def test_limiter_paces_requests_per_minute():
    lim = Limiter(rpm=120, concurrency=2, burst=1)  # 2 per second after the first
    t0 = time.monotonic()
    for _ in range(3):
        async with lim.slot("interactive"):
            pass
    assert time.monotonic() - t0 >= 0.9


async def test_interactive_served_before_waiting_background():
    lim = Limiter(rpm=6000, concurrency=1, burst=50)
    order: list[str] = []

    async def call(lane, name):
        async with lim.slot(lane):
            order.append(name)
            await asyncio.sleep(0.02)

    first = asyncio.create_task(call("background", "bg0"))
    await asyncio.sleep(0.005)
    rest = [asyncio.create_task(call("background", f"bg{i}")) for i in (1, 2)]
    await asyncio.sleep(0.005)
    rest.append(asyncio.create_task(call("interactive", "student")))
    await asyncio.gather(first, *rest)
    assert order[0] == "bg0" and order[1] == "student"


async def test_background_pauses_while_quota_low():
    pause = {"s": 0.2}
    lim = Limiter(rpm=6000, concurrency=2, burst=50, background_pause=lambda: pause["s"])
    task = asyncio.create_task(lim.acquire("background"))
    await asyncio.sleep(0.05)
    async with lim.slot("interactive"):  # interactive is never paused
        pass
    await asyncio.sleep(0.05)
    assert not task.done()  # still held while the platform reports low quota
    pause["s"] = 0
    await asyncio.wait_for(task, timeout=1)


# --- JSON repair ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure! Here it is: {"a": 1} hope that helps',
        '```json\n{"a": 1,\n```',  # mock's broken JSON: trailing comma, no closing brace
        '<think>hmm</think>{"a": 1}',
    ],
)
def test_extract_json_tolerant(text):
    assert extract_json(text) == {"a": 1}


def test_extract_json_nested_and_unrecoverable():
    assert extract_json('{"q": [{"x": "}"}], "n": 2') == {"q": [{"x": "}"}], "n": 2}
    assert extract_json("no json here") is None


def test_strip_think():
    assert strip_think("<think>\nlong\n</think>\nAnswer") == "Answer"


# --- routing table --------------------------------------------------------------------------------


def test_every_task_kind_is_routed_and_mid_is_rare():
    assert set(ROUTES) == set(TaskKind)
    mid = [k for k, r in ROUTES.items() if r.tier == "mid"]
    assert len(mid) < len(ROUTES) / 2  # compact handles most traffic (PLATFORM.md)
    assert ROUTES[TaskKind.TUTOR_TURN].pattern == "escalation"
