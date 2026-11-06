"""Cloud / Local picked in the UI (development): PUT /api/system/provider.

- the choice overrides LLM_PROVIDER at runtime, for the API and the worker, with no restart;
- Cloud never falls back to local silently: without the key, outside our slot or blocked, AI pauses;
- embeddings then come from our Ollama (bge-m3), never the mock's word-count vectors;
- class content made by a weaker provider (the mock's placeholder quizzes) is not served and is
  written again by the picked one, which replaces it;
- a REFRESH_CONTENT job re-tags and re-indexes the material with the picked provider.

The "local" provider is pointed at the in-process mock here (no Ollama in tests)."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core import provider_choice
from app.core.config import get_settings
from app.core.provenance import replaces
from app.features.placement import service as placement
from app.gateway.client import LLMClient
from app.gateway.providers import resolve
from app.jobs.worker import Worker
from app.models import AICallLog, Document, Job, PlacementSet, QuizSet
from app.rag import store
from tests.test_provenance import QUESTION, production, world  # noqa: F401  (fixture)
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, pptx  # noqa: F401  (fixtures)


@pytest.fixture
def local_is_mock(monkeypatch):
    """The local profile talks to the in-process mock with the mock's vector size."""
    for k, v in {
        "LOCAL_MODEL_COMPACT": "mock-compact",
        "LOCAL_MODEL_MID": "mock-mid",
        "LOCAL_EMBEDDING_MODEL": "bge-m3",
        "LOCAL_EMBEDDING_DIM": "384",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    prepare = LLMClient.prepare

    def with_mock_markers(self, model, messages, kind, language):
        msgs = prepare(self, model, messages, kind, language)
        if self.profile.provider == "local":  # the mock picks its reply by these markers
            msgs[0]["content"] += f" <!-- task: {kind} --> <!-- lang: {language} -->"
        return msgs

    monkeypatch.setattr(LLMClient, "prepare", with_mock_markers)


async def test_choice_overrides_env_without_restart(sm):
    settings = get_settings()
    assert (await resolve(settings, sm)).profile.provider == "mock"
    provider_choice.set_choice("local")
    assert (await resolve(settings, sm)).profile.provider == "local"
    provider_choice.clear()
    assert (await resolve(settings, sm)).profile.provider == "mock"


async def test_cloud_without_key_pauses_instead_of_falling_back(sm, api):  # noqa: F811
    provider_choice.set_choice("cloud")
    res = await resolve(get_settings(), sm)
    assert res.profile.provider == "cloud" and res.offline
    assert res.reason == "cloud_not_configured"
    status = (await api.get("/api/system/status")).json()
    assert status["provider_choice"] == "cloud" and status["can_choose_provider"]
    assert status["offline_demo_mode"] and status["cloud_configured"] is False


async def test_cloud_with_key_outside_slot_pauses(sm, monkeypatch):
    monkeypatch.setenv("CLOUD_BASE_URL", "http://cloud.invalid/v1")
    monkeypatch.setenv("CLOUD_API_KEY", "test-only-not-a-key")
    monkeypatch.setenv("LLM_SLOT_FORCE", "off")
    get_settings.cache_clear()
    provider_choice.set_choice("cloud")
    res = await resolve(get_settings(), sm)
    assert res.offline and res.reason == "outside_slot"
    monkeypatch.setenv("LLM_SLOT_FORCE", "live")
    get_settings.cache_clear()
    res = await resolve(get_settings(), sm)
    assert not res.offline and res.profile.provider == "cloud"


def test_embeddings_use_our_ollama_once_a_provider_is_picked(monkeypatch):
    assert provider_choice.embed_provider() is None  # mock + "same": follow the chat provider
    provider_choice.set_choice("cloud")  # the platform key has no embeddings model
    assert provider_choice.embed_provider() == "local"
    monkeypatch.setenv("EMBED_PROVIDER", "cloud")
    get_settings.cache_clear()
    assert provider_choice.embed_provider() == "cloud"


def test_production_ignores_the_choice(production):  # noqa: F811
    provider_choice.set_choice("local")
    assert provider_choice.get() is None and provider_choice.target() == "cloud"


async def test_put_provider_refused_in_production(sm, api, production):  # noqa: F811
    r = await api.put("/api/system/provider", json={"provider": "local"}, headers=OWL_FR)
    assert r.status_code in (401, 403)  # no dev sign-in in production, and no choice anyway
    assert provider_choice.get() is None


async def test_weaker_content_is_hidden_then_replaced(sm):
    _, _, course, _ = await world(sm)
    async with sm() as s:
        s.add(
            PlacementSet(
                id=uuid.uuid4(),
                course_id=course.id,
                language="en",
                questions=[QUESTION],
                provider="mock",
            )
        )
        await s.commit()
    assert await placement.find_set(course.id, "en") is not None  # mock active: served
    provider_choice.set_choice("local")
    assert await placement.find_set(course.id, "en") is None  # the mock's set is hidden

    async def upsert(provider: str) -> None:
        async with sm() as s:
            stmt = insert(PlacementSet).values(
                id=uuid.uuid4(),
                course_id=course.id,
                language="en",
                questions=[QUESTION | {"question": provider}],
                provider=provider,
            )
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["course_id", "language"],
                    set_={"questions": stmt.excluded.questions, "provider": stmt.excluded.provider},
                    where=replaces(PlacementSet.provider, stmt.excluded.provider),
                )
            )
            await s.commit()

    await upsert("local")  # local replaces mock
    found = await placement.find_set(course.id, "en")
    assert found is not None and found.provider == "local"
    await upsert("mock")  # mock never overwrites a real model's set
    assert (await placement.find_set(course.id, "en")).provider == "local"
    provider_choice.set_choice("cloud")
    assert await placement.find_set(course.id, "en") is None  # Cloud: platform content only
    await upsert("cloud")
    assert (await placement.find_set(course.id, "en")).provider == "cloud"


