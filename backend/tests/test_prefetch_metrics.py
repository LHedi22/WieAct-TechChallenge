# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""Prefetch step 8: was it used? `jobs.opened_at` is set the first time a student is served
what a prefetch made (or joins it while it is still being made), with one indexed UPDATE.
`/api/admin/stats` turns it into a hit rate (opened ÷ done) and a time to content (0 when the
content was ready before the student came), and shows the three daily mid caps."""

import uuid

import mock_llm.app as mock_app
from sqlalchemy import func, select, text

from app.jobs import prefetch
from app.jobs.service import mark_opened
from app.models import AICallLog, Job
from tests.admin_helpers import READ, enable_admin
from tests.test_prefetch import (  # noqa: F401  (fixtures and helpers)
    KID,
    plan_world,
    prefetch_jobs,
    prefetch_on,
    roomy_mock,
    settle,
    two_chapters,
)
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, pptx  # noqa: F401  (fixtures)


def by_kind(jobs) -> dict[str, Job]:
    return {j.kind: j for j in jobs}


async def stats(api, monkeypatch) -> dict:
    enable_admin(monkeypatch)
    r = await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)
    assert r.status_code == 200, r.text
    return r.json()["prefetch"]


async def test_serving_prefetched_content_marks_it_opened_once(api, sm, pptx, monkeypatch):
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    await plan_world(sm, world, chapter_id=uuid.UUID(ch2), level="intermediate", language="fr")
    await settle(sm)
    jobs = by_kind(await prefetch_jobs(sm, ch2))
    assert {"STUDY_PACK", "AUDIO_EPISODE"} <= set(jobs)
    assert all(j.opened_at is None for j in jobs.values())

    params = {"level": "intermediate"}
    assert (await api.get(f"/api/studio/{ch2}", params=params, headers=KID)).json()["notes"]
    first = by_kind(await prefetch_jobs(sm, ch2))
    assert first["STUDY_PACK"].opened_at is not None
    assert first["AUDIO_EPISODE"].opened_at is None  # not opened yet
    assert (await api.get(f"/api/audio/{ch2}", params=params, headers=KID)).json()["script"]
    for _ in range(3):  # later visits keep the first time
        await api.get(f"/api/studio/{ch2}", params=params, headers=KID)
    again = by_kind(await prefetch_jobs(sm, ch2))
    assert again["STUDY_PACK"].opened_at == first["STUDY_PACK"].opened_at
    assert again["AUDIO_EPISODE"].opened_at is not None

    p = await stats(api, monkeypatch)
    assert p["opened"] == 2 and p["done"] == len(jobs)
    assert p["hit_rate"] == round(2 / len(jobs), 3)
    assert p["time_to_content_s"] == {"p50": 0.0, "p95": 0.0, "n": 2}  # ready before they came


async def test_joining_a_queued_prefetch_counts_the_wait(api, sm, pptx, monkeypatch):
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    await plan_world(sm, world, chapter_id=uuid.UUID(ch2), level="intermediate", language="fr")
    r = await api.post(
        f"/api/studio/{ch2}/generate", json={"level": "intermediate", "pay": "me"}, headers=KID
    )
    assert r.json()["cost"] == 0  # Get it now
    pack = by_kind(await prefetch_jobs(sm, ch2))["STUDY_PACK"]
    assert pack.opened_at is not None and pack.lane == "interactive"
    await settle(sm)
    pack = by_kind(await prefetch_jobs(sm, ch2))["STUDY_PACK"]
    assert pack.finished_at > pack.opened_at  # the student waited for it (the mock is quick)
    p = await stats(api, monkeypatch)
    assert p["opened"] == 1 and p["time_to_content_s"]["n"] == 1
    wait = (pack.finished_at - pack.opened_at).total_seconds()
    assert p["time_to_content_s"]["p50"] == round(wait, 1)


async def test_mark_opened_touches_only_unopened_prefetch_jobs(sm):
    async with sm() as s:
        own = Job(kind="STUDY_PACK", lane="interactive", status="done", share_key="k1", payload={})
        pre = Job(kind="STUDY_PACK", lane="background", share_key="k1", payload={"prefetch": True})
        s.add_all([own, pre])
        await s.flush()
        ids = (own.id, pre.id)
        await s.commit()

    async def opened_at():
        async with sm() as s:
            rows = dict((await s.execute(select(Job.id, Job.opened_at))).all())
        return rows[ids[0]], rows[ids[1]]

    async with sm() as s:
        await mark_opened(s, "k1")
    own_at, first = await opened_at()
    async with sm() as s:
        await mark_opened(s, "k1")
    assert own_at is None and first is not None and await opened_at() == (None, first)


async def test_the_opened_update_uses_the_partial_index(sm):
    """The UPDATE's WHERE matches `ix_jobs_prefetch_unopened` (migration 0019). With sequential
    scans off, Postgres picks the index only if the predicate implies the index's."""
    async with sm() as s:
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            await s.scalars(
                text(
                    "EXPLAIN UPDATE jobs SET opened_at = now() WHERE share_key = 'k' "
                    "AND opened_at IS NULL AND (payload ->> 'prefetch') = 'true'"
                )
            )
        )
    assert "ix_jobs_prefetch_unopened" in plan, plan


