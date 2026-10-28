"""The only module that imports the OpenAI SDK. One whole (non-streamed) chat call per invocation;
retries and contract handling belong to the gateway, so the SDK's own retries are off."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from app.core.config import LLMProfile
from app.gateway.errors import CallError, classify
from app.gateway.jsonfix import strip_think


@dataclass
class Reply:
    text: str
    headers: dict[str, str]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    status: int = 200


@dataclass
class CallFailed(Exception):  # noqa: N818 - reads better at call sites than CallFailedError
    error: CallError
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: int = 0


def _error_text(e: openai.APIStatusError) -> str:
    try:
        body = e.response.json()
    except ValueError:
        return e.response.text[:500]
    err = body.get("error", body) if isinstance(body, dict) else body
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)


def _mentions(text: str, *words: str) -> bool:
    t = text.lower()
    return any(w in t for w in words)


class LLMClient:
    def __init__(
        self,
        profile: LLMProfile,
        *,
        timeout_s: float,
        disable_thinking: bool,
        json_mode: str = "auto",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.profile = profile
        self.disable_thinking = disable_thinking
        self.json_mode = json_mode
        self._sdk = AsyncOpenAI(
            base_url=profile.base_url,
            api_key=profile.api_key.get_secret_value() or "unset",
            timeout=timeout_s,
            max_retries=0,
            http_client=http_client,
        )
        # Learned per model for this process: features the server rejected with a 400.
        self._no_json_mode: set[str] = set()
        self._no_template_kwargs: set[str] = set()

    def prepare(self, model: str, messages: list[dict[str, Any]], kind: str, language: str):
        msgs = [dict(m) for m in messages]
        system = next((m for m in msgs if m.get("role") == "system"), None)
        if system is None:
            system = {"role": "system", "content": ""}
            msgs.insert(0, system)
        extra = ""
        if self.disable_thinking and "qwen3" in model.lower():
            extra += " /no_think"  # Qwen3 soft switch, honoured by Ollama and vLLM alike
        if self.profile.provider == "mock":
            extra += f" <!-- task: {kind} --> <!-- lang: {language} -->"  # mock fixture markers
        system["content"] = (str(system["content"]) + extra).strip()
        return msgs

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        json_mode: bool,
        kind: str,
        language: str,
    ) -> Reply:
        msgs = self.prepare(model, messages, kind, language)
        for _ in range(3):  # at most: drop response_format, drop chat_template_kwargs, real call
            use_json = (
                json_mode
                and self.json_mode != "off"
                and (self.json_mode == "on" or model not in self._no_json_mode)
            )
            use_tk = (
                self.disable_thinking
                and self.profile.provider == "cloud"
                and model not in self._no_template_kwargs
            )
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": msgs,
                "max_tokens": max_tokens,
                "temperature": 0.3,
                "stream": False,
            }
            if use_json:
                kwargs["response_format"] = {"type": "json_object"}
            if use_tk:
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            t0 = time.monotonic()
            try:
                raw = await self._sdk.chat.completions.with_raw_response.create(**kwargs)
            except openai.APIStatusError as e:
                ms = int((time.monotonic() - t0) * 1000)
                text = _error_text(e)
                if (
                    e.status_code == 400
                    and use_json
                    and self.json_mode == "auto"
                    and _mentions(text, "response_format", "json_object", "json mode")
                ):
                    self._no_json_mode.add(model)
                    continue
                if (
                    e.status_code == 400
                    and use_tk
                    and _mentions(
                        text, "chat_template", "enable_thinking", "extra", "unknown field"
                    )
                ):
                    self._no_template_kwargs.add(model)
                    continue
                headers = dict(e.response.headers)
                raise CallFailed(classify(e.status_code, headers, text), headers, ms) from e
            except openai.APIConnectionError as e:  # includes timeouts
                ms = int((time.monotonic() - t0) * 1000)
                raise CallFailed(classify(None, {}, type(e).__name__), {}, ms) from e
            ms = int((time.monotonic() - t0) * 1000)
            completion = raw.parse()
            usage = completion.usage
            content = completion.choices[0].message.content if completion.choices else ""
            return Reply(
                text=strip_think(content or ""),
                headers=dict(raw.headers),
                tokens_in=usage.prompt_tokens if usage else 0,
                tokens_out=usage.completion_tokens if usage else 0,
                latency_ms=ms,
            )
        raise CallFailed(classify(400, {}, "request rejected after dropping optional fields"))
