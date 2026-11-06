"""F-ACL-1 (audit 2026-11-02): any member of a world could add or delete its courses, chapters and
documents (a classmate wiped the demo "Calculus I"). Course material is managed by the world's
creator only; members read, outsiders get 404 as before."""

import io

import pytest

from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user  # noqa: F401

CREATOR = as_user("AuditCreator")
MEMBER = as_user("AuditMember")
OUTSIDER = as_user("AuditOutsider")


@pytest.fixture
async def world(api):  # noqa: F811
    r = await api.post("/api/worlds", json={"name": "ACL world"}, headers=CREATOR)
    w = r.json()
    r = await api.post(
        f"/api/worlds/{w['id']}/courses",
        json={"name": "Calculus I", "chapters": ["Limits"]},
        headers=CREATOR,
    )
    course = r.json()
    files = {"file": ("notes.txt", io.BytesIO(b"Limits: factor, cancel, substitute. " * 40))}
    r = await api.post(
        f"/api/chapters/{course['chapters'][0]['id']}/documents", files=files, headers=CREATOR
    )
    assert r.status_code == 202
    r = await api.post("/api/worlds/join", json={"code": w["join_code"]}, headers=MEMBER)
    assert r.status_code == 200
    return {
        "id": w["id"],
        "course": course["id"],
        "chapter": course["chapters"][0]["id"],
        "document": r.json()["courses"][0]["chapters"][0]["documents"][0]["id"],
    }


def writes(w):
    """Every endpoint that changes a world's course material."""
    return [
        ("POST", f"/api/worlds/{w['id']}/courses", {"json": {"name": "Intruder course"}}),
        ("POST", f"/api/courses/{w['course']}/chapters", {"json": {"title": "Intruder chapter"}}),
        (
            "POST",
            f"/api/chapters/{w['chapter']}/documents",
            {"files": {"file": ("x.txt", io.BytesIO(b"intruder text " * 50))}},
        ),
        ("DELETE", f"/api/documents/{w['document']}", {}),
        ("DELETE", f"/api/courses/{w['course']}", {}),
    ]


async def test_a_member_cannot_change_course_material(api, world):  # noqa: F811
    for method, url, kw in writes(world):
        r = await api.request(method, url, headers=MEMBER, **kw)
        assert r.status_code == 403, (method, url, r.status_code, r.text)
        assert r.json()["detail"] == "errors.forbidden"
    # nothing changed: the course, its chapter and its document are all still there
    r = await api.get(f"/api/worlds/{world['id']}", headers=MEMBER)
    courses = r.json()["courses"]
    assert [c["name"] for c in courses] == ["Calculus I"]
    assert [ch["title"] for ch in courses[0]["chapters"]] == ["Limits"]
    assert len(courses[0]["chapters"][0]["documents"]) == 1


async def test_an_outsider_still_gets_404(api, world):  # noqa: F811
    for method, url, kw in writes(world):
        r = await api.request(method, url, headers=OUTSIDER, **kw)
        assert r.status_code == 404, (method, url, r.status_code)


async def test_the_creator_can_still_manage_course_material(api, world):  # noqa: F811
    statuses = []
    for method, url, kw in writes(world):
        r = await api.request(method, url, headers=CREATOR, **kw)
        statuses.append(r.status_code)
    assert statuses == [201, 201, 202, 204, 204]


async def test_members_can_still_read_everything(api, world):  # noqa: F811
    for url in (
        f"/api/worlds/{world['id']}",
        f"/api/worlds/{world['id']}/map",
        f"/api/worlds/{world['id']}/indexing",
        f"/api/courses/{world['course']}",
    ):
        r = await api.get(url, headers=MEMBER)
        assert r.status_code == 200, (url, r.status_code)
