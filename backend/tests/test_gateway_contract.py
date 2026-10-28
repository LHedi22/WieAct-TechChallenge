"""One test per row of the platform's error contract (docs/PLATFORM.md), plus the edge cases.
These run the real gateway against the in-process mock platform and the Postgres test database —
they are the resilience evidence for the report."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.slot import TZ
from app.gateway import Defer, KeyBlocked, OfflineMode, RequestRejected, Task, TaskKind
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.providers import resolve
from app.gateway.service import Gateway
from app.models import AICallLog
from tests.conftest import FAST_MOCK, MockConfig, create_mock_app, mock_transport

MESSAGES = [
    {"role": "system", "content": "Summarise the chapter for a first-year student."},
    {"role": "user", "content": "Limits and the 0/0 indeterminate form"},
]


def make_settings(monkeypatch, **env) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def make_gateway(settings: Settings, sm, apps: dict, *, on_sleep=None, now=None):
    """apps: host → mock app (profiles' base URLs are http://<host>/v1)."""
    sleeps: list[float] = []

    def factory(profile):
        host = httpx.URL(profile.base_url).host
        return LLMClient(
            profile,
            timeout_s=5,
            disable_thinking=settings.LLM_DISABLE_THINKING,
            json_mode=settings.LLM_JSON_MODE,
            http_client=mock_transport(apps[host]),
        )

    async def sleep(s: float) -> None:
        sleeps.append(s)
        if on_sleep:
            on_sleep()

    gw = Gateway(
        settings,
        sm,
        client_factory=factory,
        sleep=sleep,
        now=now,
        limiter=Limiter(6000, 2, burst=50),
    )
    return gw, sleeps


def task(lane="interactive", **kw) -> Task:
    return Task(kind=TaskKind.DEMO_SUMMARY, lane=lane, messages=MESSAGES, **kw)


async def log_rows(sm) -> list[AICallLog]:
    async with sm() as s:
        return list((await s.scalars(select(AICallLog).order_by(AICallLog.id))).all())


# --- Normal: 200 + quota headers --------------------------------------------------------------


async def test_normal_call_parses_json_reads_quota_headers_and_logs(monkeypatch, sm, mock_llm):
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    result = await gw.run(task())
    assert result.model_tier == "mid" and result.model == "mock-mid" and not result.cached
    assert "0/0" in result.content["summary"] and len(result.content["key_points"]) == 3
    assert gw.quota.get("mock").remaining is not None
    [row] = await log_rows(sm)
    assert (row.status_code, row.provider, row.model, row.lane) == (
        200,
        "mock",
        "mock-mid",
        "interactive",
    )
    assert row.tokens_out > 0 and row.request_hash and not row.cache_hit


# --- Identical request: must not regenerate ---------------------------------------------------


async def test_identical_request_is_a_cache_hit_without_a_call(monkeypatch, sm, mock_llm):
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    first = await gw.run(task(cache_key="world1:ch1:intermediate:en"))
    second = await gw.run(task(cache_key="world1:ch1:intermediate:en"))
    assert not first.cached and second.cached and second.content == first.content
    assert mock_llm.state.stats.calls == 1
    rows = await log_rows(sm)
    assert [r.cache_hit for r in rows] == [False, True]


async def test_cache_is_kept_apart_per_provider(monkeypatch, sm, mock_llm):
    other = create_mock_app(MockConfig(**FAST_MOCK))
    s = make_settings(monkeypatch)
    gw, _ = make_gateway(s, sm, {"mock": mock_llm})
    await gw.run(task(cache_key="k"))
    s2 = make_settings(
        monkeypatch,
        LLM_PROVIDER="local",
        LOCAL_BASE_URL="http://local/v1",
        LOCAL_MODEL_MID="mock-mid",
        LOCAL_MODEL_COMPACT="mock-compact",
    )
    gw2, _ = make_gateway(s2, sm, {"local": other})
    assert not (await gw2.run(task(cache_key="k"))).cached  # a mock result never stands in


# --- Team quota exhausted: wait the stated delay, retry (requeue) ------------------------------


async def test_quota_exhausted_defers_with_the_stated_delay(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_quota": 1.0, "quota_delay_s": 7})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(Defer) as e:
        await gw.run(task())
    assert e.value.reason == "quota" and e.value.delay_s == 7
    [row] = await log_rows(sm)
    assert row.refusal_reason == "quota" and row.status_code == 429


# --- Model class saturated: 503 + Retry-After ---------------------------------------------------


async def test_503_interactive_retries_once_then_falls_back_to_compact(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    gw, sleeps = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    result = await gw.run(task())
    assert result.quick_mode and result.model_tier == "compact" and result.pattern == "fallback"
    assert sleeps == [3.0]  # one Retry-After wait (capped at 5 s for a waiting student)
    rows = await log_rows(sm)
    assert [(r.model, r.status_code) for r in rows] == [
        ("mock-mid", 503),
        ("mock-mid", 503),
        ("mock-compact", 200),
    ]
    assert rows[-1].fallback


async def test_503_retry_succeeds_on_mid_without_quick_mode(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})

    def recover():
        mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 0.0})

    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm}, on_sleep=recover)
    result = await gw.run(task())
    assert not result.quick_mode and result.model_tier == "mid"


