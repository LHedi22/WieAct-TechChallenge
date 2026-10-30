"""Seed the demo world (synthetic CC0 material from app/seed/samples.py) through the real pipeline.

    uv run python -m app.seed          # queue the uploads; the worker indexes them
    uv run python -m app.seed --run    # also index them here (no worker running)

Then 3 synthetic classmates share one quiz mistake, so a Class Wisdom tip is ready (once the
class quiz set exists: re-run after indexing if the worker was still busy).

Idempotent: re-running reuses the world (code OLIVE-7Q2) and skips files already uploaded."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings

DEMO_CODE = "OLIVE-7Q2"
DEMO_NICKNAME = "demo"
COURSES = [
    ("Calculus I", ["Limits and derivatives", "Integrals"]),
    ("Data Structures", ["Stacks and queues"]),
]
FILES = [  # (course, chapter idx, sample key)
    ("Calculus I", 1, "pdf"),
    ("Calculus I", 1, "docx"),
    ("Calculus I", 2, "png"),
    ("Data Structures", 1, "pptx"),
]


async def _stream(path: Path):
    data = await asyncio.to_thread(path.read_bytes)
    yield data


async def seed(run: bool) -> int:
    from app.api.deps import UNUSABLE_PASSWORD
    from app.core import db
    from app.features.worlds import service
    from app.models import Chapter, Course, Document, User, World, WorldMember
    from app.seed import samples

    files = samples.make_all(Path(get_settings().UPLOAD_DIR) / "_samples")
    sm = db.get_sessionmaker()
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == DEMO_NICKNAME))
        if user is None:
            user = User(nickname=DEMO_NICKNAME, password_hash=UNUSABLE_PASSWORD, ui_language="en")
            s.add(user)
            await s.commit()
        world = await s.scalar(select(World).where(World.join_code == DEMO_CODE))
        if world is None:
            world = World(name="Engineering 2B (demo)", join_code=DEMO_CODE, creator_id=user.id)
            s.add(world)
            await s.flush()
            s.add(WorldMember(world_id=world.id, user_id=user.id))
            await s.commit()
        courses = {
            c.name: c for c in await s.scalars(select(Course).where(Course.world_id == world.id))
        }
        for name, chapters in COURSES:
            if name not in courses:
                courses[name] = await service.add_course(s, world, name, chapters)
        queued = 0
        for course_name, idx, key in FILES:
            chapter = await s.scalar(
                select(Chapter).where(
                    Chapter.course_id == courses[course_name].id, Chapter.idx == idx
                )
            )
            path = files[key]
            exists = await s.scalar(
                select(Document.id).where(
                    Document.chapter_id == chapter.id, Document.filename == path.name
                )
            )
            if exists:
                continue
            _, job_id, _ = await service.store_upload(s, user, chapter, path.name, _stream(path))
            queued += job_id is not None
    print(f"World {DEMO_CODE} ({world.id}): {queued} files queued for indexing")
    from app.seed.wisdom import STUDENTS, seed_wisdom

    if run:
        from app.jobs.worker import Worker

        await Worker(sm).drain(timeout_s=900)
        print("Indexing finished")
    tips = await seed_wisdom(sm, DEMO_CODE)
    if run and tips:
        await Worker(sm).drain(timeout_s=300)
    print(f"Class Wisdom: {', '.join(STUDENTS)} share one mistake; {len(tips)} tip job(s) queued")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="python -m app.seed")
    p.add_argument("--run", action="store_true", help="index here instead of waiting for a worker")
    return asyncio.run(seed(p.parse_args(argv).run))


if __name__ == "__main__":
    raise SystemExit(main())
