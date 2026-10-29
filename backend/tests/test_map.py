"""World map, island view and presence."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core import economy
from app.jobs.worker import Worker
from app.models import Presence
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import OWL, SEA, api, make_world, pptx  # noqa: F401  (fixtures)


async def join(api, world, headers):  # noqa: F811
    r = await api.post("/api/worlds/join", json={"code": world["join_code"]}, headers=headers)
    assert r.status_code == 200


async def test_map_before_and_after_upload(api, sm, pptx):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL)
    m = (await api.get(f"/api/worlds/{world['id']}/map", headers=OWL)).json()
    assert m["creator"] == "SeaTurtle42" and not m["is_creator"]
    assert [(x["nickname"], x["is_me"]) for x in m["members"]] == [
        ("SeaTurtle42", False),
        ("NightOwl7", True),
    ]
    (course,) = m["courses"]
    assert course["name"] == "Data Structures" and course["chapters"] == 2
    assert not course["ready"] and course["level"] is None and course["mastery"] == 0

    chapter = world["course"]["chapters"][0]["id"]
    await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    await Worker(sm).drain(timeout_s=60)
    m = (await api.get(f"/api/worlds/{world['id']}/map", headers=OWL)).json()
    assert m["courses"][0]["ready"]


async def test_map_is_members_only(api):  # noqa: F811
    world = await make_world(api)
    r = await api.get(f"/api/worlds/{world['id']}/map", headers=OWL)
    assert r.status_code == 404
    r = await api.get(f"/api/courses/{world['course']['id']}", headers=OWL)
    assert r.status_code == 404


async def test_island_costs_come_from_the_economy(api):  # noqa: F811
    world = await make_world(api)
    isl = (await api.get(f"/api/courses/{world['course']['id']}", headers=SEA)).json()
    costs = {b["key"]: b for b in isl["buildings"]}
    assert costs["quiz_hall"]["cost"] == economy.COST["quiz"]
    assert costs["socratic_tutor"]["cost"] == economy.COST["tutor_session"]
    assert costs["study_studio"]["free_if_cached"] is True
    assert costs["teachback_arena"]["answer_cost"] == 0
    assert isl["level"] is None and [c["title"] for c in isl["chapters"]] == ["Stacks", "Queues"]
    assert all(c["mastery"] is None and not c["weak"] for c in isl["chapters"])


async def test_presence_shows_classmates_for_two_minutes(api, sm):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL)
    course = world["course"]["id"]
    chapter = world["course"]["chapters"][1]["id"]
    r = await api.post(f"/api/courses/{course}/presence", json={"chapter_id": chapter}, headers=OWL)
    assert r.status_code == 204
    await api.post(f"/api/courses/{course}/presence", json={}, headers=SEA)
    seen = (await api.get(f"/api/courses/{course}", headers=SEA)).json()["visitors"]
    assert seen == [{"nickname": "NightOwl7", "avatar": None, "chapter": "Queues"}]  # not me
    async with sm() as s:
        await s.execute(update(Presence).values(seen_at=datetime.now(UTC) - timedelta(minutes=3)))
        await s.commit()
    assert (await api.get(f"/api/courses/{course}", headers=SEA)).json()["visitors"] == []


async def test_presence_ignores_a_chapter_of_another_course(api):  # noqa: F811
    world = await make_world(api)
    other = (
        await api.post(
            f"/api/worlds/{world['id']}/courses",
            json={"name": "Calculus I", "chapters": ["Limits"]},
            headers=SEA,
        )
    ).json()
    r = await api.post(
        f"/api/courses/{world['course']['id']}/presence",
        json={"chapter_id": other["chapters"][0]["id"]},
        headers=SEA,
    )
    assert r.status_code == 204
