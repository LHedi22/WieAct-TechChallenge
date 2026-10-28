"""The platform's error contract (docs/PLATFORM.md) → what the gateway does about each response.

The exact quota status and header names are not documented, so classification is tolerant:
status first, then the message text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Literal

CallKind = Literal["quota", "saturated", "ceiling", "blocked", "transient", "bad_request"]

DEFAULT_QUOTA_DELAY_S = 30.0
DEFAULT_503_DELAY_S = 3.0

_CEILING = re.compile(
    r"(?:maximum|max(?:imum)?\s+response|limit|ceiling)\D{0,40}?(\d{2,7})", re.IGNORECASE
)
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s\b|sec|second)", re.IGNORECASE)


@dataclass(frozen=True)
class CallError:
    kind: CallKind
    status: int | None
    message: str
    retry_after_s: float | None = None
    ceiling: int | None = None
    ceiling_on_input: bool = False


# --- exceptions raised to the job layer (user-facing errors are i18n keys) -----------------------
class GatewayError(Exception):
    user_key = "errors.ai_failed"

    def __init__(self, message: str = "", *, refusal: str | None = None) -> None:
        super().__init__(message)
        self.refusal = refusal


class Defer(GatewayError):
    """Not now: requeue the job with not_before = now + delay (quota, saturation, network)."""

    user_key = "errors.quota_queue"

    def __init__(self, delay_s: float, reason: str) -> None:
        super().__init__(f"deferred {delay_s:.0f}s: {reason}", refusal=reason)
        self.delay_s = delay_s
        self.reason = reason


class KeyBlocked(GatewayError):
    """401 "Key is blocked": outside our slot. auto switches to local; production goes offline."""

    user_key = "errors.offline"


class OfflineMode(GatewayError):
    """Production outside the slot: only cached cloud results may be served."""

    user_key = "errors.offline"


class RequestRejected(GatewayError):
    """400 we could not fix by shrinking once."""


class BadOutput(GatewayError):
    """The model's JSON stayed invalid after one repair call."""


# --- parsing --------------------------------------------------------------------------------------
def _header(headers: dict[str, str], name: str) -> str | None:
    name = name.lower()
    return next((v for k, v in headers.items() if k.lower() == name), None)


def retry_after(headers: dict[str, str], message: str = "") -> float | None:
    """Seconds to wait, from Retry-After (seconds or HTTP date), x-ratelimit-reset*, or the text."""
    ra = _header(headers, "retry-after")
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            try:
                from datetime import UTC, datetime

                return max(0.0, (parsedate_to_datetime(ra) - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    for k, v in headers.items():
        kl = k.lower()
        if "reset" in kl and ("ratelimit" in kl or "quota" in kl):
            try:
                value = float(v)
            except ValueError:
                continue
            return value / 1000 if kl.endswith("ms") else value
    m = _SECONDS.search(message)
    return float(m.group(1)) if m else None


def classify(status: int | None, headers: dict[str, str], message: str) -> CallError:
    text = (message or "").lower()
    if status is None:
        return CallError("transient", None, message)
    if status == 429 or "quota" in text or "rate limit" in text:
        delay = retry_after(headers, message)
        return CallError("quota", status, message, delay or DEFAULT_QUOTA_DELAY_S)
    if status in (401, 403):
        return CallError("blocked", status, message)
    if status == 400:
        m = _CEILING.search(message)
        if m or "too long" in text or "exceeds" in text:
            on_input = any(w in text for w in ("context", "input", "prompt"))
            return CallError(
                "ceiling",
                status,
                message,
                ceiling=int(m.group(1)) if m else None,
                ceiling_on_input=on_input,
            )
        return CallError("bad_request", status, message)
    if status == 503:
        return CallError(
            "saturated", status, message, retry_after(headers, message) or DEFAULT_503_DELAY_S
        )
    if status >= 500 or status == 408:
        return CallError("transient", status, message, retry_after(headers, message))
    return CallError("bad_request", status, message)
