"""Audit F-OFF-1 (Tier 2 #10): offline (and production) served any cached class content, including
quiz sets, placement sets, study packs and tips that the mock or local Ollama made, because those
tables didn't record who made them (only ai_cache did).

Now each row records its provider. In production only platform-made (`cloud`) rows are served, and a
cloud-made row replaces a non-cloud one under the same unique key; in development everything is
served and the API says who made it (`made_by`) so the UI can label test data."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.features.placement import service as placement
from app.features.quiz import service as quiz
from app.features.studio import pack
from app.features.wisdom import service as wisdom
from app.features.worlds import service as worlds
from app.models import PlacementSet, QuizSet, StudyAsset, User, WisdomTip

QUESTION = {
    "question": "What is a limit?",
    "options": ["a", "b", "c", "d"],
    "answer_index": 0,
    "hint": "h",
    "explanation": "e",
    "concept": "limit",
}


@pytest.fixture
def production(monkeypatch):
    for k, v in {
        "APP_ENV": "production",
        "LLM_PROVIDER": "cloud",
        "CLOUD_BASE_URL": "http://cloud.invalid/v1",
        "CLOUD_API_KEY": "test-only-not-a-key",
        "EMBED_PROVIDER": "local",
        "SECRET_KEY": "a-long-random-test-secret-for-production-mode",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def world(sm):
    async with sm() as s:
        user = User(nickname="ProvOwl1", password_hash="-", ui_language="en")
        s.add(user)
        await s.commit()
        w = await worlds.create_world(s, user, "Provenance world")
        c = await worlds.add_course(s, w, "Calculus I", ["Limits"])
        tree = await worlds.world_tree(s, w)
        chapter = tree["courses"][0]["chapters"][0]["chapter"]
        return user, w, c, chapter


async def add(sm, *rows):
    async with sm() as s:
        s.add_all(rows)
        await s.commit()


async def test_production_never_serves_non_platform_content(sm, production):
    user, w, c, ch = await world(sm)
    await add(
        sm,
        PlacementSet(
            id=uuid.uuid4(),
            course_id=c.id,
            language="en",
            questions=[QUESTION] * 8,
            provider="mock",
        ),
        QuizSet(
            id=uuid.uuid4(),
            world_id=w.id,
            chapter_id=ch.id,
            level="intermediate",
            language="en",
            seed=1,
            questions=[QUESTION] * 10,
            provider="local",
        ),
        StudyAsset(
            id=uuid.uuid4(),
            world_id=w.id,
            chapter_id=ch.id,
            level="intermediate",
            language="en",
            kind="notes",
            content={"title": "t", "sections": []},
            provider=None,
        ),  # made before provenance existed: unknown
        WisdomTip(
            id=uuid.uuid4(),
            world_id=w.id,
            course_id=c.id,
            chapter_id=ch.id,
            concept="limit",
            mistake_type="confusion",
            language="en",
            text={"trap": "t", "why": "w", "right": "r"},
            student_count=3,
            provider="mock",
        ),
    )
    async with sm() as s:
        assert await placement.find_set(c.id, "en") is None
        assert await quiz.unseen_set(s, user, ch.id, "intermediate", "en") is None
        assert await pack.assets(s, ch.id, "intermediate", "en") == {}
        assert await wisdom.tips_for(s, w.id, "en") == []


async def test_production_serves_platform_content(sm, production):
    user, w, c, ch = await world(sm)
    await add(
        sm,
        PlacementSet(
            id=uuid.uuid4(),
            course_id=c.id,
            language="en",
            questions=[QUESTION] * 8,
            provider="cloud",
        ),
        QuizSet(
            id=uuid.uuid4(),
            world_id=w.id,
            chapter_id=ch.id,
            level="intermediate",
            language="en",
            seed=1,
            questions=[QUESTION] * 10,
            provider="cloud",
        ),
    )
    async with sm() as s:
        assert await placement.find_set(c.id, "en") is not None
        assert await quiz.unseen_set(s, user, ch.id, "intermediate", "en") is not None


async def test_a_platform_asset_replaces_a_test_one_under_the_same_key(sm, production):
    _, w, c, ch = await world(sm)
    await pack.save_asset(
        w.id, ch.id, "advanced", "en", "notes", {"title": "mock"}, provider="mock"
    )
    await pack.save_asset(
        w.id, ch.id, "advanced", "en", "notes", {"title": "real"}, provider="cloud"
    )
    async with sm() as s:
        rows = list(await s.scalars(select(StudyAsset).where(StudyAsset.level == "advanced")))
    assert len(rows) == 1 and rows[0].provider == "cloud" and rows[0].content["title"] == "real"
    # ...but a test asset never overwrites a platform one
    await pack.save_asset(
        w.id, ch.id, "advanced", "en", "notes", {"title": "mock2"}, provider="mock"
    )
    async with sm() as s:
        row = await s.scalar(select(StudyAsset).where(StudyAsset.level == "advanced"))
    assert row.provider == "cloud" and row.content["title"] == "real"


async def test_development_serves_everything(sm):
    user, w, c, ch = await world(sm)
    await add(
        sm,
        QuizSet(
            id=uuid.uuid4(),
            world_id=w.id,
            chapter_id=ch.id,
            level="intermediate",
            language="en",
            seed=1,
            questions=[QUESTION] * 10,
            provider="mock",
        ),
    )
    async with sm() as s:
        got = await quiz.unseen_set(s, user, ch.id, "intermediate", "en")
    assert got is not None and got.provider == "mock"
