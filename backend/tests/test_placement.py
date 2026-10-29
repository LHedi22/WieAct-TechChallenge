"""Placement quiz: one compact call per course + language for the whole class, answers stay on the
server, grading sets the level and seeds chapter mastery."""

import json

from sqlalchemy import func, select

from app.features.placement.service import level_for, redact
from app.jobs.worker import Worker
from app.models import AICallLog, ChapterMastery, CourseLevel, PlacementSet
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import OWL, SEA, api, make_world, pptx  # noqa: F401  (fixtures)

OWL_FR = OWL | {"X-UI-Language": "fr"}  # same language as SeaTurtle42: same shared set


def test_levels_and_redaction():
    assert level_for(39.9) == "beginner" and level_for(40) == "intermediate"
    assert level_for(75) == "intermediate" and level_for(75.1) == "advanced"
    q = {"question": "Q?", "options": list("abcd"), "answer_index": 2, "difficulty": "advanced"}
    assert redact([q]) == [{"i": 0, "question": "Q?", "options": list("abcd")}]


async def indexed_world(api, sm, pptx):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL)
    chapter = world["course"]["chapters"][0]["id"]
    await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    await Worker(sm).drain(timeout_s=60)
    return world


async def placement_calls(sm) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).where(
                AICallLog.task_kind == "PLACEMENT_QUIZ", AICallLog.status_code == 200
            )
        )


async def test_generated_once_for_the_class_and_answers_never_leak(api, sm, pptx):  # noqa: F811
    world = await indexed_world(api, sm, pptx)
    course = world["course"]["id"]
    start = (await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)).json()
    assert start["job_id"] and not start["cached"] and start["cost"] == 0
    again = (
        await api.post("/api/placement/start", json={"course_id": course}, headers=OWL_FR)
    ).json()
    assert again["job_id"] == start["job_id"]  # a classmate at the same moment shares the job
    await Worker(sm).drain(timeout_s=60)

    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "done" and "answer_index" not in json.dumps(job)
    cached = (
        await api.post("/api/placement/start", json={"course_id": course}, headers=OWL_FR)
    ).json()
    assert cached["cached"] and cached["job_id"] is None and len(cached["questions"]) == 8
    got = (await api.get(f"/api/placement/{course}", headers=SEA)).json()
    assert len(got["questions"]) == 8
    for payload in (cached, got):
        text = json.dumps(payload)
        assert "answer_index" not in text and "difficulty" not in text and "explanation" not in text
    assert await placement_calls(sm) == 1


async def test_grading_sets_level_and_mastery(api, sm, pptx):  # noqa: F811
    world = await indexed_world(api, sm, pptx)
    course = world["course"]["id"]
    await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        qs = (await s.scalar(select(PlacementSet))).questions
    right = [q["answer_index"] for q in qs]
    wrong = [(a + 1) % 4 for a in right]

    best = (
        await api.post(
            "/api/placement/finish", json={"course_id": course, "answers": right}, headers=SEA
        )
    ).json()
    assert best["level"] == "advanced" and best["correct"] == 8 and best["percent"] == 100
    assert best["chapters"][0]["title"] == "Stacks"
    worst = (
        await api.post(
            "/api/placement/finish", json={"course_id": course, "answers": wrong}, headers=OWL_FR
        )
    ).json()
    assert worst["level"] == "beginner" and worst["correct"] == 0

    async with sm() as s:
        levels = {lv.level for lv in await s.scalars(select(CourseLevel))}
        weak = [
            m.weak
            for m in await s.scalars(select(ChapterMastery).where(ChapterMastery.mastery == 0))
        ]
    assert levels == {"advanced", "beginner"} and weak and all(weak)
    island = (await api.get(f"/api/courses/{course}", headers=SEA)).json()
    assert island["level"] == "advanced" and island["chapters"][0]["mastery"] == 100
    m = (await api.get(f"/api/worlds/{world['id']}/map", headers=OWL)).json()
    assert m["courses"][0]["level"] == "beginner"


async def test_placement_errors(api, sm, pptx):  # noqa: F811
    world = await make_world(api)
    course = world["course"]["id"]
    r = await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)
    assert r.status_code == 409 and r.json()["detail"] == "errors.placement_no_material"
    r = await api.get(f"/api/placement/{course}", headers=SEA)
    assert r.status_code == 404 and r.json()["detail"] == "errors.placement_not_ready"
    r = await api.post("/api/placement/start", json={"course_id": course}, headers=OWL)
    assert r.status_code == 404  # not a member

    world = await indexed_world(api, sm, pptx)
    course = world["course"]["id"]
    await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    r = await api.post(
        "/api/placement/finish", json={"course_id": course, "answers": [0, 1]}, headers=SEA
    )
    assert r.status_code == 400 and r.json()["detail"] == "errors.placement_incomplete"


async def test_each_language_gets_its_own_set(api, sm, pptx):  # noqa: F811
    world = await indexed_world(api, sm, pptx)
    course = world["course"]["id"]
    fr = (await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)).json()
    en = (await api.post("/api/placement/start", json={"course_id": course}, headers=OWL)).json()
    assert fr["job_id"] != en["job_id"]
    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        assert {p.language for p in await s.scalars(select(PlacementSet))} == {"fr", "en"}