async def test_switch_to_local_retags_reindexes_and_regenerates_the_quiz(
    local_is_mock,
    sm,
    api,  # noqa: F811
    pptx,  # noqa: F811
    gw,  # noqa: F811
):
    _, chapter = await indexed(api, sm, pptx)  # indexed + precomputed quiz on the mock
    async with sm() as s:
        doc = await s.scalar(select(Document))
        assert doc.tagged_by == "mock"
        assert {q.provider for q in await s.scalars(select(QuizSet))} == {"mock"}

    r = await api.put("/api/system/provider", json={"provider": "local"}, headers=OWL_FR)
    assert r.status_code == 200 and r.json()["provider_choice"] == "local"
    assert r.json()["refresh_job_id"]
    status = (await api.get("/api/system/status")).json()
    assert status["provider"] == "local" and not status["offline_demo_mode"]

    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        job = await s.get(Job, uuid.UUID(r.json()["refresh_job_id"]))
        assert job.status == "done", job.error
        assert job.result["retagged"] == 1 and job.result["embedded"] == 1
        doc = await s.get(Document, doc.id)
        assert doc.tagged_by == "local"
        n_chunks = await s.scalar(select(func.count()).select_from(Document))  # one document
        local_calls = await s.scalar(
            select(func.count()).where(AICallLog.provider == "local", AICallLog.status_code == 200)
        )
        sets = {q.provider for q in await s.scalars(select(QuizSet))}
    assert n_chunks == 1 and local_calls > 0
    assert sets == {"local"}  # the class pool was written again and replaced the mock's
    vectors = await store.get_store(get_settings().profile_for("local")).count(
        {"document_id": doc.id}
    )
    assert vectors > 0

    # A student now gets the local-made set, never the mock's placeholder one
    r = await api.post(
        "/api/quiz/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
    )
    assert r.status_code == 200 and r.json()["job_id"] is None  # served from the class pool

    # Running the refresh again finds nothing to do
    again = await api.put("/api/system/provider", json={"provider": "local"}, headers=OWL_FR)
    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        job = await s.get(Job, uuid.UUID(again.json()["refresh_job_id"]))
    assert job.result["retagged"] == 0 and job.result["embedded"] == 0
