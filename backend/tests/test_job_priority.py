"""Group E (prefetch): `jobs.priority` orders the queue inside a lane (migration 0018), and a
student who joins a queued background job promotes it to the interactive lane."""

from sqlalchemy import select

from app.jobs import demo, prefetch
from app.jobs.service import (
    P_DEFAULT,
    P_NEEDED_NOW,
    P_NEXT_CHAPTER,
    create_job,
    create_or_join_shared_job,
    queue_position,
)
from app.jobs.worker import Worker
from app.models import Job


async def test_priority_orders_the_queue_inside_a_lane(sm):
    async with sm() as s:
        later = await create_job(s, kind=demo.KIND, lane="background")  # P_DEFAULT
        first = await create_job(s, kind=demo.KIND, lane="background", priority=P_NEXT_CHAPTER)
        assert later.priority == P_DEFAULT
        assert await queue_position(s, first) == 1  # created later, but more urgent
        assert await queue_position(s, later) == 2
    picked = await Worker(sm).claim("background")
    assert picked.id == first.id


async def test_a_student_joining_a_queued_prefetch_promotes_it(sm):
    async with sm() as s:
        job_id, created = await create_or_join_shared_job(
            s, kind=demo.KIND, share_key="X:1", lane="background", priority=P_NEXT_CHAPTER
        )
        assert created
        other = await create_job(s, kind=demo.KIND, lane="interactive")
    async with sm() as s:
        joined, created = await create_or_join_shared_job(
            s, kind=demo.KIND, share_key="X:1", lane="interactive"
        )
        assert (joined, created) == (job_id, False)
    async with sm() as s:
        job = await s.get(Job, job_id)
        assert (job.lane, job.priority) == ("interactive", P_NEEDED_NOW)
        assert job.cost == 0 and job.user_id is None  # joining never makes it a paid job
        assert any(e["type"] == "promoted" for e in job.events)
        assert await queue_position(s, job) == 1  # ahead of the plain interactive job
        assert await queue_position(s, await s.get(Job, other.id)) == 2


async def test_joining_in_the_background_lane_changes_nothing(sm):
    async with sm() as s:
        job_id, _ = await create_or_join_shared_job(
            s, kind=demo.KIND, share_key="X:2", lane="background", priority=P_NEXT_CHAPTER
        )
        await create_or_join_shared_job(s, kind=demo.KIND, share_key="X:2", lane="background")
    async with sm() as s:
        job = await s.scalar(select(Job).where(Job.id == job_id))
        assert (job.lane, job.priority) == ("background", P_NEXT_CHAPTER)


async def test_one_prefetch_set_runs_placement_then_quiz_and_pack_then_audio(sm):
    """Prefetch step 3: inside one set, the placement quiz goes first (it is the first screen of
    a course), then the quiz set and the study pack (oldest first), and the audio episode last
    (first in the scope guard, the first thing a mid cap drops)."""
    from app.features.audio import service as audio  # noqa: PLC0415
    from app.features.placement import service as placement  # noqa: PLC0415
    from app.features.quiz import pool  # noqa: PLC0415
    from app.features.studio import pack  # noqa: PLC0415

    order = [placement.KIND, pool.KIND, pack.KIND, audio.KIND]
    async with sm() as s:
        for kind in reversed(order):  # created in the worst order
            await create_job(s, kind=kind, lane="background", priority=prefetch.priority(kind))
    w = Worker(sm)
    claimed = [(await w.claim("background")).kind for _ in order]
    assert claimed[0] == placement.KIND and claimed[-1] == audio.KIND
    assert prefetch.priority(pool.KIND) == prefetch.priority(pack.KIND) == P_NEXT_CHAPTER
    assert prefetch.priority(placement.KIND) < P_NEXT_CHAPTER < prefetch.priority(audio.KIND)
    assert max(map(prefetch.priority, order)) < P_DEFAULT  # never behind ordinary background work


def test_prefetch_priorities_name_the_real_job_kinds():
    from app.features.audio import service as audio  # noqa: PLC0415
    from app.features.placement import service as placement  # noqa: PLC0415
    from app.features.quiz import pool  # noqa: PLC0415
    from app.features.studio import pack  # noqa: PLC0415

    assert set(prefetch.PRIORITY) == {placement.KIND, pool.KIND, pack.KIND, audio.KIND}
