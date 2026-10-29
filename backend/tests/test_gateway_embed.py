"""gateway.embed: the error contract applied to the (separately metered) embeddings endpoint."""

import pytest

from app.gateway import Defer, KeyBlocked
from app.gateway.service import EMBED_BATCH
from tests.conftest import FAST_MOCK, MockConfig, create_mock_app
from tests.test_gateway_contract import AUTO, log_rows, make_gateway, make_settings


def set_cfg(app, **cfg) -> None:
    app.state.cfg = app.state.cfg.model_copy(update=cfg)


def texts(n: int) -> list[str]:
    return [f"chunk {i} about limits and derivatives" for i in range(n)]


async def test_batches_keep_order_and_log_each_call(monkeypatch, sm, mock_llm):
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    res = await gw.embed(texts(EMBED_BATCH * 2 + 6), "background")
    assert len(res.vectors) == EMBED_BATCH * 2 + 6 and res.calls == 3
    assert res.provider == "mock" and res.model == "mock-embed"
    one = await gw.embed(["chunk 33 about limits and derivatives"], "background")
    assert res.vectors[33] == one.vectors[0]  # order preserved across batches
    rows = await log_rows(sm)
    assert [(r.task_kind, r.model_tier, r.status_code) for r in rows] == [
        ("EMBED", "embed", 200)
    ] * 4
    assert all(r.tokens_in > 0 and r.pattern == "batch" for r in rows)


async def test_ceiling_shrinks_the_batch_once_and_remembers(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, embedding_max_inputs=10)
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    res = await gw.embed(texts(25), "background")
    assert len(res.vectors) == 25
    rows = await log_rows(sm)
    assert [r.status_code for r in rows] == [400, 200, 200, 200]  # 32 → 10, 10, 5
    assert rows[0].refusal_reason == "ceiling"
    res = await gw.embed(texts(12), "background")  # learned: no second 400
    assert res.calls == 2
    assert [r.status_code for r in await log_rows(sm)][4:] == [200, 200]


async def test_quota_defers_with_the_stated_delay(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, embedding_rpm=0.001, burst=0)
    mock_llm.state.embed_bucket.tokens = 0
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(Defer) as e:
        await gw.embed(texts(3), "background")
    assert e.value.reason == "quota" and e.value.delay_s > 0
    assert (await log_rows(sm))[0].refusal_reason == "quota"


async def test_503_interactive_retries_once_then_defers(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    gw, sleeps = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(Defer) as e:
        await gw.embed(["limit 0/0"], "interactive")
    assert e.value.reason == "saturated" and len(sleeps) == 1
    assert len(await log_rows(sm)) == 2


async def test_503_background_defers_at_once(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, p_503_embed=1.0)
    gw, sleeps = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(Defer):
        await gw.embed(texts(2), "background")
    assert sleeps == [] and len(await log_rows(sm)) == 1


async def test_query_embedding_is_cached(monkeypatch, sm, mock_llm):
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    first = await gw.embed(["limit 0/0"], "interactive", cache_query=True)
    again = await gw.embed(["limit 0/0"], "interactive", cache_query=True)
    assert again.cached and again.vectors == first.vectors and again.calls == 0
    rows = await log_rows(sm)
    assert [r.cache_hit for r in rows] == [False, True]


async def test_auto_blocked_restarts_every_batch_on_local(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, blocked=True)
    local = create_mock_app(MockConfig(**FAST_MOCK))
    env = AUTO | {"CLOUD_EMBEDDING_MODEL": "mock-embed", "LOCAL_EMBEDDING_MODEL": "mock-embed"}
    gw, _ = make_gateway(make_settings(monkeypatch, **env), sm, {"cloud": mock_llm, "local": local})
    res = await gw.embed(texts(40), "background")
    assert res.provider == "local" and len(res.vectors) == 40  # never a cloud/local mix
    providers = [(r.provider, r.status_code) for r in await log_rows(sm)]
    assert providers == [("cloud", 401), ("local", 200), ("local", 200)]


async def test_dev_blocked_without_auto_raises(monkeypatch, sm, mock_llm):
    set_cfg(mock_llm, blocked=True)
    gw, _ = make_gateway(make_settings(monkeypatch), sm, {"mock": mock_llm})
    with pytest.raises(KeyBlocked):
        await gw.embed(texts(1), "background")