async def test_503_background_defers_instead_of_falling_back(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(Defer) as e:
        await gw.run(task(lane="background"))
    assert e.value.reason == "saturated" and e.value.delay_s == 3
    assert mock_llm.state.stats.by_tier == {"mid": 1}


async def test_quick_mode_result_is_not_cached(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    assert (await gw.run(task(cache_key="notes"))).quick_mode
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 0.0})
    again = await gw.run(task(cache_key="notes"))
    assert not again.cached and not again.quick_mode  # the class gets the mid-size version


# --- Request beyond a ceiling: 400 naming it → fix and resend once ----------------------------


async def test_400_ceiling_shrinks_once_and_remembers(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"max_tokens_ceiling": 200})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    result = await gw.run(task(max_tokens=900))
    assert "shrunk max_tokens to 200" in result.notes
    calls = mock_llm.state.stats.calls
    await gw.run(task(max_tokens=900))  # learned ceiling: no second 400
    assert mock_llm.state.stats.calls == calls + 1


async def test_400_that_shrinking_cannot_fix_is_rejected(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"max_tokens_ceiling": 8})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(RequestRejected):
        await gw.run(task(max_tokens=900))
    assert mock_llm.state.stats.calls == 2  # original + exactly one resend


# --- Malformed JSON -----------------------------------------------------------------------------


async def test_almost_json_is_recovered_without_a_repair_call(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_bad_json": 1.0})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    result = await gw.run(task())
    assert result.content["key_points"] and mock_llm.state.stats.calls == 1


async def test_broken_json_gets_one_compact_repair_call(monkeypatch, sm):
    replies = iter(["The summary is: limits are fun", '{"summary": "fixed", "key_points": []}'])
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_models.append(__import__("json").loads(request.content)["model"])
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": next(replies)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    s = make_settings(monkeypatch)
    gw = Gateway(
        s,
        sm,
        limiter=Limiter(6000, 2, burst=50),
        client_factory=lambda p: LLMClient(
            p,
            timeout_s=5,
            disable_thinking=True,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )
    result = await gw.run(task())
    assert result.content == {"summary": "fixed", "key_points": []}
    assert seen_models == ["mock-mid", "mock-compact"]  # the repair runs on compact
    rows = await log_rows(sm)
    assert [r.task_kind for r in rows] == ["DEMO_SUMMARY", "JSON_REPAIR"]


# --- Network errors -----------------------------------------------------------------------------


async def test_network_error_retries_once_then_defers(monkeypatch, sm):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    s = make_settings(monkeypatch)
    gw = Gateway(
        s,
        sm,
        limiter=Limiter(6000, 2, burst=50),
        sleep=lambda _: asyncio.sleep(0),
        client_factory=lambda p: LLMClient(
            p,
            timeout_s=5,
            disable_thinking=True,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )
    with pytest.raises(Defer) as e:
        await gw.run(task())
    assert e.value.reason == "transient" and len(await log_rows(sm)) == 2


# --- Concurrency: never more than 2 in flight ----------------------------------------------------


async def test_burst_of_jobs_never_exceeds_two_concurrent(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"latency_mid_ms": (30, 30)})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    results = await asyncio.gather(*[gw.run(task()) for _ in range(8)])
    assert all(not r.quick_mode for r in results)
    assert mock_llm.state.stats.max_active <= 2 and mock_llm.state.stats.by_status == {"200": 8}


# --- Providers: auto switching and offline demo mode -------------------------------------------

AUTO = dict(
    LLM_PROVIDER="auto",
    LLM_SLOT_FORCE="live",
    CLOUD_BASE_URL="http://cloud/v1",
    CLOUD_API_KEY="test-key",
    CLOUD_MODEL_COMPACT="mock-compact",
    CLOUD_MODEL_MID="mock-mid",
    LOCAL_BASE_URL="http://local/v1",
    LOCAL_MODEL_COMPACT="mock-compact",
    LOCAL_MODEL_MID="mock-mid",
)


async def test_auto_uses_cloud_in_slot(monkeypatch, sm, mock_llm):
    local = create_mock_app(MockConfig(**FAST_MOCK))
    gw, _ = make_gateway(
        make_settings(monkeypatch, **AUTO), sm, {"cloud": mock_llm, "local": local}
    )
    assert (await gw.run(task())).provider == "cloud"


async def test_auto_switches_to_local_on_401_without_restart(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"blocked": True})  # MOCK_BLOCKED
    local = create_mock_app(MockConfig(**FAST_MOCK))
    gw, _ = make_gateway(
        make_settings(monkeypatch, **AUTO), sm, {"cloud": mock_llm, "local": local}
    )
    first = await gw.run(task())
    assert first.provider == "local" and "key blocked: switched to local" in first.notes
    cloud_calls = mock_llm.state.stats.calls
    second = await gw.run(task())  # same process, next job: resolved to local up front
    assert second.provider == "local" and mock_llm.state.stats.calls == cloud_calls


async def test_auto_uses_local_outside_slot(monkeypatch, sm, mock_llm):
    env = AUTO | {"LLM_SLOT_FORCE": "off"}
    local = create_mock_app(MockConfig(**FAST_MOCK))
    gw, _ = make_gateway(make_settings(monkeypatch, **env), sm, {"cloud": mock_llm, "local": local})
    assert (await gw.run(task())).provider == "local" and mock_llm.state.stats.calls == 0


async def test_auto_returns_to_cloud_when_the_next_slot_starts(monkeypatch, sm):
    s = make_settings(monkeypatch, **(AUTO | {"LLM_SLOT_FORCE": ""}))
    in_slot = datetime(2026, 10, 28, 15, 0, tzinfo=TZ)  # group A: Wed 12:00-24:00
    async with sm() as session:
        session.add(
            AICallLog(
                ts=in_slot,
                task_kind="X",
                model_tier="mid",
                provider="cloud",
                model="m",
                pattern="p",
                status_code=401,
            )
        )
        await session.commit()
    assert (await resolve(s, sm, in_slot + timedelta(hours=1))).profile.provider == "local"
    next_slot = datetime(2026, 10, 29, 1, 0, tzinfo=TZ)  # Thu 00:00-12:00
    assert (await resolve(s, sm, next_slot)).profile.provider == "cloud"


async def test_dev_cloud_blocked_raises(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"blocked": True})
    env = {k: v for k, v in AUTO.items() if k.startswith("CLOUD_")} | {"LLM_PROVIDER": "cloud"}
    gw, _ = make_gateway(make_settings(monkeypatch, **env), sm, {"cloud": mock_llm})
    with pytest.raises(KeyBlocked):
        await gw.run(task())


