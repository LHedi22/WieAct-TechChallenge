"""Admin side, phase B: read-only pages with search, filters and pagination. Nothing here writes;
wallets come from the ledger, never from a stored balance."""

import pytest
from sqlalchemy import func, select

from app.admin import browse
from app.models import CoinLedger, User
from tests.admin_helpers import READ, enable_admin, seed_class
from tests.test_admin_phase_a import api, api_for  # noqa: F401  (fixture)


@pytest.fixture
async def seeded(sm, monkeypatch):
    enable_admin(monkeypatch)
    return await seed_class(sm)


async def test_every_read_page_needs_the_admin(api, seeded):  # noqa: F811
    for path in (
        "/api/admin/users",
        f"/api/admin/users/{seeded['ana']}",
        "/api/admin/worlds",
        f"/api/admin/worlds/{seeded['world']}",
        "/api/admin/content",
        "/api/admin/arena/questions",
        "/api/admin/arena/answers",
        "/api/admin/jobs",
        "/api/admin/jobs/summary",
        "/api/admin/cache",
        "/api/admin/cache/summary",
        "/api/admin/actions",
    ):
        assert (await api.get(path)).status_code == 401, path
        assert (await api.get(path, headers=READ)).status_code == 200, path


async def test_users_list_derives_wallets_from_the_ledger(api, sm, seeded):  # noqa: F811
    async with sm() as s:
        before = await s.scalar(select(func.count()).select_from(CoinLedger))
    page = (await api.get("/api/admin/users", headers=READ)).json()
    assert page["total"] == 2 and page["page_size"] == 50
    ana = next(u for u in page["items"] if u["nickname"] == "ana_admin")
    bilel = next(u for u in page["items"] if u["nickname"] == "bilel_admin")
    # today's free 20 - 3 spent, earned 7 from an old day; the old day's free coins don't count
    assert ana["wallet"]["free"] == 17 and ana["wallet"]["earned"] == 7
    assert ana["wallet"]["coins"] == 24 and ana["points"] == 30 and ana["worlds"] == 1
    assert ana["streak"] == 1
    # bilel never opened the app today: the free coins they'll see, without writing a row
    assert bilel["wallet"]["free"] == 20
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(CoinLedger)) == before


async def test_users_search_filter_and_pagination(api, sm, seeded, monkeypatch):  # noqa: F811
    r = (await api.get("/api/admin/users", params={"q": "bil"}, headers=READ)).json()
    assert [u["nickname"] for u in r["items"]] == ["bilel_admin"]
    r = (await api.get("/api/admin/users", params={"language": "ar"}, headers=READ)).json()
    assert [u["nickname"] for u in r["items"]] == ["ana_admin"]
    r = await api.get("/api/admin/users", params={"q": "%"}, headers=READ)
    assert r.json()["total"] == 0  # LIKE wildcards are escaped
    monkeypatch.setattr(browse, "PAGE_SIZE", 1)
    p2 = (await api.get("/api/admin/users", params={"page": 2}, headers=READ)).json()
    assert p2["total"] == 2 and len(p2["items"]) == 1
    bad = await api.get("/api/admin/users", params={"world_id": "nope"}, headers=READ)
    assert bad.status_code == 422


async def test_user_detail(api, seeded):  # noqa: F811
    d = (await api.get(f"/api/admin/users/{seeded['ana']}", headers=READ)).json()
    assert d["nickname"] == "ana_admin" and d["worlds"][0]["name"] == "Olive class"
    assert d["counts"]["questions"] == 1 and d["counts"]["jobs"] == 1
    assert {r["kind"] for r in d["coin_ledger"]} >= {"daily", "spend", "earned"}
    assert d["points_ledger"][0]["reason"] == "quiz"
    assert "password_hash" not in d


async def test_worlds_and_world_detail(api, seeded):  # noqa: F811
    page = (await api.get("/api/admin/worlds", params={"q": "OLV"}, headers=READ)).json()
    w = page["items"][0]
    assert (w["members"], w["courses"], w["documents"], w["failed_documents"], w["pool"]) == (
        2,
        1,
        1,
        1,
        15,
    )
    d = (await api.get(f"/api/admin/worlds/{seeded['world']}", headers=READ)).json()
    doc = d["courses"][0]["chapters"][0]["documents"][0]
    assert doc["status"] == "failed" and doc["error"] == "errors.indexing_failed"
    assert d["pool"]["balance"] == 15 and d["pool"]["history"][0]["by"] == "bilel_admin"
    assert {m["nickname"] for m in d["members"]} == {"ana_admin", "bilel_admin"}


async def test_content(api, seeded):  # noqa: F811
    quiz = (await api.get("/api/admin/content", headers=READ)).json()
    assert quiz["total"] == 1 and quiz["items"][0]["summary"] == "1 questions"
    notes = (
        await api.get(
            "/api/admin/content",
            params={"kind": "study_assets", "language": "ar", "chapter_id": str(seeded["chapter"])},
            headers=READ,
        )
    ).json()
    assert notes["items"][0]["summary"] == "notes"
    item = notes["items"][0]
    full = (await api.get(f"/api/admin/content/study_assets/{item['id']}", headers=READ)).json()
    assert full["body"] == {"sections": []}
    none = (
        await api.get(
            "/api/admin/content", params={"kind": "study_assets", "language": "fr"}, headers=READ
        )
    ).json()
    assert none["total"] == 0


async def test_arena_jobs_cache_log(api, seeded):  # noqa: F811
    a = (
        await api.get("/api/admin/arena/answers", params={"status": "pending_review"}, headers=READ)
    ).json()
    assert a["items"][0]["ai_score"] == 78 and a["items"][0]["author"] == "bilel_admin"
    q = (await api.get("/api/admin/arena/questions", headers=READ)).json()
    assert q["items"][0]["answers"] == 1
    jobs = (await api.get("/api/admin/jobs", params={"lane": "background"}, headers=READ)).json()
    assert [j["kind"] for j in jobs["items"]] == ["CHUNK_TAG"]
    summary = (await api.get("/api/admin/jobs/summary", headers=READ)).json()
    assert {"lane": "interactive", "status": "failed", "count": 1} in summary
    cache = (await api.get("/api/admin/cache", headers=READ)).json()
    assert cache["items"][0]["hits"] == 4 and cache["items"][0]["size_bytes"] > 0
    log = (await api.get("/api/admin/actions", headers=READ)).json()
    assert log["total"] == 0


async def test_dev_users_are_marked(api, sm, seeded):  # noqa: F811
    async with sm() as s:
        await s.execute(
            User.__table__.update().where(User.id == seeded["bilel"]).values(password_hash="x")
        )
        await s.commit()
    page = (await api.get("/api/admin/users", headers=READ)).json()
    flags = {u["nickname"]: u["dev_user"] for u in page["items"]}
    assert flags == {"ana_admin": True, "bilel_admin": False}
