"""THE only place that talks to the LLM / embeddings. Features call `await gateway.run(Task)`."""

from functools import lru_cache

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.gateway.errors import (
    BadOutput,
    Defer,
    GatewayError,
    KeyBlocked,
    OfflineMode,
    RequestRejected,
)
from app.gateway.service import Gateway
from app.gateway.types import EmbedResult, Lane, Result, Task, TaskKind, Tier

__all__ = [
    "BadOutput",
    "Defer",
    "EmbedResult",
    "Gateway",
    "GatewayError",
    "KeyBlocked",
    "Lane",
    "OfflineMode",
    "RequestRejected",
    "Result",
    "Task",
    "TaskKind",
    "Tier",
    "get_gateway",
    "embed",
    "run",
]


@lru_cache
def get_gateway() -> Gateway:
    """One gateway (one limiter) per process — only the worker process calls it."""
    return Gateway(get_settings(), get_sessionmaker())


async def run(task: Task) -> Result:
    return await get_gateway().run(task)


async def embed(texts: list[str], lane: Lane, *, cache_query: bool = False) -> EmbedResult:
    return await get_gateway().embed(texts, lane, cache_query=cache_query)
