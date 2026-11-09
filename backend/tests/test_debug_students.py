"""Debugger, phase B: the student inspector (read-only) and the shared invariant checks. Every
invariant must catch a deliberately broken ledger; the unique indexes that normally prevent the
breakage are dropped inside one transaction that is rolled back at the end."""

import uuid
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import func, select, text

from app.admin import auth
from app.admin import invariants as inv
from app.core import economy
from app.core.db import get_session, get_sessionmaker
from app.core.wallet_rules import tunis_day
from app.main import create_app
from app.models import (
    Chapter,
    ClassPoolLedger,
    CoinLedger,
    Course,
    Job,
    PeerAnswer,
    PeerQuestion,
    PointsLedger,
    User,
    World,
    WorldMember,
)
from tests.admin_helpers import READ, enable_admin, seed_class


@pytest.fixture(autouse=True)
def fresh_attempts(monkeypatch):
    monkeypatch.setattr(auth, "attempts", auth.AttemptLimiter())


@pytest.fixture
def api(sm, monkeypatch):
    enable_admin(monkeypatch)
    app = create_app()

    async def session():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_sessionmaker] = lambda: sm
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def coin(user, bucket, kind, delta, ref=None, day=None):
    return CoinLedger(
        id=uuid.uuid4(),
        user_id=user,
        day=day or tunis_day(),
        bucket=bucket,
        kind=kind,
        delta=delta,
        ref=ref,
    )


async def test_inspector_shows_a_clean_student_and_writes_nothing(sm, api):
    ids = await seed_class(sm)
    async with sm() as s:
        before = await s.scalar(select(func.count()).select_from(CoinLedger))
    r = await api.get(f"/api/admin/debug/students/{ids['bilel']}", headers=READ)
    assert r.status_code == 200, r.text
    d = r.json()
    # bilel has no refill row today: the wallet shows the 20 free coins of their next visit
    assert (
        d["wallet"]["free"] == economy.DAILY_FREE_COINS and not d["wallet"]["has_daily_row_today"]
    )
    assert d["admin_wallet_view"]["coins"] == d["wallet"]["coins"]
    assert {c["check"] for c in d["invariants"]} == set(inv.CHECKS) - inv.WORLD_ONLY
    assert all(c["ok"] for c in d["invariants"]), d["invariants"]
    assert d["activity"]["peer_answers"][0]["status"] == "pending_review"
    assert {x["scope"] for x in d["points"]["ranks"]} == {"global", "world"}
    async with sm() as s:  # the wallet function's refill row was rolled back
        assert await s.scalar(select(func.count()).select_from(CoinLedger)) == before

    ana = (await api.get(f"/api/admin/debug/students/{ids['ana']}", headers=READ)).json()
    assert ana["wallet"]["free"] == 17 and ana["wallet"]["earned"] == 7
    assert ana["wallet"]["days"][0]["day"] == str(tunis_day())
    assert (
        await api.get(f"/api/admin/debug/students/{uuid.uuid4()}", headers=READ)
    ).status_code == 404


