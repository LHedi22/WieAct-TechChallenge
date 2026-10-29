"""Job kind → handler + its human-readable stages (shown on the loading screen)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.gateway import Result


@dataclass
class JobContext:
    job_id: uuid.UUID
    kind: str
    lane: str
    payload: dict[str, Any]
    set_stage: Callable[[str], Awaitable[None]]
    quick_mode: bool = False  # set by the handler when any gateway result was quick_mode

    def note(self, result: Result) -> Result:
        self.quick_mode = self.quick_mode or result.quick_mode
        return result


Handler = Callable[[JobContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class JobSpec:
    handler: Handler
    stages: tuple[str, ...]


HANDLERS: dict[str, JobSpec] = {}


def job(kind: str, stages: tuple[str, ...]) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = JobSpec(fn, stages)
        return fn

    return register


def spec_for(kind: str) -> JobSpec:
    # Always load the full list: importing one feature module registers only its own handlers.
    import app.jobs.handlers  # noqa: F401, PLC0415  (registers every handler)

    return HANDLERS[kind]
