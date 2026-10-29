"""QdrantVectorStore against an in-memory Qdrant (no network)."""

import math
import uuid

import pytest
from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.rag import store
from app.rag.store import QdrantVectorStore, VectorPoint, get_store

DIM = 8


def vec(*hot: int) -> list[float]:
    v = [0.0] * DIM
    for i in hot:
        v[i] = 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


@pytest.fixture
def vs() -> QdrantVectorStore:
    return QdrantVectorStore(AsyncQdrantClient(location=":memory:"), "test-chunks", DIM)


def point(world, chapter, doc, *hot, level="intermediate") -> VectorPoint:
    return VectorPoint(
        uuid.uuid4(),
        vec(*hot),
        {
            "world_id": str(world),
            "course_id": "c1",
            "chapter_id": str(chapter),
            "document_id": str(doc),
            "level_tags": [level],
        },
    )


async def test_collection_created_with_dim_and_cosine(vs):
    await vs.ensure_collection()
    info = await vs.client.get_collection("test-chunks")
    assert info.config.params.vectors.size == DIM
    assert info.config.params.vectors.distance.value == "Cosine"


async def test_search_filters_by_world_and_chapter(vs):
    w1, w2, ch1, ch2, doc = (uuid.uuid4() for _ in range(5))
    a = point(w1, ch1, doc, 0)
    b = point(w1, ch2, doc, 0, 1)
    c = point(w2, ch1, doc, 0)  # another class's world: never returned
    await vs.upsert([a, b, c])
    hits = await vs.search(vec(0), {"world_id": w1}, k=5)
    assert [h.id for h in hits] == [a.id, b.id]
    hits = await vs.search(vec(0), {"world_id": w1, "chapter_id": ch2}, k=5)
    assert [h.id for h in hits] == [b.id]
    assert hits[0].payload["chapter_id"] == str(ch2)


async def test_filter_any_of_levels(vs):
    w, ch, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await vs.upsert(
        [point(w, ch, doc, 0, level="beginner"), point(w, ch, doc, 0, level="advanced")]
    )
    assert len(await vs.search(vec(0), {"level_tags": ["beginner", "intermediate"]})) == 1


async def test_upsert_is_idempotent(vs):
    w, ch, doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    p = point(w, ch, doc, 2)
    await vs.upsert([p])
    await vs.upsert([p])
    assert await vs.count({"world_id": w}) == 1


async def test_delete_document(vs):
    w, ch, d1, d2 = (uuid.uuid4() for _ in range(4))
    await vs.upsert([point(w, ch, d1, 0), point(w, ch, d1, 1), point(w, ch, d2, 2)])
    await vs.delete_document(d1)
    assert await vs.count({"world_id": w}) == 1


async def test_get_store_uses_provider_collection(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    store.reset_clients()
    s = get_settings()
    vs = get_store(s.llm)
    assert vs.collection == "hack-04-chunks-mock-mock-embed"
    assert vs.dim == s.llm.embedding_dim
    local = get_store(s.profile_for("local"))
    assert local.collection == "hack-04-chunks-local-bge-m3" and local.dim == 1024
    store.reset_clients()
