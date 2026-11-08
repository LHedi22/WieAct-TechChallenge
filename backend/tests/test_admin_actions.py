"""Admin side, phase C: every change writes admin_actions, validates with the app's own rules, and
every coin or point change is a ledger row."""

import uuid

import pytest
from sqlalchemy import func, select

from app.admin import actions as admin_actions
from app.core import economy
from app.core.security import read_claims, sign_session
from app.models import (
    AdminAction,
    AICache,
    ChapterMastery,
    ClassPoolLedger,
    CoinLedger,
    CourseLevel,
    Document,
    Job,
    PeerAnswer,
    PeerQuestion,
    PointsLedger,
    QuizSet,
    StudyAsset,
    User,
    World,
)
from tests.admin_helpers import ACT, READ, enable_admin, seed_class
from tests.test_admin_phase_a import api, api_for  # noqa: F401  (fixture)

R = {"reason": "admin test"}


@pytest.fixture
async def seeded(sm, monkeypatch):
    enable_admin(monkeypatch)
    return await seed_class(sm)


async def log(sm, action: str) -> list[AdminAction]:
    async with sm() as s:
        return list(await s.scalars(select(AdminAction).where(AdminAction.action == action)))


# --- users -------------------------------------------------------------------------------------
async def test_edit_user_follows_the_sign_up_rules(api, sm, seeded):  # noqa: F811
    uid = seeded["ana"]
    bad = await api.patch(f"/api/admin/users/{uid}", json={"nickname": "no spaces"}, headers=ACT)
    assert bad.status_code == 422
    taken = await api.patch(
        f"/api/admin/users/{uid}", json={"nickname": "bilel_admin"}, headers=ACT
    )
    assert taken.status_code == 409
    ok = await api.patch(
        f"/api/admin/users/{uid}",
        json={"nickname": "ana_2", "ui_language": "fr", **R},
        headers=ACT,
    )
    assert ok.status_code == 200 and ok.json()["nickname"] == "ana_2"
    row = (await log(sm, "user.edit"))[0]
    assert row.before["nickname"] == "ana_admin" and row.after["ui_language"] == "fr"
    # the action header is required
    assert (await api.patch(f"/api/admin/users/{uid}", json={}, headers=READ)).status_code == 403


async def test_password_reset_and_sign_out_everywhere(api, sm, seeded):  # noqa: F811
    uid = seeded["ana"]
    cookie = sign_session(uid, epoch=0)
    short = await api.post(f"/api/admin/users/{uid}/password", json={"password": "x"}, headers=ACT)
    assert short.status_code == 422
    r = await api.post(
        f"/api/admin/users/{uid}/password", json={"password": "a-new-pass-123"}, headers=ACT
    )
    assert r.status_code == 204
    async with sm() as s:
        user = await s.get(User, uid)
        assert user.password_hash.startswith("$argon2") and user.session_epoch == 1
    assert read_claims(cookie)[1] != 1  # the old cookie's epoch is now refused
    r = await api.post(f"/api/admin/users/{uid}/sign-out", json=R, headers=ACT)
    assert r.json()["session_epoch"] == 2
    me = await api.get("/api/auth/me", cookies={"lw_session": sign_session(uid, epoch=1)})
    assert me.status_code in (200, 401) and (me.status_code == 401 or me.json() is None)
    assert len(await log(sm, "user.password_reset")) == 1
    entry = (await log(sm, "user.password_reset"))[0]
    assert entry.before is None and entry.after is None  # never the hash


