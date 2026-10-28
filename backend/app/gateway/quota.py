"""Quota headers → QuotaState. Header names are undocumented: match tolerantly and log each new
x-*/ratelimit-* header name once (names only — values may be sensitive)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("gateway.quota")

LOW_WATERMARK = 3  # remaining requests at which the background lane pauses
_IGNORED = {"x-content-type-options", "x-frame-options", "x-request-id", "x-xss-protection"}
_seen: set[str] = set()


@dataclass
class QuotaState:
    remaining: int | None = None
    reset_s: float | None = None
    observed_at: float = 0.0

    @property
    def low(self) -> bool:
        if self.remaining is None or self.remaining > LOW_WATERMARK:
            return False
        # Stale observations stop pausing once the bucket has had time to refill.
        return self.reset_s is None or time.monotonic() < self.observed_at + self.reset_s

    def resume_in_s(self) -> float:
        if not self.low or self.reset_s is None:
            return 0.0
        return max(0.0, self.observed_at + self.reset_s - time.monotonic())


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
        if "remaining" in kl and ("request" in kl or "token" not in kl):
            state.remaining = int(n)
            found = True
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
