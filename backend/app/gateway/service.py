"""gateway.run(Task): the platform's error contract applied in one place (docs/PLATFORM.md).

cache? → provider for this job → limiter (2 in flight, RPM, interactive first) → call →
  503         interactive: one retry, then compact fallback (quick_mode) · background: Defer
  quota       Defer(stated delay) — the job is requeued with not_before
  400 ceiling shrink max_tokens (or the input) and resend once; remember the ceiling
  401 blocked auto: re-resolve (→ local) and continue · otherwise KeyBlocked / OfflineMode
  network     one quick retry, then Defer
→ JSON parse (tolerant) → one compact repair call if needed → cache → call log
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import LLMProfile, Settings
from app.gateway import cache, log
from app.gateway.client import CallFailed, LLMClient, Reply
from app.gateway.errors import (
    BadOutput,
    Defer,
    KeyBlocked,
    OfflineMode,
    RequestRejected,
)
from app.gateway.jsonfix import REPAIR_SYSTEM, extract_json
from app.gateway.limiter import Limiter
from app.gateway.providers import Resolution, resolve
from app.gateway.quota import QuotaTracker
from app.gateway.router import route_for
from app.gateway.types import Result, Task, TaskKind, Tier

logger = logging.getLogger("gateway")

ClientFactory = Callable[[LLMProfile], LLMClient]
MAX_ATTEMPTS = 6
INTERACTIVE_503_WAIT_CAP_S = 5.0


def _shrink_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the system prompt and the last user turn; cut the longest remaining text by 40%."""
    system = [dict(m) for m in messages if m.get("role") == "system"][:1]
    last = [dict(m) for m in messages if m.get("role") != "system"][-1:]
    out = system + last
    longest = max(out, key=lambda m: len(str(m.get("content", ""))), default=None)
    if longest is not None:
        text = str(longest.get("content", ""))
        longest["content"] = text[: int(len(text) * 0.6)]
    return out