async def test_reset_course_dry_run_then_apply(api, sm, seeded):  # noqa: F811
    uid, course = seeded["ana"], seeded["course"]
    async with sm() as s:
        s.add(CourseLevel(user_id=uid, course_id=course, level="advanced"))
        s.add(ChapterMastery(user_id=uid, chapter_id=seeded["chapter"], mastery=80, weak=False))
        await s.commit()
    dry = (
        await api.post(
            f"/api/admin/users/{uid}/reset-course", json={"course_id": str(course)}, headers=ACT
        )
    ).json()
    assert dry["dry_run"] and dry["counts"]["course_levels"] == 1
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(CourseLevel)) == 1
    no_reason = await api.post(
        f"/api/admin/users/{uid}/reset-course",
        json={"course_id": str(course), "dry_run": False},
        headers=ACT,
    )
    assert no_reason.status_code == 422
    done = await api.post(
        f"/api/admin/users/{uid}/reset-course",
        json={"course_id": str(course), "dry_run": False, **R},
        headers=ACT,
    )
    assert done.json()["counts"]["chapter_mastery"] == 1
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(CourseLevel)) == 0
        assert await s.scalar(select(func.count()).select_from(ChapterMastery)) == 0


# --- deletes ------------------------------------------------------------------------------------
@pytest.fixture
def vectors(monkeypatch):
    deleted: list[uuid.UUID] = []

    async def fake(doc_id):
        deleted.append(doc_id)

    from app.rag import store  # noqa: PLC0415

    monkeypatch.setattr(store, "delete_document_everywhere", fake)
    return deleted


async def test_delete_document_needs_dry_run_name_and_cleans_qdrant(api, sm, seeded, vectors):  # noqa: F811
    doc = seeded["document"]
    dry = (await api.post(f"/api/admin/delete/document/{doc}/dry-run", headers=ACT)).json()
    assert dry["confirm_text"] == "limits.pdf" and dry["counts"]["documents"] == 1
    wrong = await api.request(
        "DELETE", f"/api/admin/delete/document/{doc}", json={"confirm": "limits", **R}, headers=ACT
    )
    assert wrong.status_code == 422
    async with sm() as s:
        assert await s.get(Document, doc) is not None
    ok = await api.request(
        "DELETE",
        f"/api/admin/delete/document/{doc}",
        json={"confirm": "limits.pdf", **R},
        headers=ACT,
    )
    assert ok.status_code == 200 and ok.json()["vectors_deleted_for"] == 1
    assert vectors == [doc]
    async with sm() as s:
        assert await s.get(Document, doc) is None
    assert (await log(sm, "document.delete"))[0].before["name"] == "limits.pdf"


async def test_delete_world_cascades_and_cleans_every_document(api, sm, seeded, vectors):  # noqa: F811
    wid = seeded["world"]
    dry = (await api.post(f"/api/admin/delete/world/{wid}/dry-run", headers=ACT)).json()
    assert dry["counts"]["members"] == 2 and dry["counts"]["quiz_sets"] == 1
    r = await api.request(
        "DELETE",
        f"/api/admin/delete/world/{wid}",
        json={"confirm": "Olive class", **R},
        headers=ACT,
    )
    assert r.status_code == 200 and vectors == [seeded["document"]]
    async with sm() as s:
        assert await s.get(World, wid) is None
        assert await s.scalar(select(func.count()).select_from(QuizSet)) == 0


async def test_delete_user_hands_their_world_over_and_drops_their_ledgers(api, sm, seeded):  # noqa: F811
    ana = seeded["ana"]
    dry = (await api.post(f"/api/admin/delete/user/{ana}/dry-run", headers=ACT)).json()
    assert dry["worlds_transferred"][0]["new_creator"] == str(seeded["bilel"])
    assert dry["counts"]["coin_ledger_rows"] == 4 and dry["blocked_by"] == []
    r = await api.request(
        "DELETE", f"/api/admin/delete/user/{ana}", json={"confirm": "ana_admin", **R}, headers=ACT
    )
    assert r.status_code == 200, r.text
    async with sm() as s:
        assert (await s.get(World, seeded["world"])).creator_id == seeded["bilel"]
        assert (
            await s.scalar(
                select(func.count()).select_from(CoinLedger).where(CoinLedger.user_id == ana)
            )
            == 0
        )
        job = await s.scalar(select(Job).where(Job.kind == "QUIZ"))
        assert job.user_id is None  # jobs stay, anonymous
        pool = await s.scalar(select(func.sum(ClassPoolLedger.delta)))
        assert pool == 15  # the class pool doesn't change