async def test_production_outside_slot_serves_cache_only(monkeypatch, sm, mock_llm):
    env = {k: v for k, v in AUTO.items() if k.startswith("CLOUD_")} | {
        "LLM_PROVIDER": "cloud",
        "APP_ENV": "production",
        "SECRET_KEY": "prod-secret",
    }
    s = make_settings(monkeypatch, **env)
    in_slot = lambda: datetime(2026, 10, 28, 15, 0, tzinfo=TZ).astimezone(UTC)  # noqa: E731
    outside = lambda: datetime(2026, 10, 28, 9, 0, tzinfo=TZ).astimezone(UTC)  # noqa: E731
    live_gw, _ = make_gateway(s, sm, {"cloud": mock_llm}, now=in_slot)
    await live_gw.run(task(cache_key="shared-notes"))  # generated in-slot on the platform
    calls = mock_llm.state.stats.calls
    offline_gw, _ = make_gateway(s, sm, {"cloud": mock_llm}, now=outside)
    assert (await offline_gw.run(task(cache_key="shared-notes"))).cached
    with pytest.raises(OfflineMode):
        await offline_gw.run(task(cache_key="something-new"))
    assert mock_llm.state.stats.calls == calls  # never fakes AI output, never calls out of slot


async def test_call_log_counts_compact_mid_split(monkeypatch, sm, mock_llm):
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    await gw.run(task())
    await gw.run(task(tier="compact"))
    async with sm() as s:
        rows = (
            await s.execute(
                select(AICallLog.model_tier, func.count()).group_by(AICallLog.model_tier)
            )
        ).all()
    assert dict(rows) == {"mid": 1, "compact": 1}


async def test_concurrent_identical_requests_make_one_call(monkeypatch, sm, mock_llm):
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"latency_mid_ms": (50, 50)})
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    results = await asyncio.gather(*[gw.run(task(cache_key="ch1:notes:en")) for _ in range(5)])
    assert mock_llm.state.stats.calls == 1
    assert sum(r.cached for r in results) == 4
    assert len({str(r.content) for r in results}) == 1
