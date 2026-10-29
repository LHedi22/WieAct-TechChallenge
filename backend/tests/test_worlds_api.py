"""Worlds API: create / join by code, membership (404 for outsiders), courses, uploads,
the indexing rollup, deletes, and the dev search job."""

import re
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.core.config import get_settings
from app.core.db import get_session, get_sessionmaker
from app.jobs.worker import Worker
from app.main import create_app
from app.rag import store
from app.seed import samples
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)


@pytest.fixture
def api(sm, gw):  # noqa: F811
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def as_user(nickname: str, lang: str = "en") -> dict[str, str]:
    return {"X-Dev-User": nickname, "X-UI-Language": lang}


SEA = as_user("SeaTurtle42", "fr")
OWL = as_user("NightOwl7")


@pytest.fixture(scope="module")
def pptx(tmp_path_factory):
    return samples.make_pptx(tmp_path_factory.mktemp("s") / "Stacks.pptx")


async def make_world(api) -> dict:
    r = await api.post("/api/worlds", json={"name": "Engineering 2B"}, headers=SEA)
    assert r.status_code == 201
    world = r.json()
    r = await api.post(
        f"/api/worlds/{world['id']}/courses",
        json={"name": "Data Structures", "chapters": ["Stacks", "Queues"]},
        headers=SEA,
    )
    assert r.status_code == 201
    world["course"] = r.json()
    return world


async def test_create_world_gives_a_readable_join_code(api):
    world = await make_world(api)
    assert re.fullmatch(r"[A-Z]{5}-[2-9A-HJKMNP-Z]{3}", world["join_code"])
    assert world["is_creator"] and world["members"] == 1
    course = world["course"]
    assert course["color_key"] == "island-1"
    assert [(c["idx"], c["title"]) for c in course["chapters"]] == [(1, "Stacks"), (2, "Queues")]
    mine = (await api.get("/api/worlds", headers=SEA)).json()
    assert [w["id"] for w in mine] == [world["id"]]


async def test_join_by_code_is_forgiving_and_idempotent(api):
    world = await make_world(api)
    messy = world["join_code"].lower().replace("-", " ")
    r = await api.post("/api/worlds/join", json={"code": messy}, headers=OWL)
    assert r.status_code == 200 and r.json()["id"] == world["id"]
    assert not r.json()["is_creator"] and r.json()["members"] == 2
    again = await api.post("/api/worlds/join", json={"code": world["join_code"]}, headers=OWL)
    assert again.json()["members"] == 2


async def test_unknown_code(api):
    r = await api.post("/api/worlds/join", json={"code": "OLIVE-222"}, headers=OWL)
    assert r.status_code == 404 and r.json()["detail"] == "errors.join_code_unknown"


async def test_outsiders_get_404_everywhere(api, pptx):
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    for r in (
        await api.get(f"/api/worlds/{world['id']}", headers=OWL),
        await api.get(f"/api/worlds/{world['id']}/indexing", headers=OWL),
        await api.post(
            f"/api/chapters/{chapter}/documents",
            files={"file": ("x.pptx", pptx.read_bytes())},
            headers=OWL,
        ),
    ):
        assert r.status_code == 404 and r.json()["detail"] == "errors.world_not_found"


async def test_upload_index_and_rollup(api, sm, pptx):
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    r = await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    assert r.status_code == 202
    up = r.json()
    assert up["job_id"] and not up["reused"] and up["document"]["status"] == "uploaded"

    waiting = (await api.get(f"/api/worlds/{world['id']}/indexing", headers=SEA)).json()
    assert waiting["percent"] == 0 and not waiting["done"] and waiting["eta_s"] > 0
    assert waiting["chapters"][0]["state"] == "waiting"
    assert waiting["join_code"] == world["join_code"]

    await Worker(sm).drain(timeout_s=60)
    done = (await api.get(f"/api/worlds/{world['id']}/indexing", headers=SEA)).json()
    assert done["done"] and done["percent"] == 100 and done["eta_s"] == 0
    (ch,) = done["chapters"]
    assert ch["state"] == "done" and ch["title"] == "Stacks" and ch["course_name"]
    assert ch["documents"][0]["page_count"] == len(samples.STACK_SLIDES)
    assert done["quizzes"] == {"state": "done", "ready": 1}

    tree = (await api.get(f"/api/worlds/{world['id']}", headers=SEA)).json()
    assert tree["courses"][0]["chapters"][0]["documents"][0]["status"] == "ready"


async def test_upload_rejects_unknown_types(api):
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    r = await api.post(
        f"/api/chapters/{chapter}/documents", files={"file": ("a.exe", b"MZ")}, headers=SEA
    )
    assert r.status_code == 400 and r.json()["detail"] == "errors.file_type"


async def test_delete_document_removes_vectors(api, sm, pptx):
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    up = (
        await api.post(
            f"/api/chapters/{chapter}/documents",
            files={"file": (pptx.name, pptx.read_bytes())},
            headers=SEA,
        )
    ).json()
    await Worker(sm).drain(timeout_s=60)

    vs = store.get_store(get_settings().llm)
    assert await vs.count({"document_id": up["document"]["id"]}) > 0
    r = await api.delete(f"/api/documents/{up['document']['id']}", headers=SEA)
    assert r.status_code == 204
    assert await vs.count({"document_id": up["document"]["id"]}) == 0


async def test_dev_search_job(api, sm, pptx):
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    await Worker(sm).drain(timeout_s=60)
    r = await api.post(
        "/api/dev/search-jobs",
        json={"world_id": world["id"], "query": "FIFO queue enqueue dequeue"},
        headers=SEA,
    )
    assert r.status_code == 202
    await Worker(sm).drain(timeout_s=30)
    job = (await api.get(f"/api/jobs/{r.json()['job_id']}")).json()
    hits = job["result"]["hits"]
    assert job["status"] == "done" and hits and hits[0]["chapter_id"] == chapter
    assert "queue" in hits[0]["text"].lower()
    outsider = await api.post(
        "/api/dev/search-jobs", json={"world_id": world["id"], "query": "x"}, headers=OWL
    )
    assert outsider.status_code == 404


async def test_bad_nickname_header(api):
    r = await api.get("/api/worlds", headers={"X-Dev-User": "no spaces allowed"})
    assert r.status_code == 400 and r.json()["detail"] == "errors.nickname_invalid"


async def test_production_refuses_dev_users(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(APP_ENV="production"))
    with pytest.raises(deps.HTTPException) as e:
        await deps.current_user(s=None, x_dev_user="SeaTurtle42")
    assert e.value.status_code == 401 and e.value.detail == "errors.sign_in_required"