class Gateway:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        client_factory: ClientFactory | None = None,
        limiter: Limiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.sm = sessionmaker
        self.quota = QuotaTracker()
        self.limiter = limiter or Limiter(
            settings.LLM_MAX_RPM,
            settings.LLM_MAX_CONCURRENCY,
            background_pause=self._background_pause,
        )
        self._client_factory = client_factory or self._default_client
        self._clients: dict[str, LLMClient] = {}
        self._ceilings: dict[str, int] = {}  # learned max_tokens ceiling per provider
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    # --- plumbing ---------------------------------------------------------------------------------
    def _default_client(self, profile: LLMProfile) -> LLMClient:
        s = self.settings
        return LLMClient(
            profile,
            timeout_s=s.LLM_TIMEOUT_S,
            disable_thinking=s.LLM_DISABLE_THINKING,
            json_mode=s.LLM_JSON_MODE,
        )

    def client(self, profile: LLMProfile) -> LLMClient:
        key = f"{profile.provider}|{profile.base_url}"
        if key not in self._clients:
            self._clients[key] = self._client_factory(profile)
        return self._clients[key]

    def _background_pause(self) -> float:
        return max((self.quota.get(p).resume_in_s() for p in ("cloud", "local", "mock")), default=0)

    @staticmethod
    def _model(profile: LLMProfile, tier: Tier) -> str:
        return profile.model_mid if tier == "mid" else profile.model_compact

    async def _log(self, task: Task, profile: LLMProfile, tier: Tier, model: str, **f) -> None:
        await log.write(
            self.sm,
            task_kind=f.pop("kind", task.kind.value),
            lane=task.lane,
            model_tier=tier,
            provider=profile.provider,
            model=model,
            **f,
        )

    async def _call(
        self,
        task: Task,
        profile: LLMProfile,
        model: str,
        max_tokens: int,
        json_mode: bool,
        messages: list[dict[str, Any]],
        kind: TaskKind | None = None,
    ) -> Reply:
        async with self.limiter.slot(task.lane):
            try:
                reply = await self.client(profile).chat(
                    model,
                    messages,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    kind=(kind or task.kind).value,
                    language=task.language,
                )
            except CallFailed as failed:
                self.quota.update(profile.provider, failed.headers)
                raise
        self.quota.update(profile.provider, reply.headers)
        return reply

    # --- the contract -----------------------------------------------------------------------------
    async def run(self, task: Task) -> Result:
        route = route_for(task.kind)
        tier: Tier = task.tier or route.tier
        pattern = route.pattern
        res: Resolution = await resolve(self.settings, self.sm, self._now())
        profile = res.profile
        model = self._model(profile, tier)

        key = None
        if task.cache_key:
            key = cache.cache_key(
                profile.provider, model, task.kind.value, task.prompt_version, task.cache_key
            )
            hit = await cache.get(self.sm, key)
            if hit is not None:
                await self._log(task, profile, tier, model, cache_hit=True, pattern=pattern)
                return Result(
                    content=hit.content.get("value"),
                    model_tier=tier,
                    model=model,
                    provider=profile.provider,
                    pattern=pattern,
                    cached=True,
                )
        if res.offline:
            raise OfflineMode(res.reason)

        json_mode = task.response_format == "json"
        max_tokens = task.max_tokens or route.max_tokens
        if ceiling := self._ceilings.get(profile.provider):
            max_tokens = min(max_tokens, ceiling)
        messages = task.messages
        quick_mode = shrunk = retried_503 = retried_net = rerouted = False
        notes: list[str] = []

        for _ in range(MAX_ATTEMPTS):
            rhash = cache.request_hash(
                profile.provider, model, messages, max_tokens=max_tokens, json=json_mode
            )
            failed: CallFailed | None = None
            try:
                reply = await self._call(task, profile, model, max_tokens, json_mode, messages)
            except CallFailed as e:
                failed = e
            if failed is not None:  # handled outside `except` so raises below aren't chained
                err = failed.error
                await self._log(
                    task,
                    profile,
                    tier,
                    model,
                    pattern=pattern,
                    status_code=err.status,
                    latency_ms=failed.latency_ms,
                    refusal_reason=err.kind,
                    request_hash=rhash,
                    fallback=quick_mode,
                )
                if err.kind == "saturated":
                    if task.lane == "interactive" and not retried_503:
                        retried_503 = True
                        await self._sleep(min(err.retry_after_s or 3, INTERACTIVE_503_WAIT_CAP_S))
                        continue
                    if task.lane == "interactive" and tier == "mid" and task.allow_fallback:
                        tier, model, quick_mode, pattern = (
                            "compact",
                            self._model(profile, "compact"),
                            True,
                            "fallback",
                        )
                        notes.append("mid saturated: compact fallback")
                        continue
                    raise Defer(err.retry_after_s or 3, "saturated")
                if err.kind == "quota":
                    raise Defer(err.retry_after_s or 30, "quota")
                if err.kind == "ceiling" and not shrunk:
                    shrunk = True
                    if err.ceiling_on_input:
                        messages = _shrink_input(messages)
                        notes.append("shrunk input")
                    else:
                        target = int(max_tokens * 0.6)
                        if err.ceiling and err.ceiling < max_tokens:
                            target = err.ceiling
                            self._ceilings[profile.provider] = err.ceiling
                        max_tokens = max(16, target)
                        notes.append(f"shrunk max_tokens to {max_tokens}")
                    continue
                if err.kind == "blocked":
                    if self.settings.LLM_PROVIDER == "auto" and not rerouted:
                        rerouted = True  # this 401 is now in the log: resolve() picks local
                        res = await resolve(self.settings, self.sm, self._now())
                        if res.profile.provider != profile.provider:
                            profile, model = res.profile, self._model(res.profile, tier)
                            notes.append(f"key blocked: switched to {profile.provider}")
                            continue
                    if self.settings.APP_ENV == "production":
                        raise OfflineMode("blocked")
                    raise KeyBlocked(err.message)
                if err.kind == "transient":
                    if not retried_net:
                        retried_net = True
                        await self._sleep(1)
                        continue
                    raise Defer(err.retry_after_s or 10, "transient")
                raise RequestRejected(err.message, refusal=err.kind)

            await self._log(
                task,
                profile,
                tier,
                model,
                pattern=pattern,
                status_code=200,
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                latency_ms=reply.latency_ms,
                request_hash=rhash,
                fallback=quick_mode,
            )
            content: Any = reply.text
            tokens_in, tokens_out, latency = reply.tokens_in, reply.tokens_out, reply.latency_ms
            if json_mode:
                content = extract_json(reply.text)
                if content is None:
                    fixed = await self._repair(task, profile, reply.text, max_tokens)
                    content = fixed.get("content")
                    tokens_in += fixed.get("tokens_in", 0)
                    tokens_out += fixed.get("tokens_out", 0)
                    latency += fixed.get("latency_ms", 0)
                    if content is None:
                        raise BadOutput("invalid JSON after one repair call", refusal="bad_json")
                    notes.append("repaired JSON")
            if key and not quick_mode:  # a quick-mode answer must not become the class's copy
                await cache.put(
                    self.sm,
                    key=key,
                    kind=task.kind.value,
                    content=content,
                    tier=tier,
                    provider=profile.provider,
                    model=model,
                )
            return Result(
                content=content,
                model_tier=tier,
                model=model,
                provider=profile.provider,
                pattern=pattern,
                quick_mode=quick_mode,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency,
                notes=notes,
            )
        raise Defer(10, "too_many_attempts")

    async def _repair(
        self, task: Task, profile: LLMProfile, broken: str, max_tokens: int
    ) -> dict[str, Any]:
        """ONE compact call to fix the JSON (docs/ARCHITECTURE.md §JSON outputs)."""
        model = self._model(profile, "compact")
        messages = [
            {"role": "system", "content": REPAIR_SYSTEM},
            {"role": "user", "content": broken[:6000]},
        ]
        try:
            reply = await self._call(
                task, profile, model, max_tokens, True, messages, kind=TaskKind.JSON_REPAIR
            )
        except CallFailed as failed:
            await self._log(
                task,
                profile,
                "compact",
                model,
                kind=TaskKind.JSON_REPAIR.value,
                pattern="repair",
                status_code=failed.error.status,
                refusal_reason=failed.error.kind,
            )
            return {}
        await self._log(
            task,
            profile,
            "compact",
            model,
            kind=TaskKind.JSON_REPAIR.value,
            pattern="repair",
            status_code=200,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            latency_ms=reply.latency_ms,
        )
        return {
            "content": extract_json(reply.text),
            "tokens_in": reply.tokens_in,
            "tokens_out": reply.tokens_out,
            "latency_ms": reply.latency_ms,
        }
