"""Pacing for one API key: at most `concurrency` calls in flight and `rpm` calls per minute
(token bucket, continuous refill). Interactive callers are always served before background ones,
and the background lane pauses while the platform reports a low quota.

Process-local by design: only the single worker process calls the gateway (backend/CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from app.gateway.types import Lane


class Limiter:
    def __init__(
        self,
        rpm: float,
        concurrency: int,
        *,
        burst: int | None = None,
        background_pause: Callable[[], float] | None = None,
    ) -> None:
        self.rate = rpm / 60
        self.capacity = float(burst or max(1, min(3, int(rpm))))
        self.tokens = self.capacity
        self.stamp = time.monotonic()
        self.concurrency = concurrency
        self.active = 0
        self.max_active = 0
        self.waiting = {"interactive": 0, "background": 0}
        # Returns seconds the background lane should keep waiting (0 = go).
        self.background_pause = background_pause or (lambda: 0.0)
        self._cond = asyncio.Condition()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now

    def _wait_hint(self, lane: Lane) -> float | None:
        """None if `lane` may go now, else seconds worth sleeping before rechecking."""
        if self.active >= self.concurrency:
            return 1.0  # woken by release()
        if lane == "background":
            if self.waiting["interactive"]:
                return 1.0
            pause = self.background_pause()
            if pause > 0:
                return min(pause, 5.0)
        self._refill()
        if self.tokens < 1:
            return (1 - self.tokens) / self.rate if self.rate else 1.0
        return None

    async def acquire(self, lane: Lane) -> None:
        async with self._cond:
            self.waiting[lane] += 1
            try:
                while (hint := self._wait_hint(lane)) is not None:
                    with suppress(TimeoutError):  # timed out = recheck the bucket
                        await asyncio.wait_for(self._cond.wait(), timeout=hint)
                self.tokens -= 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            finally:
                self.waiting[lane] -= 1

    async def release(self) -> None:
        async with self._cond:
            self.active -= 1
            self._cond.notify_all()

    @asynccontextmanager
    async def slot(self, lane: Lane) -> AsyncIterator[None]:
        await self.acquire(lane)
        try:
            yield
        finally:
            await self.release()
