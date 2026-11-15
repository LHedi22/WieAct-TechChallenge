"""Background prefetch (decided 2026-11-14): the planner queues what a world's class will open
next, in the background lane, free and ownerless (user_id None, cost 0, no wallet or pool row):
per (chapter, level, language) the quiz set, the study pack and the audio episode, per (course,
language) the placement quiz. Opening it later is free; a student who needs it while it is still
queued promotes it (Get it now). Three daily mid caps bound it (world, creator, whole app)."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, update

from app.core import config, economy, flags
from app.features.audio import service as audio
from app.features.placement import service as placement
from app.features.quiz import pool as quiz_pool
from app.features.studio import pack as studio_pack
from app.jobs import prefetch
from app.jobs.service import P_NEEDED_NOW, P_NEXT_CHAPTER, create_or_join_shared_job, share_key
from app.jobs.worker import Worker
from app.models import (
    AICallLog,
    Chapter,
    ClassPoolLedger,
    CoinLedger,
    CourseLevel,
    Job,
    RuntimeFlag,
    User,
    World,
)
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import (  # noqa: F401  (fixtures)
    OWL,
    SEA,
    api,
    as_user,
    make_world,
    pptx,
)

KID = as_user("NextStep9", "fr")


def set_env(monkeypatch, **values) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def prefetch_on(monkeypatch):
    set_env(monkeypatch, PREFETCH_ENABLED="true")  # off by default in tests (conftest)


@pytest.fixture(autouse=True)
def roomy_mock(mock_llm):
    """These tests index two chapters and make several sets and packs: lift the mock's 20 rpm
    bucket, or a background quiz check may be deferred 120 s (correct, but not what we test)."""
    from mock_llm.app import Bucket  # noqa: PLC0415

    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"rpm": 6000, "burst": 1000})
    mock_llm.state.bucket = Bucket(6000, 1000)  # the bucket is built once, from the start config


async def two_chapters(api, sm, pptx, monkeypatch, *, at_upload: bool = False, members=(KID,)):  # noqa: F811
    """A world (creator SEA, fr) with two indexed chapters. By default prefetch is off during the
    upload (only the M2 precompute runs: chapter 1 and 2's intermediate quiz set in French), so
    a test sees exactly what its own plan queues."""
    set_env(monkeypatch, PREFETCH_ENABLED=str(at_upload).lower())
    world = await make_world(api)
    for m in members:
        await join(api, world, m)
    ch1, ch2 = (c["id"] for c in world["course"]["chapters"])
    for ch in (ch1, ch2):
        r = await api.post(
            f"/api/chapters/{ch}/documents",
            files={"file": (pptx.name, pptx.read_bytes())},
            headers=SEA,
        )
        assert r.status_code == 202, r.text
    await Worker(sm).drain(timeout_s=60)
    if at_upload:
        await settle(sm)
    set_env(monkeypatch, PREFETCH_ENABLED="true")
    return world, ch1, ch2


async def settle(sm, timeout_s: float = 120) -> None:
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


async def prefetch_jobs(sm, chapter: str | None = None) -> list[Job]:
    async with sm() as s:
        q = select(Job).where(Job.payload["prefetch"].astext == "true")
        if chapter:
            q = q.where(Job.payload["chapter_id"].astext == chapter)
        return list(await s.scalars(q.order_by(Job.created_at)))


def what(jobs, ch1=None, ch2=None) -> set[tuple]:
    names = {ch1: "ch1", ch2: "ch2"}
    return {
        (
            j.kind,
            names.get(j.payload.get("chapter_id"), "course"),
            j.payload.get("level", "-"),
            j.payload["language"],
        )
        for j in jobs
    }


async def plan_world(sm, world, **kw) -> list:
    async with sm() as s:
        return await prefetch.plan(s, uuid.UUID(world["id"]), reason="test", **kw)


async def plan(sm, chapter: str, level: str = "advanced") -> list:
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "NextStep9"))
        ch = await s.get(Chapter, uuid.UUID(chapter))
        return await prefetch.plan_next(s, user, ch, level)


async def test_planner_queues_the_worlds_set_free_and_ownerless(api, sm, pptx, monkeypatch):  # noqa: F811
    world, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch, members=(KID, OWL))
    async with sm() as s:
        coin_rows = await s.scalar(select(func.count()).select_from(CoinLedger))
    queued = await plan_world(sm, world)
    jobs = await prefetch_jobs(sm)
    assert len(queued) == len(jobs) == 12
    per_lang = {
        ("STUDY_PACK", ch, "intermediate", lang) for ch in ("ch1", "ch2") for lang in ("en", "fr")
    } | {
        ("AUDIO_EPISODE", ch, "intermediate", lang)
        for ch in ("ch1", "ch2")
        for lang in ("en", "fr")
    }
    assert what(jobs, ch1, ch2) == per_lang | {
        ("QUIZ_POOL", "ch1", "intermediate", "en"),  # French sets exist (the M2 precompute)
        ("QUIZ_POOL", "ch2", "intermediate", "en"),
        ("PLACEMENT", "course", "-", "en"),
        ("PLACEMENT", "course", "-", "fr"),
    }
    for j in jobs:
        assert (j.lane, j.user_id, j.cost) == ("background", None, 0)
        assert j.priority == prefetch.priority(j.kind)
    assert await plan_world(sm, world) == []  # idempotent: already queued
    await settle(sm)
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(CoinLedger)) == coin_rows
        assert await s.scalar(select(func.count()).select_from(ClassPoolLedger)) == 0
    for who in (KID, OWL):  # opening what was prefetched is free, in each language
        params = {"level": "intermediate", "chapter_id": ch2}
        for path in (f"/api/studio/{ch2}/price", f"/api/audio/{ch2}/price", "/api/quiz/price"):
            price = (await api.get(path, params=params, headers=who)).json()
            assert price["cost"] == economy.COST["cached_content"] and price["cached"], (
                path,
                price,
            )
        start = await api.post(
            "/api/placement/start", json={"course_id": world["course"]["id"]}, headers=who
        )
        assert (start.json()["cached"], start.json()["cost"]) == (True, 0)
    # coins still pay for what nobody prefetched: another level
    other = await api.get(f"/api/studio/{ch2}/price", params={"level": "beginner"}, headers=KID)
    assert other.json()["cost"] == economy.COST["generate_shared_asset"]
    assert await plan_world(sm, world) == []  # idempotent: already made


async def test_levels_are_intermediate_plus_each_placed_members_own(api, sm, pptx, monkeypatch):  # noqa: F811
    world, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch, members=(KID, OWL))
    async with sm() as s:
        kid = await s.scalar(select(User).where(User.nickname == "NextStep9"))
        s.add(
            CourseLevel(
                user_id=kid.id, course_id=uuid.UUID(world["course"]["id"]), level="advanced"
            )
        )
        await s.commit()
    await plan_world(sm, world, placement=False)
    pairs = {(j.payload["level"], j.payload["language"]) for j in await prefetch_jobs(sm)}
    assert pairs == {("intermediate", "en"), ("intermediate", "fr"), ("advanced", "fr")}


async def test_nothing_is_planned_when_off_paused_offline_or_at_the_last_chapter(
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    monkeypatch,
):
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    assert await plan(sm, ch2) == []  # no chapter after the last one
    set_env(monkeypatch, PREFETCH_ENABLED="false")
    assert await plan_world(sm, world) == []
    set_env(monkeypatch, PREFETCH_ENABLED="true", OFFLINE_DEMO_MODE="on")
    assert await plan_world(sm, world) == []
    set_env(monkeypatch, OFFLINE_DEMO_MODE="off")
    async with sm() as s:
        s.add(RuntimeFlag(key="pause_background_lane", value=True))
        await s.commit()
    flags.invalidate()
    assert await plan_world(sm, world) == []
    assert await prefetch_jobs(sm) == []


async def test_the_world_cap_drops_audio_first_then_packs(api, sm, pptx, monkeypatch):  # noqa: F811
    world, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch, members=(KID, OWL))
    set_env(monkeypatch, PREFETCH_MAX_MID_PER_WORLD_PER_DAY=8)
    await plan_world(sm, world)
    kinds = [j.kind for j in await prefetch_jobs(sm)]
    assert sorted(kinds) == ["PLACEMENT"] * 2 + ["QUIZ_POOL"] * 2 + ["STUDY_PACK"] * 4  # no audio
    assert await plan_world(sm, world) == []  # queued jobs count as spent
    set_env(monkeypatch, PREFETCH_MAX_MID_PER_WORLD_PER_DAY=9)
    assert len(await plan_world(sm, world)) == 1  # one more mid: the first audio episode
    async with sm() as s:
        assert (await prefetch.mid_used(s, await s.get(World, uuid.UUID(world["id"]))))[
            "world"
        ] == 9


async def test_a_creators_worlds_share_one_budget_and_the_app_has_one_too(
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    monkeypatch,
):
    world, *_ = await two_chapters(api, sm, pptx, monkeypatch, members=(KID, OWL))
    queued = len(await plan_world(sm, world))
    second = (await api.post("/api/worlds", json={"name": "Second"}, headers=SEA)).json()
    elsewhere = (await api.post("/api/worlds", json={"name": "Owl's"}, headers=OWL)).json()
    async with sm() as s:
        same_creator = await s.get(World, uuid.UUID(second["id"]))
        other_creator = await s.get(World, uuid.UUID(elsewhere["id"]))
        assert await prefetch.mid_used(s, same_creator) == {
            "world": 0,
            "creator": queued,
            "all": queued,
        }
        assert await prefetch.mid_used(s, other_creator) == {
            "world": 0,
            "creator": 0,
            "all": queued,
        }
        set_env(monkeypatch, PREFETCH_MAX_MID_PER_CREATOR_PER_DAY=queued)
        assert await prefetch.mid_left(s, same_creator) == 0
        assert await prefetch.mid_left(s, other_creator) > 0
        set_env(monkeypatch, PREFETCH_MAX_MID_PER_DAY=queued)
        assert await prefetch.mid_left(s, other_creator) == 0
    await settle(sm)  # made calls replace the expected ones
    async with sm() as s:
        made = await s.scalar(
            select(func.count())
            .select_from(AICallLog)
            .join(Job, Job.id == AICallLog.job_id)
            .where(
                Job.payload["prefetch"].astext == "true",
                AICallLog.model_tier == "mid",
                AICallLog.cache_hit.is_(False),
            )
        )
        used = await prefetch.mid_used(s, await s.get(World, uuid.UUID(world["id"])))
    assert made >= queued and used == {"world": made, "creator": made, "all": made}


async def test_upload_plans_chapters_with_prefetch_on_and_the_first_quiz_set_with_it_off(
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    monkeypatch,
):
    world, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch, at_upload=True)
    jobs = await prefetch_jobs(sm)
    assert {j.status for j in jobs} == {"done"}
    assert what(jobs, ch1, ch2) >= {
        ("PLACEMENT", "course", "-", "fr"),
        ("STUDY_PACK", "ch1", "intermediate", "fr"),
        ("AUDIO_EPISODE", "ch2", "intermediate", "fr"),
    }


async def test_with_prefetch_off_upload_still_makes_the_first_quiz_set(api, sm, pptx, monkeypatch):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    assert await prefetch_jobs(sm) == []
    async with sm() as s:
        sets = await s.execute(select(Job.kind, Job.payload["level"].astext, Job.status))
        assert (
            sorted(r for r in sets if r[0] == quiz_pool.KIND)
            == [(quiz_pool.KIND, "intermediate", "done")] * 2
        )


async def test_the_next_chapter_for_one_students_level_and_language(api, sm, pptx, monkeypatch):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    queued = await plan(sm, ch1)
    jobs = await prefetch_jobs(sm, ch2)
    assert len(queued) == 3
    assert what(jobs, ch1, ch2) == {
        (kind, "ch2", "advanced", "fr") for kind in ("QUIZ_POOL", "STUDY_PACK", "AUDIO_EPISODE")
    }
    assert await plan(sm, ch1) == []
    await settle(sm)
    for path in (f"/api/studio/{ch2}/price", f"/api/audio/{ch2}/price", "/api/quiz/price"):
        params = {"level": "advanced", "chapter_id": ch2}
        price = (await api.get(path, params=params, headers=KID)).json()
        assert price["cost"] == economy.COST["cached_content"] and price["cached"], (path, price)
    assert await plan(sm, ch1) == []


async def test_finishing_a_quiz_and_opening_the_studio_trigger_it(api, sm, pptx, monkeypatch):  # noqa: F811
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    start = await api.post(
        "/api/quiz/start", json={"chapter_id": ch1, "level": "intermediate"}, headers=KID
    )
    attempt = start.json()["attempt_id"]  # the precomputed set: no job
    await api.post(f"/api/quiz/attempts/{attempt}/finish", headers=KID)
    kinds = {j.kind for j in await prefetch_jobs(sm, ch2)}
    assert kinds == {"STUDY_PACK", "AUDIO_EPISODE"}  # chapter 2's intermediate set exists
    await api.get(f"/api/studio/{ch1}", params={"level": "advanced"}, headers=KID)
    assert len(await prefetch_jobs(sm, ch2)) == 5  # + the advanced quiz set, pack and episode


async def test_a_prefetched_pack_waits_for_mid_instead_of_quick_mode(
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    mock_llm,
    monkeypatch,
):
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
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
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    await plan(sm, ch1)
    await api.post(f"/api/studio/{ch2}/generate", json={"level": "advanced"}, headers=KID)
    await settle(sm)
    start = await api.post(
        "/api/quiz/start", json={"chapter_id": ch2, "level": "advanced"}, headers=KID
    )
    assert start.json()["attempt_id"]  # the prefetched set, opened at once and free
    got = (await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)).json()
    pf = got["prefetch"]
    assert (pf["jobs"], pf["done"], pf["waiting"], pf["promoted"]) == (3, 3, 0, 1)
    # mid: the quiz check, the notes, the script; compact: the questions, the cards, the map
    assert pf["calls"]["mid"] >= 3 and pf["calls"]["compact"] >= 3
    assert pf["quiz_sets_used"] == 1


# --- Step 2: a student who needs a queued prefetch now promotes it, whatever the building ------


async def queue_background(sm, kind: str, key: str, payload: dict, world_id) -> uuid.UUID:
    async with sm() as s:
        job_id, created = await create_or_join_shared_job(
            s,
            kind=kind,
            share_key=key,
            lane="background",
            payload={**payload, "prefetch": True},
            world_id=uuid.UUID(world_id),
            priority=P_NEXT_CHAPTER,
        )
    assert created
    return job_id


async def test_every_building_promotes_a_queued_prefetch_for_free(api, sm, pptx, monkeypatch):  # noqa: F811
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    course = world["course"]["id"]
    one = {"chapter_id": ch2, "level": "advanced", "language": "fr"}
    jobs = {
        "quiz": await queue_background(
            sm,
            quiz_pool.KIND,
            quiz_pool.share(uuid.UUID(ch2), "advanced", "fr"),
            {**one, "seed": 1},
            world["id"],
        ),
        "studio": await queue_background(
            sm,
            studio_pack.KIND,
            share_key(studio_pack.KIND, uuid.UUID(ch2), "advanced", "fr"),
            {**one, "paid_by": None},
            world["id"],
        ),
        "audio": await queue_background(
            sm,
            audio.KIND,
            share_key(audio.KIND, uuid.UUID(ch2), "advanced", "fr"),
            {**one, "paid_by": None},
            world["id"],
        ),
        "placement": await queue_background(
            sm,
            placement.KIND,
            share_key(placement.KIND, uuid.UUID(course), "fr"),
            {"course_id": course, "language": "fr"},
            world["id"],
        ),
    }
    async with sm() as s:
        coin_rows = await s.scalar(select(func.count()).select_from(CoinLedger))
    level = {"level": "advanced"}
    calls = {
        "quiz": ("/api/quiz/start", {"chapter_id": ch2, **level}),
        "studio": (f"/api/studio/{ch2}/generate", {**level, "pay": "me"}),
        "audio": (f"/api/audio/{ch2}/generate", {**level, "pay": "me"}),
        "placement": ("/api/placement/start", {"course_id": course}),
    }
    for name, (path, body) in calls.items():
        got = (await api.post(path, json=body, headers=KID)).json()
        assert (got["job_id"], got["cost"]) == (str(jobs[name]), 0), (name, got)
    async with sm() as s:
        for name, job_id in jobs.items():
            j = await s.get(Job, job_id)
            assert (j.lane, j.priority, j.user_id, j.cost) == (
                "interactive",
                P_NEEDED_NOW,
                None,
                0,
            ), name
            assert any(e["type"] == "promoted" for e in j.events), name
        assert await s.scalar(select(func.count()).select_from(CoinLedger)) == coin_rows


async def test_a_running_prefetch_keeps_its_lane_and_priority(api, sm, pptx, monkeypatch):  # noqa: F811
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    one = {"chapter_id": ch2, "level": "advanced", "language": "fr", "paid_by": None}
    key = share_key(audio.KIND, uuid.UUID(ch2), "advanced", "fr")
    job_id = await queue_background(sm, audio.KIND, key, one, world["id"])
    async with sm() as s:
        await s.execute(update(Job).where(Job.id == job_id).values(status="running"))
        await s.commit()
    got = await api.post(
        f"/api/audio/{ch2}/generate", json={"level": "advanced", "pay": "me"}, headers=KID
    )
    assert (got.json()["job_id"], got.json()["cost"]) == (str(job_id), 0)
    async with sm() as s:
        j = await s.get(Job, job_id)
        assert (j.lane, j.priority) == ("background", P_NEXT_CHAPTER)  # its calls are under way
