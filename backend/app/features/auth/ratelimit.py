"""Sign-in attempt limits (audit F-SEC-5).

Per nickname (case-insensitive): MAX_FAILURES failed sign-ins within WINDOW_S lock that nickname for
LOCK_S, and while locked even the right password is refused (otherwise guessing just continues).
A successful sign-in clears the nickname's count. Per client IP: a looser cap across nicknames,
best effort (the IP comes from the proxy's X-Forwarded-For, which a client can influence).

In memory: production runs one API process (backend/start-prod.sh), so one limiter sees every
attempt; a restart clears the counts, which is acceptable for this threat model."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable

MAX_FAILURES = 5
WINDOW_S = 15 * 60
LOCK_S = 15 * 60
IP_MAX_FAILURES = 30


class LoginLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.fails: dict[str, deque[float]] = defaultdict(deque)
        self.locked_until: dict[str, float] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self.fails[key]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        return q

    def retry_after(self, nickname: str, ip: str | None) -> int:
        """Seconds to wait before this attempt is allowed (0 = go ahead)."""
        now = self.clock()
        waits = []
        for key in (f"n:{nickname.casefold()}", f"ip:{ip}" if ip else None):
            if key and (until := self.locked_until.get(key, 0.0)) > now:
                waits.append(until - now)
        return max(1, math.ceil(max(waits))) if waits else 0

    def failed(self, nickname: str, ip: str | None) -> None:
        now = self.clock()
        for key, cap in ((f"n:{nickname.casefold()}", MAX_FAILURES), (f"ip:{ip}", IP_MAX_FAILURES)):
            if key.startswith("ip:") and not ip:
                continue
            q = self._prune(key, now)
            q.append(now)
            if len(q) >= cap:
                self.locked_until[key] = now + LOCK_S
                q.clear()

    def succeeded(self, nickname: str) -> None:
        key = f"n:{nickname.casefold()}"
        self.fails.pop(key, None)
        self.locked_until.pop(key, None)


limiter = LoginLimiter()