async def test_a_world_with_no_one_else_blocks_its_creators_deletion(api, sm, seeded):  # noqa: F811
    bilel = seeded["bilel"]
    async with sm() as s:
        s.add(World(name="Solo", join_code="SOLO-1", creator_id=bilel))
        await s.commit()
    dry = (await api.post(f"/api/admin/delete/user/{bilel}/dry-run", headers=ACT)).json()
    assert [b["world"] for b in dry["blocked_by"]] == ["Solo"]
    r = await api.request(
        "DELETE",
        f"/api/admin/delete/user/{bilel}",
        json={"confirm": "bilel_admin", **R},
        headers=ACT,
    )
    assert r.status_code == 409


# --- worlds, re-index ---------------------------------------------------------------------------
async def test_world_course_chapter_edits(api, sm, seeded):  # noqa: F811
    w = await api.patch(
        f"/api/admin/worlds/{seeded['world']}",
        json={"name": "Olive B", "regenerate_join_code": True},
        headers=ACT,
    )
    assert w.json()["name"] == "Olive B" and w.json()["join_code"] != "OLV-ADM"
    c = await api.patch(
        f"/api/admin/courses/{seeded['course']}", json={"exam_date": "2026-12-15"}, headers=ACT
    )
    assert c.json()["exam_date"] == "2026-12-15"
    ch = await api.patch(
        f"/api/admin/chapters/{seeded['chapter']}", json={"title": "Limits!"}, headers=ACT
    )
    assert ch.json()["title"] == "Limits!"
    creator = await api.delete(
        f"/api/admin/worlds/{seeded['world']}/members/{seeded['ana']}", headers=ACT
    )
    assert creator.status_code == 409
    gone = await api.delete(
        f"/api/admin/worlds/{seeded['world']}/members/{seeded['bilel']}", headers=ACT
    )
    assert gone.status_code == 200
    assert {a.action for a in await log(sm, "world.edit")} == {"world.edit"}


async def test_reindex_queues_a_background_job(api, sm, seeded, monkeypatch, tmp_path):  # noqa: F811
    missing = await api.post(
        f"/api/admin/documents/{seeded['document']}/reindex", json={}, headers=ACT
    )
    assert missing.status_code == 409  # the uploaded file is gone
    monkeypatch.setattr(admin_actions, "upload_root", lambda: tmp_path)
    (tmp_path / "nowhere").mkdir()
    (tmp_path / "nowhere" / "limits.pdf").write_bytes(b"%PDF")
    async with sm() as s:
        doc = await s.get(Document, seeded["document"])
        doc.storage_path = "nowhere/limits.pdf"
        await s.commit()
    r = await api.post(f"/api/admin/chapters/{seeded['chapter']}/reindex", json=R, headers=ACT)
    assert r.status_code == 200 and len(r.json()["jobs"]) == 1
    async with sm() as s:
        job = await s.get(Job, uuid.UUID(r.json()["jobs"][0]))
        assert job.kind == "INDEX_DOCUMENT" and job.lane == "background"
        assert (await s.get(Document, seeded["document"])).status == "uploaded"
    again = await api.post(
        f"/api/admin/documents/{seeded['document']}/reindex", json={}, headers=ACT
    )
    assert again.json()["jobs"] == r.json()["jobs"]  # no second job while one is queued


