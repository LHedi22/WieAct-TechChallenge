"""F-CACHE-1 (audit 2026-11-02): every brand-new student sent a byte-identical DAILY_PLAN *mid*
request (30 of the 37 repeated identical requests measured on the mock), because the cache key held
the user id although the prompt doesn't. The plan is now cached on the full rendered prompt (with
provider, model, task kind and prompt version, which the gateway adds to every key): identical
prompts share one answer, any personal difference (mistakes, goal, style, language) gets its own."""

import uuid

from sqlalchemy import func, select

import app.gateway as gateway_module
from app.jobs.worker import Worker
from app.models import AICallLog, Mistake, User
from tests.test_quiz import indexed, join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user, pptx  # noqa: F401  (fixtures)

OWL_FR = as_user("NightOwl7", "fr")
GULL_FR = as_user("SeaGull3", "fr")
CRAB_FR = as_user("RedCrab9", "fr")


async def plan_calls(sm) -> tuple[int, int]:
    """(model calls, cache hits) for DAILY_PLAN."""
    async with sm() as s:
        base = select(func.count()).select_from(AICallLog)
        calls = await s.scalar(
            base.where(AICallLog.task_kind == "DAILY_PLAN", AICallLog.cache_hit.is_(False))
        )
        hits = await s.scalar(
            base.where(AICallLog.task_kind == "DAILY_PLAN", AICallLog.cache_hit.is_(True))
        )
    return calls, hits


async def test_identical_new_students_share_one_plan_call(api, sm, pptx, monkeypatch):  # noqa: F811
    world, _ = await indexed(api, sm, pptx)  # NightOwl7 joined
    await join(api, world, GULL_FR)
    prompts: list[str] = []
    real_run = gateway_module.run

    async def spy(task):
        if task.kind == "DAILY_PLAN":
            prompts.append("\n".join(m["content"] for m in task.messages))
        return await real_run(task)

    monkeypatch.setattr(gateway_module, "run", spy)
    for who in (OWL_FR, GULL_FR):
        await api.get("/api/daily", headers=who)
        await Worker(sm).drain(timeout_s=30)

    assert await plan_calls(sm) == (1, 1)  # the second identical prompt is a cache hit
    # ...and the prompt carries no identity: no nickname, no user id
    async with sm() as s:
        users = list(await s.scalars(select(User)))
    assert len(prompts) == 2 and prompts[0] == prompts[1]
    for u in users:
        assert u.nickname not in prompts[0] and str(u.id) not in prompts[0]
    for who in (OWL_FR, GULL_FR):
        plan = (await api.get("/api/daily", headers=who)).json()
        assert plan["planned_by"] == "ai"


async def test_a_personal_difference_gets_its_own_plan(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    await join(api, world, CRAB_FR)
    await api.get("/api/daily", headers=CRAB_FR)  # creates RedCrab9's account row
    async with sm() as s:  # RedCrab9 has a recent mistake; NightOwl7 has none
        crab = await s.scalar(select(User).where(User.nickname == "RedCrab9"))
        s.add(
            Mistake(
                user_id=crab.id,
                world_id=uuid.UUID(world["id"]),
                chapter_id=uuid.UUID(chapter),
                concept="LIFO",
                mistake_type="confusion",
            )
        )
        await s.commit()
    await api.get("/api/daily", headers=OWL_FR)
    await Worker(sm).drain(timeout_s=30)
    assert await plan_calls(sm) == (2, 0)
