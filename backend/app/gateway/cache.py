"""ai_cache: shareable outputs are generated once. The key includes provider and model so local or
mock results never stand in for cloud ones (offline demo mode serves cloud results only)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AICache


def cache_key(provider: str, model: str, kind: str, prompt_version: str, key: str) -> str:
    raw = json.dumps([provider, model, kind, prompt_version, key], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_hash(provider: str, model: str, messages: list[dict[str, Any]], **params: Any) -> str:
    raw = json.dumps([provider, model, messages, params], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get(sm: async_sessionmaker[AsyncSession], key: str) -> AICache | None:
    async with sm() as s:
        row = await s.get(AICache, key)
        if row is not None:
            await s.execute(update(AICache).where(AICache.key == key).values(hits=AICache.hits + 1))
            await s.commit()
        return row


async def put(
    sm: async_sessionmaker[AsyncSession],
    *,
    key: str,
    kind: str,
    content: Any,
    tier: str,
    provider: str,
    model: str,
) -> None:
    async with sm() as s:
        await s.merge(
            AICache(
                key=key,
                task_kind=kind,
                content={"value": content},
                model_tier=tier,
                provider=provider,
                model=model,
                hits=0,
            )
        )
        await s.commit()
