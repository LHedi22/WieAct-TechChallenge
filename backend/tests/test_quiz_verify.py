"""Audit N-3 (5 Nov, local models): at most 1 of 15 generated quiz items had a correct answer key
("A queue is last-in-first-out (FIFO)" marked correct, lim x^3 at 2 keyed as 2…), and no automatic
check tested correctness.

Now a separate step (QUIZ_VERIFY, mid, draft-then-revise) solves every question without seeing
the key before a set is published: items the solver doesn't confirm are dropped, and a set left
with too few items is regenerated once. Verification unavailable: a student's quiz is published
marked unverified and never shared with classmates; background work waits for mid instead.
Fixture items with known right and wrong keys (quiz_key_set.json) make the checks test
correctness."""

import json

import pytest
from sqlalchemy import select

import app.gateway as gateway_module
from app import prompts
from app.evals import quiz_keys
from app.features.quiz import verify
from app.gateway import Defer, Result, TaskKind
from app.jobs.worker import Worker
from app.models import QuizSet
from tests.test_map import join
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, make_world, pptx  # noqa: F401  (fixtures)

FIX = quiz_keys.load()
ITEMS = FIX["items"]
BODY = {"level": "intermediate"}


def truthful_solver(items):
    """What a correct solver answers: the real answer of each item (1-based), sure."""
    return {
        "answers": [
            {"n": i + 1, "answer": None if it["true_index"] is None else it["true_index"] + 1,
             "sure": True}
            for i, it in enumerate(items)
        ]
    }  # fmt: skip


def test_the_fixtures_hold_known_right_and_wrong_keys():
    keys = {(it["lang"], it["key"]) for it in ITEMS}
    assert {(lang, k) for lang in ("en", "fr", "ar", "ar-TN") for k in ("right", "wrong")} <= keys
    queue = [it for it in ITEMS if "last-in-first-out (FIFO)" in json.dumps(it["question"])]
    assert queue and queue[0]["key"] == "wrong"
    for it in ITEMS:  # the label agrees with the facts
        q = it["question"]
        assert (q["answer_index"] == it["true_index"]) == (it["key"] == "right")


def test_the_verifier_never_sees_the_key_hint_or_explanation():
    qs = [dict(it["question"], hint="HINT-X", explanation="EXPL-Y") for it in ITEMS[:3]]
    _, messages = verify.render(qs, context=FIX["context"], course="c", chapter="ch", language="en")
    text = json.dumps(messages, ensure_ascii=False)
    assert "answer_index" not in text and "HINT-X" not in text and "EXPL-Y" not in text
    for q in qs:  # all four options are shown, in order, none marked
        assert all(o in text for o in q["options"])


def test_only_confirmed_items_survive():
    qs = [it["question"] for it in ITEMS]
    verdicts = verify.verdicts(truthful_solver(ITEMS), qs)
    kept = verify.keep_verified(qs, verdicts)
    assert len(kept) == sum(it["key"] == "right" for it in ITEMS)
    assert all(q["verified"] is True for q in kept)
    assert not any("last-in-first-out (FIFO)" in json.dumps(q) for q in kept)


def test_unsure_null_or_missing_answers_are_not_verified():
    qs = [ITEMS[0]["question"], ITEMS[2]["question"], ITEMS[4]["question"]]
    reply = {"answers": [{"n": 1, "answer": 2, "sure": False}, {"n": 2, "answer": None}]}
    assert verify.verdicts(reply, qs) == [False, False, False]
    assert verify.verdicts("not json", qs) is None


@pytest.fixture
def scripted(gw, monkeypatch):  # noqa: F811
    """QUIZ_GENERATE returns the fixture items (5 right + 5 wrong keys); QUIZ_VERIFY answers like
    a correct solver, or raises what the test queues."""
    script = {"verify": [], "calls": []}
    right = [it for it in ITEMS if it["lang"] == "en"] * 2  # 6 en items, 3 wrong
    pack = (right + ITEMS)[:10]

    async def run(task):
        if task.kind == TaskKind.QUIZ_GENERATE:
            script["calls"].append("generate")
            content = {
                "questions": [dict(it["question"], hint="h", explanation="e") for it in pack]
            }
            return Result(content=content, model_tier="compact", model="x", provider="mock",
                          pattern="t")  # fmt: skip
        if task.kind == TaskKind.QUIZ_VERIFY:
            script["calls"].append(f"verify:{task.lane}:{task.tier}")
            item = script["verify"].pop(0) if script["verify"] else truthful_solver(pack)
            if isinstance(item, Exception):
                raise item
            return Result(content=item, model_tier="mid", model="x", provider="mock", pattern="t")
        return await gw.run(task)

    monkeypatch.setattr(gateway_module, "run", run)
    script["pack"] = pack
    return script


