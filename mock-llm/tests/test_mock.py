import asyncio
import json

import httpx
import pytest

from mock_llm.app import create_app
from mock_llm.config import MockConfig

FAST = dict(latency_compact_ms=(0, 0), latency_mid_ms=(0, 0), p_503_mid=0, p_bad_json=0)


def client(**cfg) -> httpx.AsyncClient:
    app = create_app(MockConfig(**(FAST | cfg)), seed=1)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")


def chat_body(model="mock-compact", system="", user="limits 0/0", **extra):
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": user}
    ]
    return {"model": model, "messages": msgs, "max_tokens": 200} | extra


async def test_models_list():
    async with client() as c:
        ids = [m["id"] for m in (await c.get("/v1/models")).json()["data"]]
    assert ids == ["mock-compact", "mock-mid", "mock-embed"]


async def test_chat_returns_whole_response_with_quota_headers():
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"].startswith("Mock reply")
    assert r.json()["usage"]["completion_tokens"] > 0
    assert int(r.headers["x-ratelimit-remaining"]) >= 0
    assert "x-ratelimit-reset-ms" in r.headers


async def test_quota_header_names_are_configurable():
    async with client(header_remaining="x-team-left") as c:
        r = await c.post("/v1/chat/completions", json=chat_body())
    assert "x-team-left" in r.headers


async def test_task_fixture_by_marker_and_language():
    system = "<!-- task: DEMO_SUMMARY --> <!-- lang: fr --> Résume."
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(system=system, user="les limites"))
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    assert "limite" in data["summary"] and "les limites" in data["summary"]
    assert len(data["key_points"]) == 3


async def test_streaming_rejected():
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(stream=True))
    assert r.status_code == 400


async def test_ceiling_400_names_the_limit():
    async with client(max_tokens_ceiling=512) as c:
        r = await c.post("/v1/chat/completions", json=chat_body(max_tokens=2000))
    assert r.status_code == 400
    assert "512" in r.json()["error"]["message"]


@pytest.mark.parametrize("fault,status", [("503", 503), ("quota", 429), ("blocked", 401)])
async def test_fault_header(fault, status):
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(), headers={"X-Mock-Fault": fault})
    assert r.status_code == status
    if fault == "503":
        assert r.headers["Retry-After"] == "3"
    if fault == "quota":
        assert "quota" in r.json()["error"]["message"] and int(r.headers["Retry-After"]) >= 1
    if fault == "blocked":
        assert r.json()["error"]["message"] == "Key is blocked"


async def test_quota_status_configurable():
    async with client(quota_status=403) as c:
        r = await c.post(
            "/v1/chat/completions", json=chat_body(), headers={"X-Mock-Fault": "quota"}
        )
    assert r.status_code == 403


async def test_bad_json_fault():
    system = "<!-- task: DEMO_SUMMARY -->"
    async with client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json=chat_body(system=system),
            headers={"X-Mock-Fault": "badjson"},
        )
    text = r.json()["choices"][0]["message"]["content"]
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


async def test_bucket_empties_then_refuses_with_delay():
    async with client(rpm=6, burst=2) as c:
        codes = [
            (await c.post("/v1/chat/completions", json=chat_body())).status_code for _ in range(3)
        ]
        last = await c.post("/v1/chat/completions", json=chat_body())
    assert codes[:2] == [200, 200] and codes[2] == 429
    assert int(last.headers["Retry-After"]) >= 1


async def test_more_than_two_concurrent_rejected():
    async with client(latency_compact_ms=(200, 200)) as c:
        rs = await asyncio.gather(
            *[c.post("/v1/chat/completions", json=chat_body()) for _ in range(4)]
        )
        stats = (await c.get("/_mock/stats")).json()
    assert sorted(r.status_code for r in rs) == [200, 200, 429, 429]
    assert stats["max_concurrency_seen"] == 2


async def test_blocked_and_live_config_patch():
    async with client(blocked=True) as c:
        assert (await c.post("/v1/chat/completions", json=chat_body())).status_code == 401
        await c.patch("/_mock/config", json={"blocked": False})
        assert (await c.post("/v1/chat/completions", json=chat_body())).status_code == 200


async def test_mid_503_probability():
    async with client(p_503_mid=1.0) as c:
        r = await c.post("/v1/chat/completions", json=chat_body(model="mock-mid"))
        ok = await c.post("/v1/chat/completions", json=chat_body(model="mock-compact"))
    assert r.status_code == 503 and ok.status_code == 200


async def test_embeddings_deterministic_and_sized():
    async with client(embedding_dim=8) as c:
        a = (
            await c.post("/v1/embeddings", json={"model": "mock-embed", "input": ["x", "y"]})
        ).json()
        b = (await c.post("/v1/embeddings", json={"model": "mock-embed", "input": "x"})).json()
    assert len(a["data"]) == 2 and len(a["data"][0]["embedding"]) == 8
    assert a["data"][0]["embedding"] == b["data"][0]["embedding"]
    assert a["data"][0]["embedding"] != a["data"][1]["embedding"]
