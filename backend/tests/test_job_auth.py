"""Audit F-ACL-2 (Tier 2 #5): GET /api/jobs/{id} and POST /api/jobs/{id}/cancel had no auth at all;
anyone, even signed out, could read any job and cancel another student's queued job.

Now: signed-out → 401. A job is visible to its owner, and class-level jobs (a Study pack, audio
episode, quiz pool, placement set, indexing, Class Wisdom tip) to the members of their world,
because classmates are attached to them. Personal jobs (Tutor, Teach-Back grades, daily plan…) are
owner-only. Only the owner cancels. Everyone else gets 404, so a job's existence isn't revealed."""

import pytest

from app.features.studio import pack
from app.features.tutor import service as tutor
from app.jobs import demo
from app.jobs.service import create_job
from app.models import User, World, WorldMember
from tests.test_jobs import api  # noqa: F401  (fixture)

OWNER, CLASSMATE, OUTSIDER = "JobOwner1", "JobMate2", "JobStranger3"


def h(nick: str) -> dict[str, str]:
    return {"X-Dev-User": nick}


@pytest.fixture
async def jobs(sm, api):  # noqa: F811
    for nick in (OWNER, CLASSMATE, OUTSIDER):  # create the dev users
        await api.get("/api/auth/me", headers=h(nick))
    async with sm() as s:
        from sqlalchemy import select  # noqa: PLC0415

        users = {u.nickname: u for u in await s.scalars(select(User))}
        world = World(name="Job world", join_code="JOBSS-2AB", creator_id=users[OWNER].id)
        s.add(world)
        await s.flush()
        for nick in (OWNER, CLASSMATE):
            s.add(WorldMember(world_id=world.id, user_id=users[nick].id))
        await s.commit()
        own = dict(user_id=users[OWNER].id, world_id=world.id)
        personal = await create_job(s, kind=tutor.KIND, lane="interactive", **own)
        shared = await create_job(
            s,
            kind=pack.KIND,
            lane="interactive",
            payload={"chapter_id": "x", "level": "advanced", "language": "en"},
            **own,
        )
        legacy = await create_job(s, kind=demo.KIND, lane="interactive")  # no owner at all
    return {"personal": str(personal.id), "shared": str(shared.id), "legacy": str(legacy.id)}


async def test_signed_out_callers_get_401(api, jobs):  # noqa: F811
    for job_id in jobs.values():
        assert (await api.get(f"/api/jobs/{job_id}")).status_code == 401
        assert (await api.post(f"/api/jobs/{job_id}/cancel")).status_code == 401


async def test_the_owner_reads_and_cancels(api, jobs):  # noqa: F811
    assert (await api.get(f"/api/jobs/{jobs['personal']}", headers=h(OWNER))).status_code == 200
    r = await api.post(f"/api/jobs/{jobs['personal']}/cancel", headers=h(OWNER))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


async def test_personal_jobs_are_hidden_from_classmates_and_outsiders(api, jobs):  # noqa: F811
    for nick in (CLASSMATE, OUTSIDER):
        assert (await api.get(f"/api/jobs/{jobs['personal']}", headers=h(nick))).status_code == 404
        r = await api.post(f"/api/jobs/{jobs['personal']}/cancel", headers=h(nick))
        assert r.status_code == 404


async def test_class_jobs_are_visible_to_members_but_only_the_owner_cancels(api, jobs):  # noqa: F811
    assert (await api.get(f"/api/jobs/{jobs['shared']}", headers=h(CLASSMATE))).status_code == 200
    assert (await api.get(f"/api/jobs/{jobs['shared']}", headers=h(OUTSIDER))).status_code == 404
    r = await api.post(f"/api/jobs/{jobs['shared']}/cancel", headers=h(CLASSMATE))
    assert r.status_code == 404


async def test_a_job_without_owner_is_not_public(api, jobs):  # noqa: F811
    assert (await api.get(f"/api/jobs/{jobs['legacy']}", headers=h(OUTSIDER))).status_code == 404


async def test_unknown_job_is_404_when_signed_in(api, jobs):  # noqa: F811
    r = await api.get("/api/jobs/00000000-0000-0000-0000-000000000000", headers=h(OWNER))
    assert r.status_code == 404
