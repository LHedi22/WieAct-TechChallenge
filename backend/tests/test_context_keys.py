"""Audit OPT-17: the quiz and placement ai_cache keys were course/chapter + level + language (+
seed) only, with no hash of the chapter text behind the prompt. After the material changed (an
admin edit, a re-upload) the old questions were replayed from ai_cache instead of being written
from the new text. The keys now carry a hash of the context sent to the model."""

from sqlalchemy import delete, update

from app.jobs.worker import Worker
from app.models import Chunk, PlacementSet, QuizAttempt, QuizSet
from tests.test_quiz import calls, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, pptx  # noqa: F401  (fixtures)


async def edit_material(sm, chapter):
    async with sm() as s:
        await s.execute(
            update(Chunk).where(Chunk.chapter_id == chapter).values(text=Chunk.text + " (revised)")
        )
        await s.commit()


async def test_edited_material_writes_a_new_placement_set(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    course = world["course"]["id"]
    await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "PLACEMENT_QUIZ") == 1
    await edit_material(sm, chapter)
    async with sm() as s:  # the class's set is dropped so it is written again
        await s.execute(delete(PlacementSet))
        await s.commit()
    await api.post("/api/placement/start", json={"course_id": course}, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "PLACEMENT_QUIZ") == 2  # a fresh call, not the old reply


async def test_edited_material_writes_a_new_quiz_set(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    body = {"chapter_id": chapter, "level": "advanced"}
    await api.post("/api/quiz/start", json=body, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    before = await calls(sm, "QUIZ_GENERATE")
    await edit_material(sm, chapter)
    async with sm() as s:  # same seed again for the same chapter + level + language
        await s.execute(delete(QuizAttempt))
        await s.execute(delete(QuizSet).where(QuizSet.level == "advanced"))
        await s.commit()
    await api.post("/api/quiz/start", json=body, headers=SEA)
    await Worker(sm).drain(timeout_s=60)
    assert await calls(sm, "QUIZ_GENERATE") == before + 1
