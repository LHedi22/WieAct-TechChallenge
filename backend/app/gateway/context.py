"""What the gateway knows about the call it is making, without changing any feature's signature.

The worker sets `current_job` around each job's handler (one asyncio task per job, so the value
never leaks between jobs); the gateway copies it into every `ai_call_log` row. A replay from
/admin/debug sets `debug_target` (mock or local only): the gateway then uses that provider, never
the cache, refuses cloud, and marks its log rows `debug` so no metric counts them.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class JobRef:
    job_id: uuid.UUID
    attempt: int
    user_id: uuid.UUID | None = None


current_job: ContextVar[JobRef | None] = ContextVar("current_job", default=None)
debug_target: ContextVar[str | None] = ContextVar("debug_target", default=None)
