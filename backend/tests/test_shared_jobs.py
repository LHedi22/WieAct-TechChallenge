"""Shared class jobs under concurrency (audit OPT-01): classmates who start the same study pack,
audio episode, quiz set or placement set at the same moment get ONE job, ONE payer and ONE set of
model calls, whatever the interleaving (each request has its own session, so this is real
Postgres concurrency). A failed or cancelled job frees its key, and the money invariants hold."""

import asyncio

from sqlalchemy import func, or_, select

from app.admin import invariants
from app.core import economy
from app.jobs.worker import Worker
from app.models import AICallLog, Job
from tests.test_map import join
from tests.test_quiz import calls, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user, pptx  # noqa: F401  (fixtures)

N = 10


async def classmates(api, world, n=N, lang="fr"):  # noqa: F811
    users = [as_user(f"Mate{i:02d}", lang) for i in range(n)]
    for u in users:
        await join(api, world, u)
    return users


async def jobs_of(sm, kind: str) -> list[Job]:
    async with sm() as s:
        return list(await s.scalars(select(Job).where(Job.kind == kind)))


async def no_broken_invariants(sm):
    async with sm() as s:
        broken = invariants.flat(await invariants.run(s))
    assert broken == [], broken


async def test_ten_classmates_one_study_pack(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    users = await classmates(api, world)
    rs = await asyncio.gather(
        *(
            api.post(f"/api/studio/{chapter}/generate", json={"level": "advanced"}, headers=u)
            for u in users
        )
    )
    assert {r.status_code for r in rs} == {200}, [r.text for r in rs]
    out = [r.json() for r in rs]
    assert len({o["job_id"] for o in out}) == 1
    assert sorted(o["cost"] for o in out) == [0] * (N - 1) + [economy.COST["generate_shared_asset"]]
    assert len(await jobs_of(sm, "STUDY_PACK")) == 1
    await Worker(sm).drain(timeout_s=60)
    assert (await calls(sm, "NOTES_WRITE"), await calls(sm, "FLASHCARDS")) == (1, 1)
    assert await calls(sm, "MAP_WRITE") == 1
    await no_broken_invariants(sm)


async def test_ten_classmates_one_audio_episode(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    users = await classmates(api, world)
    rs = await asyncio.gather(
        *(
            api.post(f"/api/audio/{chapter}/generate", json={"level": "advanced"}, headers=u)
            for u in users
        )
    )
    out = [r.json() for r in rs]
    assert len({o["job_id"] for o in out}) == 1, out
    assert sum(o["cost"] for o in out) == economy.COST["generate_shared_asset"]
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "AUDIO_SCRIPT") == 1
    await no_broken_invariants(sm)


async def checked(sm) -> int:
    """QUIZ_VERIFY answers: sent and answered, or read from the cache."""
    async with sm() as s:
        return await s.scalar(
            select(func.count()).where(
                AICallLog.task_kind == "QUIZ_VERIFY",
                or_(AICallLog.status_code == 200, AICallLog.cache_hit.is_(True)),
            )
        )


async def test_ten_classmates_one_new_quiz_set_and_one_verification(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    users = await classmates(api, world)
    verify_before = await checked(sm)
    rs = await asyncio.gather(
        *(
            api.post(
                "/api/quiz/start", json={"chapter_id": chapter, "level": "advanced"}, headers=u
            )
            for u in users
        )
    )
    out = [r.json() for r in rs]
    assert len({o["job_id"] for o in out}) == 1, out
    assert sum(o["cost"] for o in out) == economy.COST["quiz"]  # one payer, the rest join free
    await Worker(sm).drain(timeout_s=60)
    # one check: a call, or the cache when the mock wrote the same questions as the upload's
    # intermediate set (the check is keyed by its request since step 8, audit after/84)
    assert await checked(sm) - verify_before == 1
    for u, o in zip(users, out, strict=True):  # every classmate gets an attempt on that set
        r = await api.post(f"/api/quiz/attempts/from-job/{o['job_id']}", headers=u)
        assert r.status_code == 200, r.text
    await no_broken_invariants(sm)


async def test_ten_classmates_one_placement_set(api, sm, pptx):  # noqa: F811
    world, _ = await indexed(api, sm, pptx)
    users = await classmates(api, world, lang="ar")
    course = world["course"]["id"]
    rs = await asyncio.gather(
        *(api.post("/api/placement/start", json={"course_id": course}, headers=u) for u in users)
    )
    out = [r.json() for r in rs]
    assert len({o["job_id"] for o in out}) == 1, out
    assert len(await jobs_of(sm, "PLACEMENT")) == 1
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "PLACEMENT_QUIZ") == 1


async def test_a_cancelled_job_frees_its_key(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    a, b = await classmates(api, world, n=2)
    first = (
        await api.post(f"/api/audio/{chapter}/generate", json={"level": "advanced"}, headers=a)
    ).json()
    r = await api.post(f"/api/jobs/{first['job_id']}/cancel", headers=a)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    second = (
        await api.post(f"/api/audio/{chapter}/generate", json={"level": "advanced"}, headers=b)
    ).json()
    assert second["job_id"] != first["job_id"]
    assert second["cost"] == economy.COST["generate_shared_asset"]
    async with sm() as s:
        active = await s.scalar(
            select(func.count()).where(Job.kind == "AUDIO_EPISODE", Job.status == "queued")
        )
    assert active == 1
    await no_broken_invariants(sm)


async def test_admin_retry_refuses_while_a_classmate_job_holds_the_key(api, sm, pptx, monkeypatch):  # noqa: F811
    from tests.admin_helpers import ACT, enable_admin  # noqa: PLC0415

    enable_admin(monkeypatch)
    world, chapter = await indexed(api, sm, pptx)
    a, b = await classmates(api, world, n=2)
    body = {"level": "advanced"}
    first = (await api.post(f"/api/audio/{chapter}/generate", json=body, headers=a)).json()
    await api.post(f"/api/jobs/{first['job_id']}/cancel", headers=a)
    await api.post(f"/api/audio/{chapter}/generate", json=body, headers=b)  # holds the key now
    r = await api.post(
        f"/api/admin/jobs/{first['job_id']}/retry", json={"reason": "test"}, headers=ACT
    )
    assert r.status_code == 409, r.text
