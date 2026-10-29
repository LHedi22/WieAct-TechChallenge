"""Indexing end to end: upload → INDEX_DOCUMENT job → parse → CHUNK_TAG (mock) → embeddings
(mock) → in-memory Qdrant → search. Includes the M2 Done-when: a 30-page PDF + a PPTX are
indexed and search("limit 0/0") returns the Limits pages."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

import app.gateway as gateway_module
from app.core.config import Settings, get_settings
from app.features.worlds import service as worlds
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.service import Gateway
from app.jobs.worker import Worker
from app.models import AICallLog, Chunk, Document, Job, QuizSet, User
from app.rag import store
from app.rag.search import search
from app.seed import samples
from tests.conftest import mock_transport


@pytest.fixture
def rag_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    store.reset_clients()
    yield
    store.reset_clients()


@pytest.fixture
def gw(sm, mock_llm, monkeypatch, rag_env):
    g = Gateway(
        Settings(),
        sm,
        limiter=Limiter(6000, 2, burst=50, embed_rpm=6000),
        client_factory=lambda p: LLMClient(
            p, timeout_s=5, disable_thinking=True, http_client=mock_transport(mock_llm)
        ),
    )
    monkeypatch.setattr(gateway_module, "run", g.run)
    monkeypatch.setattr(gateway_module, "embed", g.embed)
    return g


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, Path]:
    return samples.make_all(tmp_path_factory.mktemp("samples"))


async def stream(path: Path):
    data = await asyncio.to_thread(path.read_bytes)
    for i in range(0, len(data), 64 * 1024):
        yield data[i : i + 64 * 1024]


async def world_with_courses(sm):
    async with sm() as s:
        user = User(nickname="SeaTurtle42", password_hash="-", ui_language="fr")
        s.add(user)
        await s.commit()
        world = await worlds.create_world(s, user, "Engineering 2B")
        calc = await worlds.add_course(s, world, "Calculus I", ["Limits and derivatives"])
        ds = await worlds.add_course(s, world, "Data Structures", ["Stacks and queues"])
        tree = await worlds.world_tree(s, world)
        chapters = {c["course"].name: c["chapters"][0]["chapter"] for c in tree["courses"]}
        assert calc.color_key == "island-1" and ds.color_key == "island-2"
        return user, world, chapters


async def upload(sm, user, chapter, path: Path):
    async with sm() as s:
        return await worlds.store_upload(s, user, chapter, path.name, stream(path))


async def calls(sm, kind: str) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).where(AICallLog.task_kind == kind, AICallLog.status_code == 200)
        )


async def test_done_when_pdf_and_pptx_indexed_and_search_finds_limits(sm, gw, files):
    user, world, chapters = await world_with_courses(sm)
    pdf, job_pdf, reused = await upload(sm, user, chapters["Calculus I"], files["pdf"])
    pptx, _, _ = await upload(sm, user, chapters["Data Structures"], files["pptx"])
    assert job_pdf is not None and not reused and pdf.kind == "pdf"

    await Worker(sm).drain(timeout_s=120)

    async with sm() as s:
        docs = {d.id: d for d in await s.scalars(select(Document))}
        assert docs[pdf.id].status == "ready" and docs[pdf.id].progress == 100
        assert docs[pdf.id].page_count == 30 and docs[pptx.id].status == "ready"
        n_chunks = await s.scalar(select(func.count()).where(Chunk.document_id == pdf.id))
        tagged = await s.scalar(
            select(func.count()).where(Chunk.document_id == pdf.id, Chunk.tags != ["-"])
        )
    assert tagged == n_chunks  # every chunk got concepts from CHUNK_TAG

    # Request economy: one tag call per 8 chunks, one embeddings call per 32
    assert await calls(sm, "CHUNK_TAG") == -(-n_chunks // 8) + -(-12 // 8)
    assert await calls(sm, "EMBED") == -(-n_chunks // 32) + 1

    hits = await search(world.id, "limit 0/0")
    assert hits, "search returned nothing"
    top = hits[:3]
    assert all(h.chapter_id == chapters["Calculus I"].id for h in top)
    assert all(int(h.page_ref.split(":")[1]) <= 15 for h in top)  # the Limits half of the PDF
    assert any("0/0" in h.text for h in top)

    stacks = await search(world.id, "push pop LIFO stack")
    assert stacks[0].chapter_id == chapters["Data Structures"].id
    assert stacks[0].page_ref.startswith("slide:")


async def test_search_never_crosses_worlds(sm, gw, files):
    user, world, chapters = await world_with_courses(sm)
    await upload(sm, user, chapters["Calculus I"], files["pdf"])
    await Worker(sm).drain(timeout_s=120)
    async with sm() as s:
        other = await worlds.create_world(s, user, "Another class")
    assert await search(other.id, "limit 0/0") == []


async def test_same_file_twice_in_a_chapter_is_indexed_once(sm, gw, files):
    user, _, chapters = await world_with_courses(sm)
    first, _, _ = await upload(sm, user, chapters["Data Structures"], files["pptx"])
    again, job, reused = await upload(sm, user, chapters["Data Structures"], files["pptx"])
    assert reused and job is None and again.id == first.id


async def test_same_file_in_another_world_reuses_the_tags(sm, gw, files):
    user, _, chapters = await world_with_courses(sm)
    await upload(sm, user, chapters["Data Structures"], files["pptx"])
    await Worker(sm).drain(timeout_s=60)
    tag_calls = await calls(sm, "CHUNK_TAG")
    _, _, other = await world_with_courses_named(sm, user, "Engineering 2C")
    await upload(sm, user, other["Data Structures"], files["pptx"])
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "CHUNK_TAG") == tag_calls  # cache hits, no repeated identical calls


async def world_with_courses_named(sm, user, name):
    async with sm() as s:
        world = await worlds.create_world(s, user, name)
        await worlds.add_course(s, world, "Data Structures", ["Stacks and queues"])
        tree = await worlds.world_tree(s, world)
        return user, world, {c["course"].name: c["chapters"][0]["chapter"] for c in tree["courses"]}


async def test_quota_defers_then_resumes_without_reparsing(sm, gw, files, mock_llm):
    user, _, chapters = await world_with_courses(sm)
    doc, job_id, _ = await upload(sm, user, chapters["Data Structures"], files["pptx"])
    mock_llm.state.embed_bucket.tokens = 0
    mock_llm.state.embed_bucket.rate = 0
    worker = Worker(sm)
    await worker.drain(timeout_s=30)
    async with sm() as s:
        d = await s.get(Document, doc.id)
        j = await s.get(Job, job_id)
        assert d.status == "embedding" and d.detail == {"key": "waiting"}
        assert j.status == "queued" and j.error == "deferred:quota"
        j.not_before = None
        await s.commit()
    tag_calls = await calls(sm, "CHUNK_TAG")
    mock_llm.state.embed_bucket.rate = 1000
    mock_llm.state.embed_bucket.tokens = 10
    await worker.drain(timeout_s=30)
    async with sm() as s:
        assert (await s.get(Document, doc.id)).status == "ready"
    assert await calls(sm, "CHUNK_TAG") == tag_calls  # chunks and tags survived the deferral


async def test_unreadable_file_fails_with_a_user_key(sm, gw, tmp_path):
    user, _, chapters = await world_with_courses(sm)
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    doc, job_id, _ = await upload(sm, user, chapters["Calculus I"], bad)
    await Worker(sm).drain(timeout_s=30)
    async with sm() as s:
        d = await s.get(Document, doc.id)
        j = await s.get(Job, job_id)
    assert d.status == "failed" and d.error == "errors.document_unreadable"
    assert j.status == "failed" and j.error == "errors.document_unreadable"


async def test_ready_chapter_precomputes_one_quiz_pool(sm, gw, files):
    user, _, chapters = await world_with_courses(sm)
    await upload(sm, user, chapters["Data Structures"], files["pptx"])
    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        pools = list(await s.scalars(select(QuizSet)))
    assert len(pools) == 1
    pool = pools[0]
    assert pool.level == "intermediate" and pool.language == "fr"  # the creator's language
    assert len(pool.questions) == 10
    assert all(len(q["options"]) == 4 and q["hint"] for q in pool.questions)
    assert await calls(sm, "QUIZ_GENERATE") == 1


async def test_rejects_unknown_type_and_oversize(sm, gw, tmp_path, monkeypatch):
    user, _, chapters = await world_with_courses(sm)
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(worlds.Rejected) as e:
        await upload(sm, user, chapters["Calculus I"], exe)
    assert e.value.key == "errors.file_type"
    monkeypatch.setenv("UPLOAD_MAX_MB", "0")
    get_settings.cache_clear()
    txt = tmp_path / "notes.txt"
    txt.write_text("limits " * 100, encoding="utf-8")
    with pytest.raises(worlds.Rejected) as e:
        await upload(sm, user, chapters["Calculus I"], txt)
    assert e.value.key == "errors.file_too_large"
    assert not list((tmp_path / "uploads").rglob("*.txt"))  # partial file removed