# --- economy ------------------------------------------------------------------------------------
async def test_coins_are_ledger_rows_and_never_negative(api, sm, seeded):  # noqa: F811
    uid = seeded["ana"]
    no_reason = await api.post(
        f"/api/admin/users/{uid}/coins", json={"bucket": "earned", "delta": 5}, headers=ACT
    )
    assert no_reason.status_code == 422
    r = await api.post(
        f"/api/admin/users/{uid}/coins", json={"bucket": "earned", "delta": 50, **R}, headers=ACT
    )
    assert r.status_code == 200 and r.json()["earned"] == 57  # the earn cap doesn't apply
    neg = await api.post(
        f"/api/admin/users/{uid}/coins", json={"bucket": "purchased", "delta": -1, **R}, headers=ACT
    )
    assert neg.status_code == 422 and "negative" in neg.json()["detail"]
    async with sm() as s:
        rows = list(await s.scalars(select(CoinLedger).where(CoinLedger.kind == "admin")))
    assert [(r.bucket, r.delta) for r in rows] == [("earned", 50)]
    wallet = (await api.get("/api/wallet", headers={"X-Dev-User": "ana_admin"})).json()
    assert wallet["coins"] == 17 + 57
    entry = (await log(sm, "coins.adjust"))[0]
    assert entry.before == {"earned": 7} and entry.after["earned"] == 57


async def test_points_and_pool(api, sm, seeded):  # noqa: F811
    uid = seeded["ana"]
    r = await api.post(f"/api/admin/users/{uid}/points", json={"delta": -10, **R}, headers=ACT)
    assert r.json()["points"] == 20
    too_far = await api.post(
        f"/api/admin/users/{uid}/points", json={"delta": -21, **R}, headers=ACT
    )
    assert too_far.status_code == 422
    async with sm() as s:
        adj = await s.scalar(select(PointsLedger).where(PointsLedger.reason == "admin_adjust"))
        assert adj.delta == -10 and adj.ref.startswith("admin:")
    pool = await api.post(
        f"/api/admin/worlds/{seeded['world']}/pool", json={"delta": -16, **R}, headers=ACT
    )
    assert pool.status_code == 422
    pool = await api.post(
        f"/api/admin/worlds/{seeded['world']}/pool", json={"delta": 5, **R}, headers=ACT
    )
    assert pool.json()["balance"] == 20


async def test_exam_pass_grant_and_end(api, sm, seeded):  # noqa: F811
    uid = seeded["ana"]
    no = await api.post(
        f"/api/admin/users/{uid}/exam-pass", json={"action": "end", **R}, headers=ACT
    )
    assert no.status_code == 422
    g = await api.post(
        f"/api/admin/users/{uid}/exam-pass", json={"action": "grant", **R}, headers=ACT
    )
    assert g.json()["pass_active"] is True
    wallet = (await api.get("/api/wallet", headers={"X-Dev-User": "ana_admin"})).json()
    assert wallet["exam_pass_until"] is not None
    e = await api.post(
        f"/api/admin/users/{uid}/exam-pass", json={"action": "end", **R}, headers=ACT
    )
    assert e.json()["pass_active"] is False


async def test_economy_overrides_reach_prices_and_the_economy_endpoint(api, sm, seeded):  # noqa: F811
    view = (await api.get("/api/admin/economy", headers=READ)).json()
    quiz = next(i for i in view["items"] if i["key"] == "cost.quiz")
    assert quiz["default"] == quiz["effective"] == 5
    bad = await api.put("/api/admin/economy/cost.quiz", json={"value": -1, **R}, headers=ACT)
    assert bad.status_code == 422
    unknown = await api.put(
        "/api/admin/economy/cost.free_lunch", json={"value": 1, **R}, headers=ACT
    )
    assert unknown.status_code == 422
    r = await api.put("/api/admin/economy/cost.quiz", json={"value": 7, **R}, headers=ACT)
    quiz = next(i for i in r.json()["items"] if i["key"] == "cost.quiz")
    assert quiz["effective"] == 7 and quiz["default"] == 5 and quiz["overridden"]
    pub = (await api.get("/api/economy")).json()
    assert pub["cost"]["quiz"] == 7 and pub["buildings"]["quiz_hall"]["cost"] == 7
    assert economy.COST["quiz"] == 7
    back = await api.put("/api/admin/economy/cost.quiz", json={"value": None, **R}, headers=ACT)
    assert next(i for i in back.json()["items"] if i["key"] == "cost.quiz")["effective"] == 5
    assert (await api.get("/api/economy")).json()["cost"]["quiz"] == 5


