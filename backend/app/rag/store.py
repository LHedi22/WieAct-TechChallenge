"""VectorStore: Qdrant holds vectors + filter payload only; chunk text lives in Postgres.

One collection per provider + embedding model (`Settings.collection_for`), sized by that profile's
embedding dim, cosine distance, keyword payload indexes on the filter fields."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models

from app.core.config import LLMProfile, get_settings

FILTER_FIELDS = ("world_id", "course_id", "chapter_id", "document_id", "level_tags")


@dataclass
class VectorPoint:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    collection: str

    async def ensure_collection(self) -> None: ...
    async def upsert(self, points: list[VectorPoint]) -> None: ...
    async def search(
        self, vector: list[float], filters: dict[str, Any], k: int = 8
    ) -> list[Hit]: ...
    async def delete_document(self, document_id: uuid.UUID) -> None: ...
    async def count(self, filters: dict[str, Any] | None = None) -> int: ...


def _filter(filters: dict[str, Any] | None) -> models.Filter | None:
    if not filters:
        return None
    must: list[models.Condition] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, list | tuple | set):
            must.append(
                models.FieldCondition(key=key, match=models.MatchAny(any=[str(v) for v in value]))
            )
        else:
            must.append(models.FieldCondition(key=key, match=models.MatchValue(value=str(value))))
    return models.Filter(must=must) if must else None


class QdrantVectorStore:
    def __init__(self, client: AsyncQdrantClient, collection: str, dim: int) -> None:
        self.client = client
        self.collection = collection
        self.dim = dim
        self._ready = False

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
            )
            for name in FILTER_FIELDS:
                await self.client.create_payload_index(
                    self.collection, name, field_schema=models.PayloadSchemaType.KEYWORD
                )
        self._ready = True

    async def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        await self.ensure_collection()
        await self.client.upsert(
            self.collection,
            points=[
                models.PointStruct(id=str(p.id), vector=p.vector, payload=p.payload) for p in points
            ],
            wait=True,
        )

    async def search(self, vector: list[float], filters: dict[str, Any], k: int = 8) -> list[Hit]:
        await self.ensure_collection()
        res = await self.client.query_points(
            self.collection, query=vector, query_filter=_filter(filters), limit=k, with_payload=True
        )
        return [Hit(uuid.UUID(str(p.id)), p.score, p.payload or {}) for p in res.points]

    async def delete_document(self, document_id: uuid.UUID) -> None:
        if not self._ready and not await self.client.collection_exists(self.collection):
            return  # nothing indexed for this provider yet
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=_filter({"document_id": document_id})),
            wait=True,
        )

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        await self.ensure_collection()
        res = await self.client.count(self.collection, count_filter=_filter(filters), exact=True)
        return res.count


_clients: dict[str, AsyncQdrantClient] = {}


def _client(url: str) -> AsyncQdrantClient:
    if url not in _clients:
        if url == ":memory:":
            _clients[url] = AsyncQdrantClient(location=":memory:")
        else:
            key = get_settings().QDRANT_API_KEY.get_secret_value() or None
            _clients[url] = AsyncQdrantClient(url=url, api_key=key, timeout=30)
    return _clients[url]


def get_store(profile: LLMProfile) -> QdrantVectorStore:
    """The store for a provider profile (each provider's vectors live in their own collection)."""
    s = get_settings()
    return QdrantVectorStore(
        _client(s.QDRANT_URL), s.collection_for(profile), profile.embedding_dim
    )


def reset_clients() -> None:
    """Tests: drop cached clients (an in-memory Qdrant starts empty again)."""
    _clients.clear()


async def delete_document_everywhere(document_id: uuid.UUID) -> None:
    """A deleted file disappears from every provider's collection, not only the current one."""
    s = get_settings()
    for provider in ("cloud", "local", "mock"):
        await get_store(s.profile_for(provider)).delete_document(document_id)
