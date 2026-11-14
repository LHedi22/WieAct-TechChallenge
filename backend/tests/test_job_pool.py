"""Audit OPT-34 (found by the 30-student class load test, 14 Nov): creating a job read the
offline switches through a SECOND database session while the request's session already held a
connection. When the flags cache expired under a burst, every request waited for a second
connection with its first one held: 30 students exhausted the pool (5 + 10) and got 500s after
30 s. Job creation and prefetch planning now read them through the caller's session."""

import uuid

import pytest
from sqlalchemy import select

from app.core import db, flags
from app.jobs import demo, prefetch
from app.jobs import service as jobs_service
from app.jobs.service import create_job, create_or_join_shared_job
from app.models import Chapter, User


def no_second_session():
    raise AssertionError("a second session was opened while the caller holds one")


@pytest.fixture
def one_session_only(monkeypatch):
    flags.invalidate()  # a cache miss: the switches must be read now
    monkeypatch.setattr(jobs_service, "get_sessionmaker", no_second_session, raising=False)
    monkeypatch.setattr(prefetch, "get_sessionmaker", no_second_session, raising=False)
    monkeypatch.setattr(db, "get_sessionmaker", no_second_session)


async def test_creating_a_job_reads_the_switches_through_the_callers_session(sm, one_session_only):
    async with sm() as s:
        await create_job(s, kind=demo.KIND, lane="interactive")
        await create_or_join_shared_job(s, kind=demo.KIND, share_key="P:1", lane="background")


async def test_prefetch_planning_too(sm, one_session_only):
    async with sm() as s:
        user = User(nickname=f"pool{uuid.uuid4().hex[:6]}", password_hash="x", ui_language="en")
        s.add(user)
        await s.flush()
        chapter = Chapter(id=uuid.uuid4(), course_id=uuid.uuid4(), idx=1, title="t")
        assert await prefetch.plan_next(s, user, chapter, "beginner") == []
        assert await s.scalar(select(User.id).where(User.id == user.id))
