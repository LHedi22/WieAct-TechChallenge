"""Fake EdNova platform: OpenAI-compatible, whole responses only, with the platform's error contract
(docs/PLATFORM.md) reproducible on demand. Run: uvicorn mock_llm.app:app --port 9000."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mock_llm.config import MockConfig

FIXTURES = Path(__file__).parent / "fixtures"
TASK_MARK = re.compile(r"<!--\s*task:\s*([A-Z_]+)\s*-->")
LANG_MARK = re.compile(r"<!--\s*lang:\s*([a-zA-Z-]+)\s*-->")
FAULTS = {"503", "quota", "400", "badjson", "slow", "blocked"}


class Bucket:
    """Token bucket: `rate_per_min` sustained, up to `capacity`, continuous refill (no reset)."""

    def __init__(self, rate_per_min: float, capacity: int) -> None:
        self.rate = rate_per_min / 60
        self.capacity = capacity
        self.tokens = float(capacity)
        self.t = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
        self.t = now

    def take(self) -> float:
        """Consume one unit; return 0 on success or the seconds until one is available."""
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate if self.rate else 60.0

    def remaining(self) -> int:
        self._refill()
        return int(self.tokens)

    def reset_ms(self) -> int:
        self._refill()
        return int((self.capacity - self.tokens) / self.rate * 1000) if self.rate else 0


class Stats:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.by_status: dict[str, int] = {}
        self.by_tier: dict[str, int] = {}
        self.active = 0
        self.max_active = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "by_status": self.by_status,
            "by_tier": self.by_tier,
            "active": self.active,
            "max_concurrency_seen": self.max_active,
        }


def _error(status: int, message: str, kind: str, headers: dict[str, str] | None = None):
    return JSONResponse({"error": {"message": message, "type": kind}}, status, headers=headers)


def _fault(request: Request) -> str | None:
    f = (request.headers.get("x-mock-fault") or "").strip().lower()
    return f if f in FAULTS else None


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _topic(messages: list[dict[str, Any]]) -> str:
    user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    words = re.findall(r"\w+", str(user.get("content", "")))
    return " ".join(words[:6]) or "the material"


def _content(messages: list[dict[str, Any]], json_wanted: bool) -> str:
    system = " ".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    task = TASK_MARK.search(system)
    lang_mark = LANG_MARK.search(system)
    lang = lang_mark.group(1) if lang_mark else "en"
    topic = _topic(messages)
    if task:
        for name in (
            f"{task.group(1)}.{lang}.json",
            f"{task.group(1)}.{lang[:2]}.json",
            f"{task.group(1)}.en.json",
        ):
            path = FIXTURES / name
            if path.exists():
                return path.read_text(encoding="utf-8").replace("{topic}", topic).strip()
    if json_wanted:
        return json.dumps({"text": f"Mock reply about {topic}."})
    return f"Mock reply about {topic}."


def _break_json(text: str) -> str:
    """Almost-JSON, the way small models break it: fenced, trailing comma, missing brace."""
    return "```json\n" + text.rstrip().rstrip("}") + ",\n```"


def _embedding(text: str, dim: int) -> list[float]:
    rng = random.Random(hashlib.sha256(text.encode("utf-8")).digest())
    v = [rng.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def create_app(config: MockConfig | None = None, *, seed: int | None = None) -> FastAPI:
    app = FastAPI(title="mock-llm")
    cfg = config or MockConfig.from_env()
    app.state.cfg = cfg
    app.state.bucket = Bucket(cfg.rpm, cfg.burst)
    app.state.embed_bucket = Bucket(cfg.embedding_rpm, max(cfg.burst, 10))
    app.state.stats = Stats()
    app.state.rng = random.Random(seed)
    lock = asyncio.Lock()

    def quota_headers() -> dict[str, str]:
        c: MockConfig = app.state.cfg
        b: Bucket = app.state.bucket
        return {c.header_remaining: str(b.remaining()), c.header_reset_ms: str(b.reset_ms())}

    def quota_exhausted(delay: float):
        c: MockConfig = app.state.cfg
        d = max(1, math.ceil(delay))
        return _error(
            c.quota_status,
            f"team quota exhausted, retry in {d} s",
            "quota_exhausted",
            {"Retry-After": str(d), **quota_headers()},
        )

    def record(status: int, tier: str) -> None:
        s: Stats = app.state.stats
        s.calls += 1
        s.by_status[str(status)] = s.by_status.get(str(status), 0) + 1
        s.by_tier[tier] = s.by_tier.get(tier, 0) + 1

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        c: MockConfig = app.state.cfg
        if c.blocked:
            return _error(401, "Key is blocked", "auth_error")
        ids = [c.model_compact, c.model_mid, c.model_embedding]
        return {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        c: MockConfig = app.state.cfg
        rng: random.Random = app.state.rng
        body = await request.json()
        fault = _fault(request)
        model = str(body.get("model", ""))
        tier = "mid" if model == c.model_mid or "mid" in model else "compact"

        def done(resp):
            record(resp.status_code, tier)
            return resp

        if c.blocked or fault == "blocked":
            return done(_error(401, "Key is blocked", "auth_error"))
        if body.get("stream"):
            return done(_error(400, "streaming is not supported", "invalid_request_error"))
        if model not in (c.model_compact, c.model_mid):
            return done(_error(404, f"model {model!r} not found", "not_found"))
        max_tokens = int(body.get("max_tokens") or 256)
        if max_tokens > c.max_tokens_ceiling or fault == "400":
            return done(
                _error(
                    400,
                    f"max_tokens {max_tokens} exceeds the maximum response length of "
                    f"{c.max_tokens_ceiling} tokens",
                    "invalid_request_error",
                )
            )
        wait = app.state.bucket.take()
        if wait:
            return done(quota_exhausted(wait))
        if fault == "quota" or rng.random() < c.p_quota:
            return done(quota_exhausted(c.quota_delay_s))
        p503 = c.p_503_mid if tier == "mid" else c.p_503_compact
        if fault == "503" or rng.random() < p503:
            return done(
                _error(
                    503,
                    f"model class {tier} saturated",
                    "overloaded",
                    {"Retry-After": str(c.retry_after_503_s)},
                )
            )

        s: Stats = app.state.stats
        async with lock:
            if s.active >= c.max_concurrency:
                return done(quota_exhausted(1))
            s.active += 1
            s.max_active = max(s.max_active, s.active)
        try:
            lo, hi = c.latency_mid_ms if tier == "mid" else c.latency_compact_ms
            ms = rng.uniform(lo, hi) * (4 if fault == "slow" else 1)
            await asyncio.sleep(ms / 1000)
            messages = body.get("messages") or []
            json_wanted = (body.get("response_format") or {}).get("type") == "json_object"
            text = _content(messages, json_wanted)
            if fault == "badjson" or (
                text.lstrip().startswith("{") and rng.random() < c.p_bad_json
            ):
                text = _break_json(text)
            prompt_text = " ".join(str(m.get("content", "")) for m in messages)
            usage = {"prompt_tokens": _tokens(prompt_text), "completion_tokens": _tokens(text)}
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            payload = {
                "id": f"mock-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
            return done(JSONResponse(payload, headers=quota_headers()))
        finally:
            async with lock:
                s.active -= 1

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        c: MockConfig = app.state.cfg
        if c.blocked or _fault(request) == "blocked":
            return _error(401, "Key is blocked", "auth_error")
        body = await request.json()
        wait = app.state.embed_bucket.take()
        if wait:
            return quota_exhausted(wait)
        inputs = body.get("input")
        texts = [inputs] if isinstance(inputs, str) else list(inputs or [])
        data = [
            {"object": "embedding", "index": i, "embedding": _embedding(t, c.embedding_dim)}
            for i, t in enumerate(texts)
        ]
        tokens = sum(_tokens(t) for t in texts)
        return {
            "object": "list",
            "model": body.get("model", c.model_embedding),
            "data": data,
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    @app.get("/_mock/config")
    def get_config() -> dict[str, Any]:
        return app.state.cfg.model_dump()

    @app.patch("/_mock/config")
    async def patch_config(request: Request) -> dict[str, Any]:
        changes = await request.json()
        app.state.cfg = app.state.cfg.model_copy(update=changes)
        c: MockConfig = app.state.cfg
        if {"rpm", "burst"} & changes.keys():
            app.state.bucket = Bucket(c.rpm, c.burst)
        return c.model_dump()

    @app.get("/_mock/stats")
    def stats() -> dict[str, Any]:
        return app.state.stats.as_dict()

    @app.delete("/_mock/stats")
    def reset_stats() -> dict[str, Any]:
        app.state.stats.reset()
        return app.state.stats.as_dict()

    return app


app = create_app()
