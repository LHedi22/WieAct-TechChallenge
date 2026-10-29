"""Socratic Tutor: plan (one call), turns as jobs, hints max 3, escalation to mid after 2 "stuck",
compact fallback when mid is saturated, the answer-leak guard, and the session summary."""

import asyncio

from sqlalchemy import func, select

from app.features.tutor.service import leaks_answer
from app.jobs.worker import Worker
from app.models import AICallLog
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, make_world, pptx  # noqa: F401  (fixtures)


async def tutor_calls(sm, kind="TUTOR_TURN", tier=None) -> int:
    async with sm() as s:
        q = select(func.count()).where(AICallLog.task_kind == kind, AICallLog.status_code == 200)
        if tier:
            q = q.where(AICallLog.model_tier == tier)
        return await s.scalar(q)


async def start(api, sm, chapter):  # noqa: F811
    r = await api.post(
        "/api/tutor/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]
    await Worker(sm).drain(timeout_s=30)
    return sid


async def say(api, sm, sid, text="", action="message"):  # noqa: F811
    r = await api.post(
        f"/api/tutor/{sid}/turn", json={"text": text, "action": action}, headers=OWL_FR
    )
    assert r.status_code == 200, r.text
    await Worker(sm).drain(timeout_s=30)
    return (await api.get(f"/api/tutor/{sid}", headers=OWL_FR)).json()


def test_leak_check():
    assert leaks_answer("The answer is 4.")
    assert leaks_answer("La réponse est 4.")
    assert leaks_answer("الجواب هو 4.")
    assert leaks_answer("Factor the top first.")  # no question back to the student
    assert not leaks_answer("What do you get if you factor the top?")
    assert not leaks_answer("ماذا تجد إذا بسّطت؟")


async def test_plan_gives_goal_three_ideas_and_a_question_in_one_call(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    s = (await api.get(f"/api/tutor/{sid}", headers=OWL_FR)).json()
    assert s["goal"] and len(s["ideas"]) == 3 and not any(i["found"] for i in s["ideas"])
    assert s["turns"][0]["role"] == "tutor" and s["turns"][0]["text"].endswith("?")
    assert "ensemble" in s["turns"][0]["text"]  # French, the student's language
    assert s["pending_job_id"] is None and s["hints_used"] == 0 and s["max_hints"] == 3
    assert await tutor_calls(sm) == 1


async def test_turns_ideas_and_hint_limit(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    s = await say(api, sm, sid, "on empile les assiettes ?")
    assert [t["role"] for t in s["turns"]] == ["tutor", "student", "tutor"]
    assert s["ideas"][0]["found"] and s["turns"][-1]["tier"] == "compact"
    for n in range(1, 4):
        s = await say(api, sm, sid, action="hint")
        assert s["hints_used"] == n
    r = await api.post(f"/api/tutor/{sid}/turn", json={"action": "hint"}, headers=OWL_FR)
    assert r.status_code == 400 and r.json()["detail"] == "errors.tutor_no_hints"
    empty = await api.post(f"/api/tutor/{sid}/turn", json={"text": "  "}, headers=OWL_FR)
    assert empty.status_code == 400


async def test_one_turn_at_a_time(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    first = await api.post(f"/api/tutor/{sid}/turn", json={"text": "a"}, headers=OWL_FR)
    second = await api.post(f"/api/tutor/{sid}/turn", json={"text": "b"}, headers=OWL_FR)
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["detail"] == "errors.tutor_busy"


async def test_two_stuck_signals_escalate_to_mid(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    s = await say(api, sm, sid, action="stuck")
    assert s["turns"][-1]["tier"] == "compact"
    s = await say(api, sm, sid, action="stuck")
    assert s["turns"][-1]["tier"] == "mid" and not s["turns"][-1]["quick_mode"]
    async with sm() as db_s:
        row = await db_s.scalar(
            select(AICallLog).where(AICallLog.model_tier == "mid").order_by(AICallLog.id.desc())
        )
    assert row.task_kind == "TUTOR_TURN" and row.pattern == "escalation"
    s = await say(api, sm, sid, "je vois")
    assert s["turns"][-1]["tier"] == "compact"  # back to compact after the mid turn


async def test_mid_saturated_falls_back_to_compact_quick_mode(api, sm, pptx, gw, mock_llm):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    mock_llm.state.cfg = mock_llm.state.cfg.model_copy(update={"p_503_mid": 1.0})
    gw._sleep = lambda _: asyncio.sleep(0)
    await say(api, sm, sid, action="stuck")
    s = await say(api, sm, sid, action="stuck")
    last = s["turns"][-1]
    assert last["tier"] == "compact" and last["quick_mode"] is True


async def test_leaked_answer_is_rewritten_as_a_question(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    s = await say(api, sm, sid, "leak: dis-moi juste la réponse")
    reply = s["turns"][-1]["text"]
    assert "La réponse est" not in reply and reply.endswith("?")
    assert await tutor_calls(sm, "TUTOR_GUARD") == 1


async def test_end_writes_a_summary_and_closes(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    await say(api, sm, sid, "on empile")
    r = await api.post(f"/api/tutor/{sid}/end", headers=OWL_FR)
    assert r.status_code == 200
    await Worker(sm).drain(timeout_s=30)
    s = (await api.get(f"/api/tutor/{sid}", headers=OWL_FR)).json()
    assert s["status"] == "ended" and s["summary"]["summary"] and s["summary"]["next_step"]
    assert len(s["summary"]["ideas_found"]) == 1 and len(s["summary"]["ideas_missing"]) == 2
    after = await api.post(f"/api/tutor/{sid}/turn", json={"text": "x"}, headers=OWL_FR)
    assert after.status_code == 409


async def test_sessions_are_personal(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    sid = await start(api, sm, chapter)
    assert (await api.get(f"/api/tutor/{sid}", headers=SEA)).status_code == 404
    other = await api.post(
        "/api/tutor/start",
        json={"chapter_id": chapter, "level": "beginner"},
        headers={"X-Dev-User": "Stranger9"},
    )
    assert other.status_code == 404