async def test_invariant_check_reports_without_fixing(api, sm, seeded):  # noqa: F811
    ok = (await api.get("/api/admin/invariants", headers=READ)).json()
    assert ok["ok"] is True, ok["violations"]
    async with sm() as s:
        for _ in range(2):  # a duplicated reward and a negative earned bucket
            s.add(
                CoinLedger(
                    user_id=seeded["bilel"],
                    day=economy.next_refill().date(),
                    bucket="earned",
                    kind="earned",
                    delta=-2,
                    ref="dup",
                )
            )
        await s.commit()
    bad = (await api.get("/api/admin/invariants", headers=READ)).json()
    checks = {v["check"] for v in bad["violations"]}
    assert {"negative_bucket", "duplicate_reward"} <= checks
    async with sm() as s:
        assert await s.scalar(select(func.count()).where(CoinLedger.ref == "dup")) == 2


# --- jobs and cache -----------------------------------------------------------------------------
async def test_cancel_refunds_once_retry_and_run_now(api, sm, seeded):  # noqa: F811
    async with sm() as s:
        job = await s.scalar(select(Job).where(Job.kind == "QUIZ"))
        job.status = "running"
        s.add(
            CoinLedger(
                user_id=seeded["ana"],
                day=economy.next_refill().date(),
                bucket="free",
                kind="spend",
                delta=-3,
                ref=str(job.id),
            )
        )
        await s.commit()
        jid = job.id
    r = await api.post(f"/api/admin/jobs/{jid}/cancel", json=R, headers=ACT)
    assert r.json()["status"] == "cancelled"
    again = await api.post(f"/api/admin/jobs/{jid}/cancel", json=R, headers=ACT)
    assert again.status_code == 409
    async with sm() as s:
        refunds = list(
            await s.scalars(
                select(CoinLedger).where(CoinLedger.ref == str(jid), CoinLedger.kind == "refund")
            )
        )
    assert [x.delta for x in refunds] == [3]
    retry = await api.post(f"/api/admin/jobs/{jid}/retry", json=R, headers=ACT)
    assert retry.json()["status"] == "queued"
    now = await api.post(f"/api/admin/jobs/{jid}/run-now", json=R, headers=ACT)
    assert now.status_code == 200
    async with sm() as s:
        (await s.get(Job, jid)).error = "deferred:quota"
        await s.commit()
    quota = await api.post(f"/api/admin/jobs/{jid}/run-now", json=R, headers=ACT)
    assert quota.status_code == 409  # the platform's stated quota delay is respected


async def test_cache_purge_warns_for_cloud_entries(api, sm, seeded):  # noqa: F811
    async with sm() as s:
        s.add(
            AICache(
                key="k-cloud",
                task_kind="NOTES_WRITE",
                content={"value": 1},
                model_tier="mid",
                provider="cloud",
                model="m",
            )
        )
        await s.commit()
    dry = (
        await api.post("/api/admin/cache/purge", json={"task_kind": "NOTES_WRITE"}, headers=ACT)
    ).json()
    assert (
        dry["entries"] == 2 and dry["cloud_entries"] == 1 and "repeated identical" in dry["warning"]
    )
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(AICache)) == 2
    assert dry["confirm_text"] == "purge cloud entries"
    no_confirm = await api.post(
        "/api/admin/cache/purge",
        json={"task_kind": "NOTES_WRITE", "dry_run": False, **R},
        headers=ACT,
    )
    assert no_confirm.status_code == 422  # platform entries need the typed confirm
    done = await api.post(
        "/api/admin/cache/purge",
        json={"task_kind": "NOTES_WRITE", "provider": "mock", "dry_run": False, **R},
        headers=ACT,
    )
    assert done.json()["entries"] == 1
    async with sm() as s:
        assert [k for k in await s.scalars(select(AICache.key))] == ["k-cloud"]


