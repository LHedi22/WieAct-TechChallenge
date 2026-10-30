"""Class Wisdom: distinct students per (world, concept, mistake_type); at WISDOM_THRESHOLD ONE mid
call writes the tip in every language of the world; later students only raise the count."""

import json

from sqlalchemy import func, select

from app import gateway
from app.core import economy
from app.jobs.worker import Worker
from app.models import AICallLog, Job, Mistake, WisdomTip
from tests.test_map import join
from tests.test_quiz import answers_of, calls, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user, pptx  # noqa: F401  (fixtures)

STUDENTS = [as_user(n, "fr") for n in ("Mouette1", "Mouette2", "Mouette3", "Mouette4")]


async def miss_first_question(api, sm, headers, chapter):  # noqa: F811
    """Start the class quiz, answer question 0 wrong twice, the rest right, finish."""
    body = {"chapter_id": chapter, "level": "intermediate"}
    aid = (await api.post("/api/quiz/start", json=body, headers=headers)).json()["attempt_id"]
    right = await answers_of(sm)
    for _ in range(2):
        await api.post(
            f"/api/quiz/attempts/{aid}/answer",
            json={"q": 0, "choice": (right[0] + 1) % 4},
            headers=headers,
        )
    for i in range(1, 10):
        await api.post(
            f"/api/quiz/attempts/{aid}/answer", json={"q": i, "choice": right[i]}, headers=headers
        )
    await api.post(f"/api/quiz/attempts/{aid}/finish", headers=headers)
    await Worker(sm).drain(timeout_s=30)


async def tip_jobs(sm) -> int:
    async with sm() as s:
        return await s.scalar(select(func.count()).where(Job.kind == "WISDOM_TIP"))


async def test_three_students_same_mistake_make_one_tip_in_every_language(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    ar = as_user("Gazelle5", "ar")
    await join(api, world, ar)  # an Arabic-speaking classmate: the tip comes in ar too
    for h in STUDENTS[:3]:
        await join(api, world, h)

    await miss_first_question(api, sm, STUDENTS[0], chapter)
    await miss_first_question(api, sm, STUDENTS[1], chapter)
    assert await tip_jobs(sm) == 0
    async with sm() as s:
        concepts = set(await s.scalars(select(Mistake.concept)))
    assert len(concepts) == 1  # the shared question's concept, same text for everyone

    await miss_first_question(api, sm, STUDENTS[2], chapter)  # the threshold student
    assert economy.WISDOM_THRESHOLD == 3
    assert await tip_jobs(sm) == 1
    assert await calls(sm, "WISDOM_TIP") == 1  # one call for both languages
    async with sm() as s:
        tips = list(await s.scalars(select(WisdomTip).order_by(WisdomTip.language)))
        log = await s.scalar(select(AICallLog).where(AICallLog.task_kind == "WISDOM_TIP"))
    assert [t.language for t in tips] == ["ar", "fr"]
    assert all(t.student_count == 3 and t.text["trap"] and t.text["right"] for t in tips)
    assert log.model_tier == "mid"

    fr = await api.get("/api/wisdom", params={"world_id": world["id"]}, headers=STUDENTS[0])
    got = fr.json()["tips"]
    assert len(got) == 1 and got[0]["language"] == "fr" and got[0]["student_count"] == 3
    got_ar = (await api.get("/api/wisdom", params={"world_id": world["id"]}, headers=ar)).json()
    assert got_ar["tips"][0]["language"] == "ar"

    # A 4th student only raises the count: no new job, no new call.
    await join(api, world, STUDENTS[3])
    await miss_first_question(api, sm, STUDENTS[3], chapter)
    assert await tip_jobs(sm) == 1 and await calls(sm, "WISDOM_TIP") == 1
    again = await api.get("/api/wisdom", params={"world_id": world["id"]}, headers=STUDENTS[0])
    assert again.json()["tips"][0]["student_count"] == 4


async def test_tip_prompt_carries_no_nicknames(api, sm, pptx, gw, monkeypatch):  # noqa: F811
    seen = []

    async def spy(task):
        seen.append(task)
        return await gw.run(task)

    monkeypatch.setattr(gateway, "run", spy)
    world, chapter = await indexed(api, sm, pptx)
    for h in STUDENTS[:3]:
        await join(api, world, h)
        await miss_first_question(api, sm, h, chapter)
    tip = [t for t in seen if t.kind == "WISDOM_TIP"]
    assert len(tip) == 1 and tip[0].lane == "background"
    text = json.dumps(tip[0].messages, ensure_ascii=False)
    assert "Mouette" not in text and "SeaTurtle" not in text


async def test_wisdom_is_members_only(api, sm, pptx):  # noqa: F811
    world, _ = await indexed(api, sm, pptx)
    r = await api.get("/api/wisdom", params={"world_id": world["id"]}, headers=as_user("Stranger9"))
    assert r.status_code == 404
