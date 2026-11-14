"""Group E: background prefetch, one chapter ahead. A student who finishes a quiz or opens the
Study Studio on chapter N gets chapter N+1's quiz set and study pack made in the background lane,
at P_NEXT_CHAPTER, free and ownerless (user_id None, cost 0, no wallet or pool row). Opening it
later is free; a student who needs it while it is still queued promotes it (Get it now)."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core import economy
from app.core.config import get_settings
from app.jobs import prefetch
from app.jobs.service import P_NEEDED_NOW, P_NEXT_CHAPTER
from app.jobs.worker import Worker
from app.models import Chapter, CoinLedger, Job, User
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, as_user, make_world, pptx  # noqa: F401  (fixtures)

KID = as_user("NextStep9", "fr")


@pytest.fixture(autouse=True)
def roomy_mock(mock_llm):
    """These tests index two chapters and make several sets and packs: lift the mock's 20 rpm
    bucket, or a background quiz check may be deferred 120 s (correct, but not what we test)."""
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"rpm": 6000, "burst": 1000})


async def two_chapters(api, sm, pptx):  # noqa: F811
    world = await make_world(api)
    await join(api, world, KID)
    ch1, ch2 = (c["id"] for c in world["course"]["chapters"])
    for ch in (ch1, ch2):
        r = await api.post(
            f"/api/chapters/{ch}/documents",
            files={"file": (pptx.name, pptx.read_bytes())},
            headers=SEA,
        )
        assert r.status_code == 202, r.text
    await Worker(sm).drain(timeout_s=60)  # indexing + the precomputed intermediate sets
    return world, ch1, ch2


async def settle(sm, timeout_s: float = 90) -> None:
    """Drain until the prefetch jobs are finished, including deferrals of a few seconds from the
    mock's quota signal."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        await Worker(sm).drain(timeout_s=timeout_s)
        async with sm() as s:
            left = await s.scalar(
                select(Job.id).where(
                    Job.status.in_(("queued", "running")), Job.payload["prefetch"].astext == "true"
                )
            )
        if left is None:
            return
        await asyncio.sleep(0.5)
    async with sm() as s:
        stuck = [
            (j.kind, j.status, j.lane, j.error, j.not_before, j.attempts, (j.events or [])[-4:])
            for j in await s.scalars(
                select(Job).where(
                    Job.status.in_(("queued", "running")), Job.payload["prefetch"].astext == "true"
                )
            )
        ]
    raise TimeoutError(f"jobs did not settle: {stuck}")


async def prefetch_jobs(sm, chapter: str) -> list[Job]:
    async with sm() as s:
        return list(
            await s.scalars(
                select(Job).where(
                    Job.payload["chapter_id"].astext == chapter,
                    Job.payload["prefetch"].astext == "true",
                )
            )
        )


async def plan(sm, chapter: str, level: str = "advanced") -> list:
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "NextStep9"))
        ch = await s.get(Chapter, uuid.UUID(chapter))
        return await prefetch.plan_next(s, user, ch, level)


async def test_planner_queues_the_next_chapter_free_and_ownerless(api, sm, pptx):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    async with sm() as s:
        coin_rows = await s.scalar(select(func.count()).select_from(CoinLedger))
    queued = await plan(sm, ch1)
    jobs = await prefetch_jobs(sm, ch2)
    assert sorted(j.kind for j in jobs) == ["QUIZ_POOL", "STUDY_PACK"]
    assert len(queued) == 2
    for j in jobs:
        assert (j.lane, j.priority, j.user_id, j.cost) == ("background", P_NEXT_CHAPTER, None, 0)
        assert j.payload["level"] == "advanced" and j.payload["language"] == "fr"
    assert await plan(sm, ch1) == []  # idempotent: already queued
    await settle(sm)
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(CoinLedger)) == coin_rows
    # opening what was prefetched is free
    for path in (f"/api/studio/{ch2}/price", "/api/quiz/price"):
        params = {"level": "advanced", "chapter_id": ch2}
        price = (await api.get(path, params=params, headers=KID)).json()
        assert price["cost"] == economy.COST["cached_content"] and price["cached"], (path, price)
    assert await plan(sm, ch1) == []  # idempotent: already made


