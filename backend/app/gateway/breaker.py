"""A short circuit breaker for the embeddings endpoint (audit N-9): it is metered separately, and
during an outage job retries used to keep calling it (16 calls for one Tutor start).

closed → BREAKER_FAILS consecutive outage failures (503, network) → open for BREAKER_OPEN_S
(doubling on each trip, capped at BREAKER_MAX_OPEN_S): no call is made → after the cooldown,
half-open: ONE probe call; success closes it, failure reopens it for longer. One breaker per
provider, per process (the worker runs every embedding of a job)."""

from __future__ import annotations

from datetime import datetime, timedelta

BREAKER_FAILS = 3
BREAKER_OPEN_S = 60.0
BREAKER_MAX_OPEN_S = 300.0
PROBE_WAIT_S = 5.0  # others wait this long while the single probe call is in flight


class Breaker:
    def __init__(self) -> None:
        self.fails = 0
        self.trips = 0
        self.open_until: datetime | None = None
        self.probing = False

    def remaining(self, now: datetime) -> float:
        """Seconds until a call is allowed (0 = call now). Past the cooldown, the first caller
        becomes the probe; the others wait for its outcome."""
        if self.open_until is None:
            return 0.0
        if now < self.open_until:
            return (self.open_until - now).total_seconds()
        if self.probing:
            return PROBE_WAIT_S
        return 0.0

    def before_call(self, now: datetime) -> None:
        if self.open_until is not None and now >= self.open_until:
            self.probing = True

    def failure(self, now: datetime) -> None:
        self.fails += 1
        if self.probing or self.fails >= BREAKER_FAILS:
            self.trips += 1
            wait = min(BREAKER_OPEN_S * 2 ** (self.trips - 1), BREAKER_MAX_OPEN_S)
            self.open_until = now + timedelta(seconds=wait)
            self.fails, self.probing = 0, False

    def success(self) -> None:
        self.fails = self.trips = 0
        self.open_until, self.probing = None, False
