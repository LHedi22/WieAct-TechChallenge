"""Audit F-QUICK-1 (Tier 2 #9): when the mid model was saturated, the compact fallback's notes (and
audio scripts) became the class's permanent copy: every classmate got them, nobody could get the
mid version. Now a Quick-mode copy is marked; while it is, anyone in the class can make the full
version for free (it replaces the notes in place; cards and map, always compact-made, stay)."""

from sqlalchemy import select

from app.jobs.worker import Worker
from app.models import AICallLog, StudyAsset
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, pptx  # noqa: F401  (fixtures)

LEVEL = {"level": "intermediate"}


async def studio(api, chapter, headers):  # noqa: F811
    r = await api.get(f"/api/studio/{chapter}", params=LEVEL, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def notes_rows(sm, kind="notes"):
    async with sm() as s:
        return list(await s.scalars(select(StudyAsset).where(StudyAsset.kind == kind)))


async def mid_calls(sm, task: str) -> int:
    async with sm() as s:
        rows = await s.scalars(
            select(AICallLog).where(
                AICallLog.task_kind == task,
                AICallLog.model_tier == "mid",
                AICallLog.status_code == 200,
            )
        )
        return len(list(rows))


async def test_a_quick_mode_pack_is_marked_and_upgraded_for_free(api, sm, pptx, mock_llm):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    mock_llm.state.cfg.p_503_mid = 1.0  # the mid model is saturated
    start = (
        await api.post(
            f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=OWL_FR
        )
    ).json()
    await Worker(sm).drain(timeout_s=60)
    quick = await studio(api, chapter, SEA)  # a classmate opens it
    assert quick["notes"] and quick["quick_mode"] is True
    assert quick["cost"] == 0  # making the full version is free: the class already paid
    assert start["cost"] > 0

    mock_llm.state.cfg.p_503_mid = 0.0  # later, the mid model is free again
    up = (
        await api.post(f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=SEA)
    ).json()
    assert up["job_id"] and up["cost"] == 0
    await Worker(sm).drain(timeout_s=60)
    full = await studio(api, chapter, SEA)
    assert full["quick_mode"] is False and full["notes"]
    assert len(await notes_rows(sm)) == 1  # replaced in place, not a second copy
    assert await mid_calls(sm, "NOTES_WRITE") == 1  # the upgrade used the mid model


async def test_a_normal_pack_is_not_regenerated(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    await api.post(f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=OWL_FR)
    await Worker(sm).drain(timeout_s=60)
    s = await studio(api, chapter, SEA)
    assert s["quick_mode"] is False
    again = (
        await api.post(f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=SEA)
    ).json()
    assert again == {"job_id": None, "cost": 0, "cached": True}


async def test_a_quick_mode_audio_script_is_upgraded_for_free(api, sm, pptx, mock_llm):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    mock_llm.state.cfg.p_503_mid = 1.0
    await api.post(f"/api/audio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=OWL_FR)
    await Worker(sm).drain(timeout_s=60)
    quick = (await api.get(f"/api/audio/{chapter}", params=LEVEL, headers=SEA)).json()
    assert quick["script"] and quick["quick_mode"] is True and quick["cost"] == 0

    mock_llm.state.cfg.p_503_mid = 0.0
    up = (
        await api.post(f"/api/audio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=SEA)
    ).json()
    assert up["job_id"] and up["cost"] == 0
    await Worker(sm).drain(timeout_s=60)
    full = (await api.get(f"/api/audio/{chapter}", params=LEVEL, headers=SEA)).json()
    assert full["quick_mode"] is False
    assert len(await notes_rows(sm, "audio_script")) == 1