async def new_set(api, sm, chapter, who=OWL_FR):  # noqa: F811
    """Finish whatever is open, then start a quiz that needs a new set; returns the job json."""
    body = {"chapter_id": chapter, **BODY}
    first = (await api.post("/api/quiz/start", json=body, headers=who)).json()
    if first.get("attempt_id"):
        await api.post(f"/api/quiz/attempts/{first['attempt_id']}/finish", headers=who)
        first = (await api.post("/api/quiz/start", json=body, headers=who)).json()
    await Worker(sm).drain(timeout_s=60)
    return (await api.get(f"/api/jobs/{first['job_id']}", headers=who)).json()


async def test_wrong_keys_never_reach_students(api, sm, pptx, scripted):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    job = await new_set(api, sm, chapter)
    assert job["status"] == "done"
    async with sm() as s:
        sets = list(await s.scalars(select(QuizSet).order_by(QuizSet.seed)))
    for qs in sets:  # the precomputed set too
        assert all(q.get("verified") is True for q in qs.questions)
        assert not any("last-in-first-out (FIFO)" in q["options"][q["answer_index"]]
                       for q in qs.questions)  # fmt: skip
    wrong = sum(it["key"] == "wrong" for it in scripted["pack"])
    assert len(sets[-1].questions) == 10 - wrong or "generate" in scripted["calls"][-2:]


async def test_too_few_survivors_regenerate_once_then_fail(api, sm, pptx, scripted):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    calls_before = len(scripted["calls"])
    nobody_right = {"answers": [{"n": i + 1, "answer": None, "sure": True} for i in range(10)]}
    scripted["verify"] += [nobody_right, nobody_right]
    job = await new_set(api, sm, chapter)
    assert job["status"] == "failed"  # coins come back (refund on failure)
    new_calls = scripted["calls"][calls_before:]
    assert new_calls.count("generate") == 2 and len(new_calls) == 4  # one regeneration only


async def test_mid_unavailable_publishes_unverified_and_never_shares_it(api, sm, pptx, scripted):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    scripted["verify"].append(Defer(30, "saturated"))
    job = await new_set(api, sm, chapter)
    assert job["status"] == "done"
    attempt = (await api.post(f"/api/quiz/attempts/from-job/{job['id']}", headers=OWL_FR)).json()
    assert attempt["verified"] is False  # the UI says the answers aren't double-checked
    async with sm() as s:
        newest = await s.scalar(select(QuizSet).order_by(QuizSet.seed.desc()))
    assert all(q["verified"] is False for q in newest.questions)
    # a classmate never gets the unverified set: their start doesn't hand it out
    await join(api, world, SEA)
    other = (await api.post(
        "/api/quiz/start", json={"chapter_id": chapter, **BODY}, headers=SEA
    )).json()  # fmt: skip
    if other.get("attempt_id"):
        seen = (await api.get(f"/api/quiz/attempts/{other['attempt_id']}", headers=SEA)).json()
        assert seen["verified"] is True


async def test_background_pool_waits_for_mid_instead(api, sm, pptx, scripted):  # noqa: F811
    scripted["verify"] += [Defer(3600, "saturated")] * 3
    world = await make_world(api)
    chapter = world["course"]["chapters"][0]["id"]
    await api.post(
        f"/api/chapters/{chapter}/documents",
        files={"file": (pptx.name, pptx.read_bytes())},
        headers=SEA,
    )
    await Worker(sm).drain(timeout_s=60)
    async with sm() as s:
        assert await s.scalar(select(QuizSet)) is None  # nothing published unverified


async def test_full_path_on_the_mock_marks_items_verified(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    async with sm() as s:
        qs = await s.scalar(select(QuizSet))
    assert qs is not None and all(q["verified"] is True for q in qs.questions)


def test_quiz_verify_prompt_is_versioned():
    assert prompts.render("quiz_verify", context="x", course="c", chapter="ch", language="fr",
                          questions="1. q")[0]  # fmt: skip
