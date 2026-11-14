"""Quota headers → QuotaState. Header names are undocumented: match tolerantly and log each new
x-*/ratelimit-* header name once (names only — values may be sensitive)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("gateway.quota")

LOW_WATERMARK = 3  # remaining requests at which the background lane pauses
DEFAULT_LIMIT_RPM = 20.0  # the platform's rate when no limit header came (PLATFORM.md)
_IGNORED = {"x-content-type-options", "x-frame-options", "x-request-id", "x-xss-protection"}
_seen: set[str] = set()


@dataclass
class QuotaState:
    remaining: int | None = None
    reset_s: float | None = None
    limit_rpm: float | None = None  # the key's sustained rate, when a limit header says it
    observed_at: float = 0.0

    def pause_s(self) -> float:
        """How long after the observation the background lane waits. The platform sends no reset
        header (DECISIONS 2026-11-09), so without one this is the time the token bucket needs to
        refill above LOW_WATERMARK at the key's rate (audit OPT-06)."""
        if self.remaining is None or self.remaining > LOW_WATERMARK:
            return 0.0
        if self.reset_s is not None:
            return self.reset_s
        rpm = self.limit_rpm or DEFAULT_LIMIT_RPM
        return (LOW_WATERMARK + 1 - self.remaining) * 60 / rpm

    @property
    def low(self) -> bool:
        # Stale observations stop pausing once the bucket has had time to refill.
        return time.monotonic() < self.observed_at + self.pause_s()

    def resume_in_s(self) -> float:
        return max(0.0, self.observed_at + self.pause_s() - time.monotonic())


def _number(v: str) -> float | None:
    try:
        return float(v.split(",")[0].strip().rstrip("s"))
    except ValueError:
        return None


def parse(headers: dict[str, str]) -> QuotaState | None:
    """None when no quota header is present."""
    state = QuotaState(observed_at=time.monotonic())
    found = False
    for k, v in headers.items():
        kl = k.lower()
        if kl.startswith(("x-", "ratelimit")) and kl not in _IGNORED and kl not in _seen:
            _seen.add(kl)
            log.info("quota header seen: %s", kl)
        if not ("ratelimit" in kl or "quota" in kl or kl.startswith("x-rate")):
            continue
        n = _number(v)
        if n is None:
            continue
        if "parallel" in kl:  # concurrency slots left (platform, 9/11), not requests
            continue
        if "remaining" in kl and ("request" in kl or "token" not in kl):
            state.remaining = int(n)
            found = True
        elif "limit" in kl and ("request" in kl or "rpm" in kl) and "token" not in kl:
            state.limit_rpm = n  # x-ratelimit-api_key-limit-requests, x-litellm-key-rpm-limit
        elif "reset" in kl:
            state.reset_s = n / 1000 if kl.endswith("ms") else n
            found = True
    return state if found else None


def seen_header_names() -> list[str]:
    return sorted(_seen)


class QuotaTracker:
    """Latest QuotaState per provider (the bucket is per key)."""

    def __init__(self) -> None:
        self._state: dict[str, QuotaState] = {}

    def update(self, provider: str, headers: dict[str, str]) -> None:
        state = parse(headers)
        if state:
            self._state[provider] = state

    def get(self, provider: str) -> QuotaState:
        return self._state.get(provider, QuotaState())