async def test_every_invariant_catches_a_broken_ledger(sm, monkeypatch):
    async with sm() as s:
        u = User(id=uuid.uuid4(), nickname="broken_ledger", password_hash="!", ui_language="en")
        w = World(id=uuid.uuid4(), name="W", join_code="BRK-001", creator_id=u.id)
        s.add(u)
        await s.flush()
        s.add(w)
        await s.flush()
        course = Course(id=uuid.uuid4(), world_id=w.id, name="C", color_key="island1")
        s.add_all([WorldMember(world_id=w.id, user_id=u.id), course])
        await s.flush()
        ch = Chapter(id=uuid.uuid4(), course_id=course.id, idx=0, title="T")
        s.add(ch)
        await s.flush()
        q = PeerQuestion(
            id=uuid.uuid4(),
            world_id=w.id,
            chapter_id=ch.id,
            author_id=u.id,
            text="?",
            language="en",
            status="open",
        )
        s.add(q)
        await s.flush()
        a = PeerAnswer(
            id=uuid.uuid4(),
            question_id=q.id,
            author_id=u.id,
            text="!",
            status="pending_review",
            rewarded=True,
        )
        job = Job(kind="QUIZ_POOL", lane="interactive", status="failed", cost=5, user_id=u.id)
        s.add_all([a, job])
        await s.commit()

    async with sm() as s:
        # the indexes that normally forbid this breakage go, inside this transaction only
        names = (
            await s.scalars(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename IN"
                    " ('coin_ledger', 'points_ledger', 'class_pool_ledger')"
                    " AND indexdef LIKE 'CREATE UNIQUE%' AND indexname NOT LIKE 'pk_%'"
                )
            )
        ).all()
        for n in names:
            await s.execute(text(f'DROP INDEX "{n}"'))
        today, old = tunis_day(), date(2026, 1, 5)
        s.add_all(
            [
                coin(u.id, "free", "daily", 20),
                coin(u.id, "free", "daily", 20),  # daily_once
                coin(u.id, "earned", "spend", -30, "x1"),  # negative_bucket (earned < 0)
                coin(u.id, "earned", "earned", 6, "r1", old),
                coin(u.id, "earned", "earned", 6, "r1", old),  # duplicate_reward + earned_cap
                coin(u.id, "free", "spend", -3, "j9"),
                coin(u.id, "free", "refund", 3, "j9"),
                coin(u.id, "free", "refund", 3, "j9"),  # over_refund
                coin(u.id, "free", "spend", -5, str(job.id)),  # unrefunded_job
                coin(u.id, "earned", "earned", 3, f"answer:{a.id}"),  # pending_review_rewarded
                *[coin(u.id, "pass", "spend", 0, f"p{i}") for i in range(16)],  # pass_over_limit
                PointsLedger(user_id=u.id, world_id=w.id, delta=5, reason="quiz", ref="q1"),
                PointsLedger(user_id=u.id, world_id=w.id, delta=5, reason="quiz", ref="q1"),
                ClassPoolLedger(world_id=w.id, user_id=u.id, kind="spend", delta=-15, ref="pj"),
                ClassPoolLedger(world_id=w.id, user_id=u.id, kind="refund", delta=15, ref="pj"),
                ClassPoolLedger(world_id=w.id, user_id=u.id, kind="refund", delta=15, ref="pj"),
                ClassPoolLedger(world_id=w.id, user_id=u.id, kind="spend", delta=-40, ref="pk"),
            ]
        )
        await s.flush()

        # wallet_matches_ledger: make the wallet function disagree with the ledger sums
        import app.features.wallet.service as wallet  # noqa: PLC0415
        from app.admin.browse import wallets  # noqa: PLC0415

        async def off_by_one(s_, user_id, now=None):
            # (the real one writes today's refill with ON CONFLICT, whose index is dropped here)
            raw = (await wallets(s_, [user_id]))[user_id]
            return wallet.Balances(raw["free"], raw["earned"] + 1, raw["purchased"], 0, None, 0)

        monkeypatch.setattr(wallet, "balances", off_by_one)
        student = await inv.run(s, u.id)
        whole = await inv.run(s)
        await s.rollback()

    broken = {name for name, rows in student.items() if rows} | {
        name for name in inv.WORLD_ONLY if whole[name]
    }
    assert broken == set(inv.CHECKS), set(inv.CHECKS) - broken
    assert today  # (the refill rows are on today)
    async with sm() as s:  # the transaction (and the dropped indexes) rolled back
        n = await s.scalar(
            text("SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_points_ledger_award'")
        )
        assert n == 1


async def test_global_invariants_endpoint_uses_the_same_checks(sm, api):
    await seed_class(sm)
    r = (await api.get("/api/admin/invariants", headers=READ)).json()
    assert r["ok"] is True and r["violations"] == []


async def test_explain_price_follows_the_apps_pricing(sm, api):
    ids = await seed_class(sm)
    url = f"/api/admin/debug/students/{ids['ana']}/price"
    quiz = (
        await api.get(
            url, headers=READ, params={"activity": "quiz", "chapter_id": str(ids["chapter"])}
        )
    ).json()
    # the seeded class set is unverified (not shareable), so a new set is charged
    assert quiz["base_cost"] == economy.COST["quiz"] and quiz["split"] == {"free": 5}
    assert any("spending order" in step for step in quiz["steps"])
    # ana (ar) already has the class's Arabic notes: free; bilel (fr) would pay, or use the pool
    params = {"activity": "study_pack", "chapter_id": str(ids["chapter"])}
    free = (await api.get(url, headers=READ, params=params)).json()
    assert free["pays"] == 0 and free["steps"][-1] == "Nothing is charged."
    bilel = f"/api/admin/debug/students/{ids['bilel']}/price"
    pack = (await api.get(bilel, headers=READ, params=params)).json()
    assert pack["base_cost"] == economy.COST["generate_shared_asset"]
    assert pack["pool"] == {"balance": 15, "can_pay": True} and pack["split"] == {"free": 15}
    solo = (await api.get(url, headers=READ, params={"activity": "teachback_solo"})).json()
    assert solo["pays"] == economy.COST["teachback_solo"] and solo["split"] == {"free": 8}
    need = await api.get(url, headers=READ, params={"activity": "quiz"})
    assert need.status_code == 422

    async with sm() as s:  # an Exam Pass pays instead of coins
        s.add(
            CoinLedger(
                id=uuid.uuid4(),
                user_id=ids["ana"],
                day=tunis_day(),
                bucket="pass",
                kind="purchased",
                delta=0,
                ref="exam_pass",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()
    solo = (await api.get(url, headers=READ, params={"activity": "teachback_solo"})).json()
    assert solo["exam_pass"] and solo["pays"] == 0
