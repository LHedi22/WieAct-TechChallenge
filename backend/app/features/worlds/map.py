"""The world map, the island view and "on this island now" (presence)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import CurrentUser, Session
from app.core import economy
from app.features.worlds import service
from app.features.worlds.service import NotFound
from app.models import (
    Chapter,
    ChapterMastery,
    Course,
    CourseLevel,
    Document,
    Presence,
    Profile,
    User,
    World,
    WorldMember,
)

router = APIRouter(prefix="/api", tags=["map"])
PRESENCE_WINDOW = timedelta(minutes=2)


class Member(BaseModel):
    nickname: str
    avatar: dict | None
    is_me: bool


class MapCourse(BaseModel):
    id: uuid.UUID
    name: str
    color_key: str
    ready: bool  # has at least one indexed file: the island has risen
    chapters: int
    level: str | None  # my placement level; None = locked until the placement quiz
    mastery: int  # my average chapter mastery, 0-100


class MapOut(BaseModel):
    world_id: uuid.UUID
    name: str
    join_code: str
    creator: str
    is_creator: bool
    members: list[Member]
    courses: list[MapCourse]


class IslandChapter(BaseModel):
    id: uuid.UUID
    idx: int
    title: str
    ready: bool
    mastery: int | None  # None = not started
    weak: bool


class Building(BaseModel):
    key: str
    cost: int
    free_if_cached: bool = False
    answer_cost: int | None = None


class Visitor(BaseModel):
    nickname: str
    avatar: dict | None
    chapter: str | None


class IslandOut(BaseModel):
    id: uuid.UUID
    world_id: uuid.UUID
    name: str
    color_key: str
    level: str | None
    mastery: int
    chapters: list[IslandChapter]
    buildings: list[Building]
    visitors: list[Visitor]  # classmates on this island in the last 2 minutes (not me)


class PresenceIn(BaseModel):
    chapter_id: uuid.UUID | None = None


def _http(e: NotFound) -> HTTPException:
    return HTTPException(404, e.key)


async def _members(s, world: World, me: User) -> list[Member]:
    rows = await s.execute(
        select(User.id, User.nickname, Profile.avatar)
        .join(WorldMember, WorldMember.user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(WorldMember.world_id == world.id)
        .order_by(WorldMember.joined_at)
    )
    return [Member(nickname=n, avatar=a, is_me=uid == me.id) for uid, n, a in rows]


async def _mastery_by_course(s, user: User, course_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await s.execute(
        select(Chapter.course_id, func.coalesce(func.avg(ChapterMastery.mastery), 0))
        .join(ChapterMastery, ChapterMastery.chapter_id == Chapter.id)
        .where(ChapterMastery.user_id == user.id, Chapter.course_id.in_(course_ids))
        .group_by(Chapter.course_id)
    )
    return {cid: round(float(avg)) for cid, avg in rows}


async def course_for_member(s, user: User, course_id: uuid.UUID) -> Course:
    course = await s.get(Course, course_id)
    if course is None:
        raise NotFound("errors.world_not_found")
    await service.member_world(s, user, course.world_id)
    return course


@router.get("/worlds/{world_id}/map", response_model=MapOut)
async def world_map(world_id: uuid.UUID, s: Session, user: CurrentUser) -> MapOut:
    try:
        world = await service.member_world(s, user, world_id)
    except NotFound as e:
        raise _http(e) from e
    courses = list(
        await s.scalars(select(Course).where(Course.world_id == world.id).order_by(Course.name))
    )
    ids = [c.id for c in courses]
    chapters = dict(
        (
            await s.execute(
                select(Chapter.course_id, func.count())
                .where(Chapter.course_id.in_(ids))
                .group_by(Chapter.course_id)
            )
        ).all()
    )
    ready = set(
        await s.scalars(
            select(Chapter.course_id)
            .join(Document, Document.chapter_id == Chapter.id)
            .where(Chapter.course_id.in_(ids), Document.status == "ready")
            .distinct()
        )
    )
    levels = dict(
        (
            await s.execute(
                select(CourseLevel.course_id, CourseLevel.level).where(
                    CourseLevel.user_id == user.id, CourseLevel.course_id.in_(ids)
                )
            )
        ).all()
    )
    mastery = await _mastery_by_course(s, user, ids)
    creator = await s.get(User, world.creator_id)
    return MapOut(
        world_id=world.id,
        name=world.name,
        join_code=world.join_code,
        creator=creator.nickname if creator else "",
        is_creator=world.creator_id == user.id,
        members=await _members(s, world, user),
        courses=[
            MapCourse(
                id=c.id,
                name=c.name,
                color_key=c.color_key,
                ready=c.id in ready,
                chapters=chapters.get(c.id, 0),
                level=levels.get(c.id),
                mastery=mastery.get(c.id, 0),
            )
            for c in courses
        ],
    )


@router.get("/courses/{course_id}", response_model=IslandOut)
async def island(course_id: uuid.UUID, s: Session, user: CurrentUser) -> IslandOut:
    try:
        course = await course_for_member(s, user, course_id)
    except NotFound as e:
        raise _http(e) from e
    chapters = list(
        await s.scalars(select(Chapter).where(Chapter.course_id == course.id).order_by(Chapter.idx))
    )
    ch_ids = [c.id for c in chapters]
    ready = set(
        await s.scalars(
            select(Document.chapter_id).where(
                Document.chapter_id.in_(ch_ids), Document.status == "ready"
            )
        )
    )
    mine = {
        m.chapter_id: m
        for m in await s.scalars(
            select(ChapterMastery).where(
                ChapterMastery.user_id == user.id, ChapterMastery.chapter_id.in_(ch_ids)
            )
        )
    }
    level = await s.scalar(
        select(CourseLevel.level).where(
            CourseLevel.user_id == user.id, CourseLevel.course_id == course.id
        )
    )
    since = datetime.now(UTC) - PRESENCE_WINDOW
    visitors = await s.execute(
        select(User.nickname, Profile.avatar, Chapter.title)
        .join(Presence, Presence.user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
        .outerjoin(Chapter, Chapter.id == Presence.chapter_id)
        .where(Presence.course_id == course.id, Presence.seen_at >= since, User.id != user.id)
        .order_by(Presence.seen_at.desc())
        .limit(12)
    )
    known = [m.mastery for m in mine.values()]
    return IslandOut(
        id=course.id,
        world_id=course.world_id,
        name=course.name,
        color_key=course.color_key,
        level=level,
        mastery=round(sum(known) / len(known)) if known else 0,
        chapters=[
            IslandChapter(
                id=c.id,
                idx=c.idx,
                title=c.title,
                ready=c.id in ready,
                mastery=mine[c.id].mastery if c.id in mine else None,
                weak=mine[c.id].weak if c.id in mine else False,
            )
            for c in chapters
        ],
        buildings=[Building(key=k, **v) for k, v in economy.BUILDINGS.items()],
        visitors=[Visitor(nickname=n, avatar=a, chapter=t) for n, a, t in visitors],
    )


@router.post("/courses/{course_id}/presence", status_code=204)
async def presence(course_id: uuid.UUID, body: PresenceIn, s: Session, user: CurrentUser):
    """The island view calls this every 30 s while open."""
    try:
        course = await course_for_member(s, user, course_id)
    except NotFound as e:
        raise _http(e) from e
    chapter_id = body.chapter_id
    if chapter_id is not None:
        chapter = await s.get(Chapter, chapter_id)
        if chapter is None or chapter.course_id != course.id:
            chapter_id = None
    stmt = insert(Presence).values(
        user_id=user.id, course_id=course.id, chapter_id=chapter_id, seen_at=func.now()
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "course_id"],
            set_={"chapter_id": stmt.excluded.chapter_id, "seen_at": func.now()},
        )
    )
    await s.commit()
    return Response(status_code=204)