# --- content and arena --------------------------------------------------------------------------
async def test_content_edit_is_validated_and_flagged(api, sm, seeded):  # noqa: F811
    async with sm() as s:
        quiz = await s.scalar(select(QuizSet))
        notes = await s.scalar(select(StudyAsset))
    bad = await api.put(
        f"/api/admin/content/quiz_sets/{quiz.id}",
        json={
            "body": [{"question": "Q?", "options": ["a", "a", "b", "c"], "answer_index": 0}],
            **R,
        },
        headers=ACT,
    )
    assert bad.status_code == 422  # options must be distinct: the app's own schema
    good_q = {
        "question": "lim x->0 of x?",
        "options": ["0", "1", "2", "3"],
        "answer_index": 0,
        "hint": "plug in",
        "explanation": "x goes to 0",
        "concept": "limits",
        "verified": True,
    }
    ok = await api.put(
        f"/api/admin/content/quiz_sets/{quiz.id}", json={"body": [good_q], **R}, headers=ACT
    )
    assert ok.status_code == 200 and ok.json()["body"][0]["verified"] is True  # extras kept
    notes_bad = await api.put(
        f"/api/admin/content/study_assets/{notes.id}",
        json={"body": {"sections": []}, **R},
        headers=ACT,
    )
    assert notes_bad.status_code == 422
    page = (await api.get("/api/admin/content", headers=READ)).json()
    assert page["items"][0]["edited_by_admin"] is True
    entry = (await log(sm, "content.edit"))[0]
    assert entry.before["body"] == [{"q": "lim?"}]


async def test_arena_moderation(api, sm, seeded):  # noqa: F811
    a, q = seeded["answer"], seeded["question"]
    no_score = await api.post(
        f"/api/admin/arena/answers/{a}", json={"action": "score", **R}, headers=ACT
    )
    assert no_score.status_code == 422
    r = await api.post(
        f"/api/admin/arena/answers/{a}", json={"action": "score", "score": 85, **R}, headers=ACT
    )
    assert r.json()["status"] == "graded" and r.json()["rewarded"] is True
    assert r.json()["coins_earned"] == economy.EARN["peer_answer_good"]
    twice = await api.post(
        f"/api/admin/arena/answers/{a}", json={"action": "score", "score": 90, **R}, headers=ACT
    )
    assert twice.status_code == 409  # no longer pending: paid once
    async with sm() as s:
        earned = list(await s.scalars(select(CoinLedger).where(CoinLedger.ref == f"answer:{a}")))
        assert len(earned) == 1
        ask = Job(
            kind="ARENA_ASK",
            lane="interactive",
            status="done",
            payload={"question_id": str(q)},
            stages=[],
            user_id=seeded["ana"],
            cost=2,
        )
        s.add(ask)
        await s.flush()
        s.add(
            CoinLedger(
                user_id=seeded["ana"],
                day=economy.next_refill().date(),
                bucket="free",
                kind="spend",
                delta=-2,
                ref=str(ask.id),
            )
        )
        await s.commit()
        ask_id = ask.id
    rej = await api.post(
        f"/api/admin/arena/questions/{q}", json={"action": "reject", **R}, headers=ACT
    )
    assert rej.json()["status"] == "rejected"
    async with sm() as s:
        refund = await s.scalar(
            select(CoinLedger).where(CoinLedger.ref == str(ask_id), CoinLedger.kind == "refund")
        )
        assert refund.delta == 2
    back = await api.post(
        f"/api/admin/arena/questions/{q}", json={"action": "restore", **R}, headers=ACT
    )
    assert back.json()["status"] == "open"
    rej_a = await api.post(
        f"/api/admin/arena/answers/{a}", json={"action": "reject", **R}, headers=ACT
    )
    assert rej_a.json()["status"] == "rejected"
    async with sm() as s:
        assert (await s.get(PeerAnswer, a)).status == "rejected"
        assert (await s.get(PeerQuestion, q)).status == "open"
    assert len(await log(sm, "answer.score")) == 1
