"""search(world, query): embed the query (interactive lane, cached), vector search in the
current provider's collection, filtered to the class's world, then join the text from Postgres.
The first half of narrow-before-generating; features add the compact filter step."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app import gateway
from app.core import db
from app.core.config import get_settings
from app.gateway import Lane
from app.jobs.registry import JobContext, job
from app.models import Chunk
from app.rag.store import get_store


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    score: float
    text: str
    page_ref: str
    chapter_id: uuid.UUID
    document_id: uuid.UUID
    tags: list[str]


async def search(
    world_id: uuid.UUID,
    query: str,
    *,
    course_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    levels: list[str] | None = None,
    k: int = 8,
    lane: Lane = "interactive",
) -> list[SearchHit]:
    res = await gateway.embed([query], lane, cache_query=True)
    store = get_store(get_settings().profile_for(res.provider))
    filters: dict[str, Any] = {
        "world_id": world_id,
        "course_id": course_id,
        "chapter_id": chapter_id,
    }
    if levels:
        filters["level_tags"] = levels
    hits = await store.search(res.vectors[0], filters, k=k)
    if not hits:
        return []
    async with db.get_sessionmaker()() as s:
        rows = {
            c.id: c
            for c in await s.scalars(select(Chunk).where(Chunk.id.in_([h.id for h in hits])))
        }
    return [
        SearchHit(
            chunk_id=h.id,
            score=h.score,
            text=rows[h.id].text,
            page_ref=rows[h.id].page_ref,
            chapter_id=rows[h.id].chapter_id,
            document_id=rows[h.id].document_id,
            tags=[t for t in rows[h.id].tags if t != "-"],
        )
        for h in hits
        if h.id in rows  # a vector whose chunk was deleted is skipped
    ]


@job("DEV_SEARCH", stages=("searching",))
async def dev_search(ctx: JobContext) -> dict[str, Any]:
    """Dev-only (POST /api/dev/search-jobs): a search run in the worker, like every AI call."""
    await ctx.set_stage("searching")
    hits = await search(
        uuid.UUID(ctx.payload["world_id"]), ctx.payload["query"], k=ctx.payload.get("k", 8)
    )
    return {
        "hits": [
            {
                "chunk_id": str(h.chunk_id),
                "score": round(h.score, 4),
                "chapter_id": str(h.chapter_id),
                "page_ref": h.page_ref,
                "tags": h.tags,
                "text": h.text[:400],
            }
            for h in hits
        ]
    }
