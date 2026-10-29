"""Quiz Hall: shared sets (free when unseen), generation as a job when all are seen, answers graded
on the server (hint → second try → reveal), points, mastery, and one tagging call per attempt."""

import json

from sqlalchemy import func, select

from app.core import economy
from app.jobs.worker import Worker
from app.models import AICallLog, ChapterMastery, Mistake, QuizSet
from tests.test_map import join
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import OWL, SEA, api, make_world, pptx  # noqa: F401  (fixtures)

OWL_FR = OWL | {"X-UI-Language": "fr"}  # same language as the precomputed set


async def indexed(api, sm, pptx):  # noqa: F811
    world = await make_world(api)
    await join(api, world, OWL_FR)
    chapter = world["course"]["chapters"][0]["id"]
    await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    await Worker(sm).drain(timeout_s=60)  # indexing + the precomputed set (seed 1)
    return world, chapter


async def calls(sm, kind: str) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).where(AICallLog.task_kind == kind, AICallLog.status_code == 200)
        )


async def answers_of(sm, attempt_set_id=None) -> list[int]:
    async with sm() as s:
        qs = await s.scalar(select(QuizSet).order_by(QuizSet.seed.desc()))
        return [q["answer_index"] for q in qs.questions]


async def test_unseen_shared_set_is_free_and_needs_no_ai_call(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    before = await calls(sm, "QUIZ_GENERATE")
    price = (
        await api.get(
            "/api/quiz/price",
            params={"chapter_id": chapter, "level": "intermediate"},
            headers=OWL_FR,
        )
    ).json()
    assert price == {"cost": 0, "cached": True}
    r = await api.post(
        "/api/quiz/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
    )
    start = r.json()
    assert start["attempt_id"] and start["job_id"] is None and start["cost"] == 0
    attempt = (await api.get(f"/api/quiz/attempts/{start['attempt_id']}", headers=OWL_FR)).json()
    assert len(attempt["questions"]) == 10 and attempt["chapter_title"] == "Stacks"
    assert all(q["answer_index"] is None and q["hint"] is None for q in attempt["questions"])
    assert await calls(sm, "QUIZ_GENERATE") == before


async def test_all_seen_generates_a_new_set_as_a_job(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    body = {"chapter_id": chapter, "level": "intermediate"}
    await api.post("/api/quiz/start", json=body, headers=OWL_FR)  # uses seed 1
    price = (await api.get("/api/quiz/price", params=body, headers=OWL_FR)).json()
    assert price == {"cost": economy.COST["quiz"], "cached": False}
    start = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()
    assert start["job_id"] and start["attempt_id"] is None and start["cost"] == 5
    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "done" and "answer_index" not in json.dumps(job)
    assert job["stages"] == [
        "reading_chapter",
        "matching_level",
        "writing_questions",
        "writing_hints",
    ]
    attempt = (
        await api.post(f"/api/quiz/attempts/from-job/{start['job_id']}", headers=OWL_FR)
    ).json()
    assert len(attempt["questions"]) == 10
    async with sm() as s:
        seeds = sorted(q.seed for q in await s.scalars(select(QuizSet)))
    assert seeds == [1, 2]


async def test_hint_second_try_reveal_skip_points_and_results(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    start = (
        await api.post(
            "/api/quiz/start", json={"chapter_id": chapter, "level": "intermediate"}, headers=OWL_FR
        )
    ).json()
    aid = start["attempt_id"]
    right = await answers_of(sm)
    wrong = [(a + 1) % 4 for a in right]

    def post(path, body):
        return api.post(f"/api/quiz/attempts/{aid}/{path}", json=body, headers=OWL_FR)

    q0 = (await post("answer", {"q": 0, "choice": right[0]})).json()
    assert q0["status"] == "correct" and q0["answer_index"] == right[0] and q0["explanation"]
    q1 = (await post("answer", {"q": 1, "choice": wrong[1]})).json()
    assert q1["status"] == "hint" and q1["hint"] and q1["answer_index"] is None  # no answer yet
    q1 = (await post("answer", {"q": 1, "choice": right[1]})).json()
    assert q1["status"] == "second" and q1["answer_index"] == right[1]
    await post("answer", {"q": 2, "choice": wrong[2]})
    q2 = (await post("answer", {"q": 2, "choice": wrong[2]})).json()
    assert q2["status"] == "wrong" and q2["answer_index"] == right[2]
    q3 = (await post("skip", {"q": 3})).json()
    assert q3["status"] == "skipped" and q3["answer_index"] == right[3]
    again = await post("answer", {"q": 0, "choice": right[0]})
    assert again.status_code == 409 and again.json()["detail"] == "errors.quiz_question_done"

    resumed = (await api.get(f"/api/quiz/attempts/{aid}", headers=OWL_FR)).json()  # save & exit
    assert resumed["current"] == 4 and resumed["points"] == 15

    for i in range(4, 10):
        await post("answer", {"q": i, "choice": right[i]})
    res = (await api.post(f"/api/quiz/attempts/{aid}/finish", headers=OWL_FR)).json()
    assert res["score"] == 8 and res["total"] == 10 and res["second_tries"] == 2
    assert res["points"] == 7 * 10 + 5
    assert [m["i"] for m in res["missed"]] == [1, 2, 3]
    assert res["missed"][1]["status"] == "wrong" and res["missed"][1]["explanation"]
    assert res["mastery"] == 80 and not res["weak"]
    assert res["next_step"]["kind"] == "quiz"  # 8/10: move on
    assert res["tag_job_id"]

    await Worker(sm).drain(timeout_s=30)
    async with sm() as s:
        tags = list(await s.scalars(select(Mistake).order_by(Mistake.question_idx)))
        mastery = await s.scalar(select(ChapterMastery.mastery))
    assert [t.question_idx for t in tags] == [1, 2, 3]
    assert {t.mistake_type for t in tags} <= set(
        ("misconception", "calculation", "misread", "definition", "procedure")
    )
    assert mastery == 80
    assert await calls(sm, "QUIZ_GRADE_TAG") == 1  # one call for all missed questions

    finished = await post("answer", {"q": 5, "choice": 0})
    assert finished.status_code == 409


async def test_struggling_points_to_the_tutor_and_mastery_blends(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    body = {"chapter_id": chapter, "level": "intermediate"}
    aid = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()["attempt_id"]
    res = (await api.post(f"/api/quiz/attempts/{aid}/finish", headers=OWL_FR)).json()  # all skipped
    assert res["score"] == 0 and res["weak"] and res["mastery"] == 0
    assert res["next_step"] == {
        "kind": "tutor",
        "chapter_id": chapter,
        "chapter_title": "Stacks",
        "level": "intermediate",
        "cost": economy.COST["tutor_session"],
    }


async def test_attempts_are_personal_and_members_only(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    body = {"chapter_id": chapter, "level": "intermediate"}
    aid = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()["attempt_id"]
    other = {"X-Dev-User": "Stranger9"}
    assert (await api.get(f"/api/quiz/attempts/{aid}", headers=SEA)).status_code == 404
    assert (await api.post("/api/quiz/start", json=body, headers=other)).status_code == 404
    bad = await api.post(
        "/api/quiz/start", json={"chapter_id": chapter, "level": "expert"}, headers=OWL_FR
    )
    assert bad.status_code == 400 and bad.json()["detail"] == "errors.level_invalid"


async def test_eval_script_writes_outputs_with_checks(api, sm, pptx, tmp_path):  # noqa: F811
    from app.evals.__main__ import quiz_eval
    from app.seed.__main__ import seed

    assert await seed(run=True) == 0
    assert await quiz_eval(["en", "fr", "ar"], 20, "OLIVE-7Q2", False, tmp_path) == 0
    for lang in ("en", "fr", "ar"):
        report = json.loads((tmp_path / f"mock-{lang}.json").read_text(encoding="utf-8"))
        assert report["count"] == 20 and report["calls"] == 2
        assert report["checks_passed"]["valid"] == 20
        assert report["checks_passed"]["language_script"] == 20
        assert report["questions"][0]["review"] == {"correct": None, "notes": ""}
