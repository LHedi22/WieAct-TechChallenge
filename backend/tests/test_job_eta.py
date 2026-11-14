"""Audit OPT-10: the loading screen's ETA was queue position × average *call* latency ÷ 2, but a
job makes 2–4 calls and jobs deferred to a later `not_before` counted as ahead: first ETAs said
1–8 s for waits of 19–60 s (logs/32-same-chapter-10.log, mock).

Now the ETA adds up what is really ahead (each job's own kind's recent duration, the time left of
running jobs, never a job deferred to later) and divides by the calls that run at once."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.features.studio import pack
from app.jobs import demo
from app.jobs.service import queue_position, view
from app.models import Job


def row(now, kind, status, lane="interactive", *, ago=0.0, took=None, started_ago=None, **kw):
    created = now - timedelta(seconds=ago)
    j = Job(
        id=uuid.uuid4(),
        kind=kind,
        lane=lane,
        status=status,
        payload={},
        stages=[],
        created_at=created,
        **kw,
    )
    if took is not None:  # a finished job of this kind: how long it ran
        j.started_at, j.finished_at = created, created + timedelta(seconds=took)
    if started_ago is not None:
        j.started_at = now - timedelta(seconds=started_ago)
    return j


async def test_eta_adds_up_real_job_durations_per_kind_and_lane(sm):
    assert get_settings().LLM_MAX_CONCURRENCY == 2
    now = datetime.now(UTC)
    history = [
        row(now, demo.KIND, "done", ago=900, took=8),
        row(now, demo.KIND, "done", ago=800, took=12),  # demo jobs take 10 s
        row(now, pack.KIND, "done", ago=700, took=30),  # study packs 30 s
    ]
    running = row(now, pack.KIND, "running", ago=60, started_ago=10)  # 20 s left
    ahead = [row(now, demo.KIND, "queued", ago=50), row(now, demo.KIND, "queued", ago=40)]
    later = row(now, demo.KIND, "queued", ago=45, not_before=now + timedelta(minutes=10))
    behind = row(now, pack.KIND, "queued", lane="background", ago=55)  # background waits for us
    me = row(now, pack.KIND, "queued", ago=1)
    async with sm() as s:
        s.add_all([*history, running, *ahead, later, behind, me])
        await s.commit()
        assert await queue_position(s, me) == 3  # the deferred job isn't ahead
        v = await view(s, me)
        # (20 left + 10 + 10 ahead) / 2 calls at once, then its own 30 s (its calls run in turn)
        assert 49 <= v.eta_s <= 51, v.eta_s
        bg = await view(s, behind)  # behind everything interactive, itself included
        assert bg.queue_position == 4
        assert 64 <= bg.eta_s <= 66, bg.eta_s  # (20 + 10 + 10 + 30) / 2 + 30
