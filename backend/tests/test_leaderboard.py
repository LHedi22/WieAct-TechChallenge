"""Class and global leaderboards from the points ledger: week vs all time, opt-out, membership."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.features.leaderboard.service import week_start
from app.features.wallet import service as wallet
from app.models import PointsLedger, User
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import OWL, SEA, api, make_world  # noqa: F401  (fixtures)

FOX = {"X-Dev-User": "DesertFox"}


async def uid(sm, nickname) -> uuid.UUID:
    async with sm() as s:
        return await s.scalar(select(User.id).where(User.nickname == nickname))


async def award(sm, nickname, world_id, points, ref, days_ago=0):
    async with sm() as s:
        user_id = await uid(sm, nickname)
        await wallet.add_points(s, user_id, uuid.UUID(world_id), points, "test", ref)
        if days_ago:
            await s.execute(
                update(PointsLedger)
                .where(PointsLedger.ref == ref)
                .values(created_at=datetime.now(UTC) - timedelta(days=days_ago))
            )
        await s.commit()


async def board(api, world, headers, **params):  # noqa: F811
    r = await api.get(
        "/api/leaderboard", params={"world_id": world["id"], **params}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_week_and_all_time_and_opt_out(api, sm):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL)
    await join(api, world, FOX)
    await award(sm, "SeaTurtle42", world["id"], 50, "a")
    await award(sm, "NightOwl7", world["id"], 30, "b")
    await award(sm, "NightOwl7", world["id"], 100, "c", days_ago=30)  # not this week

    week = await board(api, world, OWL, scope="world", period="week")
    assert [(e["nickname"], e["points"]) for e in week["entries"]] == [
        ("SeaTurtle42", 50),
        ("NightOwl7", 30),
    ]
    assert week["me"]["rank"] == 2 and week["me"]["is_me"]
    all_time = await board(api, world, OWL, scope="world", period="all")
    assert all_time["entries"][0]["nickname"] == "NightOwl7"

    # SeaTurtle42 hides: still ranked in the class (as a Hidden explorer), gone from global
    r = await api.put("/api/profile", json={"leaderboard_opt_in": False}, headers=SEA)
    assert r.status_code == 200, r.text
    week = await board(api, world, OWL, scope="world", period="week")
    assert week["entries"][0] == {
        "rank": 1,
        "nickname": None,
        "avatar": None,
        "points": 50,
        "is_me": False,
    }
    glob = await board(api, world, OWL, scope="global", period="week")
    assert [e["nickname"] for e in glob["entries"]] == ["NightOwl7"]
    mine = await board(api, world, SEA, scope="global", period="week")
    assert mine["me"] is None and mine["opted_in"] is False


async def test_class_board_needs_membership(api, sm):  # noqa: F811
    world = await make_world(api)
    r = await api.get(
        "/api/leaderboard", params={"world_id": world["id"], "scope": "world"}, headers=FOX
    )
    assert r.status_code == 404
    r = await api.get("/api/leaderboard", params={"scope": "world"}, headers=SEA)
    assert r.status_code == 400


def test_week_starts_monday_midnight_in_tunis():
    # Wed 4 Nov 2026 10:00 UTC → Monday 2 Nov 00:00 Tunis = Sun 1 Nov 23:00 UTC
    assert week_start(datetime(2026, 11, 4, 10, tzinfo=UTC)) == datetime(
        2026, 11, 1, 23, tzinfo=UTC
    )