async def test_stats_show_the_three_mid_caps(api, sm, pptx, monkeypatch):
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    await plan_world(sm, world, chapter_id=uuid.UUID(ch2), level="intermediate", language="fr")
    p = await stats(api, monkeypatch)
    caps = prefetch.caps()
    assert p["mid_today"]["all"] == {"used": 2, "cap": caps["all"]}  # pack + audio, expected
    [w] = p["mid_today"]["worlds"]
    assert (w["world_id"], w["used"], w["cap"]) == (world["id"], 2, caps["world"])
    [c] = p["mid_today"]["creators"]
    assert (c["used"], c["cap"]) == (2, caps["creator"])
    assert set(c) == {"creator_id", "used", "cap"}  # an id, never a nickname
    async with sm() as s:
        assert await s.scalar(select(Job.id).where(Job.opened_at.is_not(None))) is None


async def test_a_derived_request_identical_across_levels_is_sent_once(api, sm, pptx, monkeypatch):
    """Found by the step 8 class runs (after/84): the mock wrote the same notes and questions for
    intermediate and advanced, so the mind map and the quiz check, whose prompts are built from
    those replies and do not name the level, sent byte-identical requests (repeated_identical 2).
    Their cache key is now the request itself: an identical request reads the first answer."""
    first: dict[str, object] = {}
    for kind in ("NOTES_WRITE", "QUIZ_GENERATE"):  # a model that ignores the level
        real = mock_app.GENERATORS[kind]

        def same(*a, _real=real, _kind=kind, **k):
            return first.setdefault(_kind, _real(*a, **k))

        monkeypatch.setitem(mock_app.GENERATORS, kind, same)
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    for level in ("intermediate", "advanced"):
        await plan_world(sm, world, chapter_id=uuid.UUID(ch2), level=level, language="en")
    await settle(sm)
    jobs = await prefetch_jobs(sm, ch2)
    assert {(j.kind, j.status) for j in jobs if j.kind in ("STUDY_PACK", "QUIZ_POOL")} == {
        ("STUDY_PACK", "done"),
        ("QUIZ_POOL", "done"),
    }
    async with sm() as s:
        sent = dict(
            (
                await s.execute(
                    select(AICallLog.task_kind, func.count())
                    .join(Job, Job.id == AICallLog.job_id)
                    .where(
                        AICallLog.status_code == 200,
                        AICallLog.cache_hit.is_(False),
                        Job.payload["prefetch"].astext == "true",  # not the French upload sets
                    )
                    .group_by(AICallLog.task_kind)
                )
            ).all()
        )
    assert sent["NOTES_WRITE"] == 2 and sent["QUIZ_GENERATE"] >= 2  # the level is in these
    assert sent["MAP_WRITE"] == 1 and sent["QUIZ_VERIFY"] == 1
    enable_admin(monkeypatch)
    r = await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)
    assert r.json()["repeated_identical"] == 0