async def test_last_chapter_unready_next_or_switched_off_plans_nothing(api, sm, pptx, monkeypatch):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    assert await plan(sm, ch2) == []  # no chapter after the last one
    monkeypatch.setattr(get_settings(), "PREFETCH_ENABLED", False)
    assert await plan(sm, ch1) == []
    assert await prefetch_jobs(sm, ch2) == []


async def test_finishing_a_quiz_and_opening_the_studio_trigger_it(api, sm, pptx):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    start = await api.post(
        "/api/quiz/start", json={"chapter_id": ch1, "level": "intermediate"}, headers=KID
    )
    attempt = start.json()["attempt_id"]  # the precomputed set: no job
    await api.post(f"/api/quiz/attempts/{attempt}/finish", headers=KID)
    kinds = {j.kind for j in await prefetch_jobs(sm, ch2)}
    assert kinds == {"STUDY_PACK"}  # chapter 2's intermediate set was precomputed at upload
    await api.get(f"/api/studio/{ch1}", params={"level": "advanced"}, headers=KID)
    assert len(await prefetch_jobs(sm, ch2)) == 3  # + the advanced quiz set and pack


async def test_get_it_now_promotes_the_queued_prefetch_and_stays_free(api, sm, pptx):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    await plan(sm, ch1)
    quiz_job = next(j for j in await prefetch_jobs(sm, ch2) if j.kind == "QUIZ_POOL")
    price = (
        await api.get(
            "/api/quiz/price", params={"chapter_id": ch2, "level": "advanced"}, headers=KID
        )
    ).json()
    assert price["cost"] == 0 and not price["cached"]
    assert price["preparing"]["job_id"] == str(quiz_job.id) and price["preparing"]["eta_s"] >= 1
    started = await api.post(
        "/api/quiz/start", json={"chapter_id": ch2, "level": "advanced"}, headers=KID
    )
    assert (started.json()["job_id"], started.json()["cost"]) == (str(quiz_job.id), 0)
    pack = await api.post(f"/api/studio/{ch2}/generate", json={"level": "advanced"}, headers=KID)
    assert pack.json()["cost"] == 0
    async with sm() as s:
        for j in await prefetch_jobs(sm, ch2):
            j = await s.get(Job, j.id)
            assert (j.lane, j.priority, j.cost, j.user_id) == ("interactive", P_NEEDED_NOW, 0, None)


async def test_a_prefetched_pack_waits_for_mid_instead_of_quick_mode(api, sm, pptx, mock_llm):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    await plan(sm, ch1)
    await Worker(sm).drain(timeout_s=30)
    pack = next(j for j in await prefetch_jobs(sm, ch2) if j.kind == "STUDY_PACK")
    assert pack.status == "queued" and not pack.quick_mode  # deferred: background never falls back
    assert (pack.error or "").startswith("deferred:")
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 0.0})


async def test_stats_count_prefetch_jobs_calls_promotions_and_use(api, sm, pptx, monkeypatch):  # noqa: F811
    from tests.admin_helpers import READ, enable_admin  # noqa: PLC0415

    enable_admin(monkeypatch)
    _, ch1, ch2 = await two_chapters(api, sm, pptx)
    await plan(sm, ch1)
    await api.post(f"/api/studio/{ch2}/generate", json={"level": "advanced"}, headers=KID)
    await settle(sm)
    start = await api.post(
        "/api/quiz/start", json={"chapter_id": ch2, "level": "advanced"}, headers=KID
    )
    assert start.json()["attempt_id"]  # the prefetched set, opened at once and free
    got = (await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)).json()
    pf = got["prefetch"]
    assert (pf["jobs"], pf["done"], pf["waiting"], pf["promoted"]) == (2, 2, 0, 1)
    # mid: the quiz check + the notes; compact: the questions, the cards, the map
    assert pf["calls"]["mid"] >= 2 and pf["calls"]["compact"] >= 3
    assert pf["quiz_sets_used"] == 1
