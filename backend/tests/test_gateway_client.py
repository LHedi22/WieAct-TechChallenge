"""LLMClient: Qwen3 thinking off, optional fields dropped on a 400, <think> stripped."""

import json

import httpx
from pydantic import SecretStr

from app.core.config import LLMProfile
from app.gateway.client import LLMClient


def profile(provider="cloud") -> LLMProfile:
    return LLMProfile(
        provider=provider,
        base_url="http://p/v1",
        api_key=SecretStr("k"),
        model_compact="qwen3-1.7b",
        model_mid="qwen3-14b",
        embedding_model="bge-m3",
        embedding_dim=1024,
    )


def ok(content: str) -> httpx.Response:
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
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
    )


def client(handler, provider="cloud", **kw) -> LLMClient:
    return LLMClient(
        profile(provider),
        timeout_s=5,
        disable_thinking=True,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kw,
    )


async def chat(c: LLMClient, json_mode=False):
    return await c.chat(
        "qwen3-14b",
        [{"role": "user", "content": "hi"}],
        max_tokens=50,
        json_mode=json_mode,
        kind="DEMO_SUMMARY",
        language="en",
    )


async def test_qwen3_thinking_disabled_and_think_stripped():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return ok("<think>\nlet me think\n</think>\nHello")

    reply = await chat(client(handler))
    body = bodies[0]
    assert body["messages"][0]["role"] == "system" and "/no_think" in body["messages"][0]["content"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["stream"] is False
    assert reply.text == "Hello" and reply.tokens_out == 4


async def test_chat_template_kwargs_dropped_on_400_and_remembered():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(
                400, json={"error": {"message": "unknown field chat_template_kwargs"}}
            )
        return ok("Hi")

    c = client(handler)
    assert (await chat(c)).text == "Hi"
    await chat(c)
    assert ["chat_template_kwargs" in b for b in bodies] == [True, False, False]


async def test_json_mode_dropped_on_400_in_auto():
    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format not supported"}})
        return ok('{"a": 1}')

    c = client(handler, provider="local")
    await chat(c, json_mode=True)
    await chat(c, json_mode=True)
    assert ["response_format" in b for b in bodies] == [True, False, False]
    assert all("chat_template_kwargs" not in b for b in bodies)  # cloud-only field


async def test_mock_gets_task_and_language_markers():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return ok("x")

    await chat(client(handler, provider="mock"))
    system = bodies[0]["messages"][0]["content"]
    assert "<!-- task: DEMO_SUMMARY -->" in system and "<!-- lang: en -->" in system


async def test_status_errors_become_classified_failures():
    def handler(req):
        return httpx.Response(
            503, headers={"Retry-After": "4"}, json={"error": {"message": "busy"}}
        )

    try:
        await chat(client(handler))
    except Exception as e:  # CallFailed
        assert e.error.kind == "saturated" and e.error.retry_after_s == 4
    else:
        raise AssertionError("expected CallFailed")
