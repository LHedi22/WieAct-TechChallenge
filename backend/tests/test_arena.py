"""Teach-Back Arena: moderation on ask (refund on reject), answers graded draft-then-revise (mid
only in the review band or when unsure; mid busy → the draft stands), rewards once, pins, votes,
permissions, solo mode, and the full path against the in-process mock."""

import pytest
from sqlalchemy import func, select

import app.gateway as gateway_module
from app.core import economy
from app.core.config import get_settings
from app.features.arena.service import CRITERIA, Grade, needs_review, parse_grade
from app.gateway import Defer, Result, TaskKind
from app.jobs.worker import Worker
from app.models import AICallLog
from tests.test_map import join
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, make_world, pptx  # noqa: F401  (fixtures)

GOOD = "A stack keeps the most recent action on top, so undo just pops it: last in, first out."


def levels_for(score):
    """Rubric levels (audit N-2) whose server total is `score` (a multiple of 10)."""
    left, out = score // 10, {}
    for name, top in CRITERIA.items():
        out[name] = {"level": min(top, left)}
        left -= out[name]["level"]
    return out


def g(score, confidence="high", flag="ok", evidence="A stack keeps"):
    """A scripted grade reply; every level's evidence must be in the answer (audit N-1)."""
    return {
        "flag": flag,
        "criteria": {k: {**v, "evidence": evidence} for k, v in levels_for(score).items()},
        "confidence": confidence,
        "errors": [{"quote": "A stack keeps", "fix": "Say which end."}] if score < 85 else [],
        "good": "You linked undo to the order of actions.",
        "missing": ["LIFO"],
    }


@pytest.fixture
def grades(gw, monkeypatch):  # noqa: F811
    """Scripted TEACHBACK_GRADE replies per tier (a dict, or an exception to raise)."""
    script: dict[str, list] = {"compact": [], "mid": []}
    script["calls"] = []

    async def run(task):
        if task.kind != TaskKind.TEACHBACK_GRADE:
            return await gw.run(task)
        tier = task.tier or "compact"
        script["calls"].append(tier)
        item = script[tier].pop(0)
        if isinstance(item, Exception):
            raise item
        return Result(content=item, model_tier=tier, model="x", provider="mock", pattern="t")

    monkeypatch.setattr(gateway_module, "run", run)
    return script


async def room(api, sm, pptx):  # noqa: F811
    """A world with an indexed chapter; NightOwl7 (fr) asks, SeaTurtle42 answers."""
    _, chapter = await indexed(api, sm, pptx)
    r = await api.post(
        "/api/arena/questions",
        json={"chapter_id": chapter, "text": "Why does a stack make undo easy?"},
        headers=OWL_FR,
    )
    assert r.status_code == 202, r.text
    assert r.json()["cost"] == economy.COST["peer_question"]
    await Worker(sm).drain(timeout_s=30)
    return chapter, r.json()["question_id"]


async def send(api, sm, qid, text=GOOD, who=SEA):  # noqa: F811
    r = await api.post(f"/api/arena/questions/{qid}/answers", json={"text": text}, headers=who)
    assert r.status_code == 202, r.text
    await Worker(sm).drain(timeout_s=30)
    return (await api.get(f"/api/arena/questions/{qid}", headers=who)).json()


async def wallet(api, who):  # noqa: F811
    return (await api.get("/api/wallet", headers=who)).json()


# --- units ---------------------------------------------------------------------------------------
def test_review_when_unsure_high_or_near_the_threshold():
    t, band = economy.PEER_ANSWER_THRESHOLD, economy.TEACHBACK_REVIEW_BAND
    high = get_settings().TEACHBACK_REVIEW_HIGH_SCORE
    assert needs_review(Grade(score=high, confidence="high"), peer=False)  # audit N-1
    assert not needs_review(Grade(score=t - band - 10, confidence="medium"), peer=True)
    assert needs_review(Grade(score=t + band, confidence="high"), peer=True)
    assert needs_review(Grade(score=20, confidence="low"), peer=True)
    assert not needs_review(Grade(score=t, confidence="high"), peer=False)  # solo: no coins
    assert needs_review(Grade(score=t, confidence="low"), peer=False)
    assert not needs_review(Grade(score=t, confidence="low", flag="abusive"), peer=True)


def test_parse_grade_is_tolerant():
    out = parse_grade(
        {"criteria": levels_for(90), "confidence": "sure", "flag": "?", "errors": ["x", {}]}
    )
    assert (out.score, out.confidence, out.flag, len(out.errors)) == (90, "medium", "ok", 1)
    assert parse_grade({"criteria": {"accuracy": {"level": 40}}}).score == 40  # clamped to 4
    assert parse_grade("not json") is None and parse_grade({"good": "no rubric"}) is None


# --- peer room -----------------------------------------------------------------------------------
async def test_ask_answer_pin_and_rewards(api, sm, pptx, grades):  # noqa: F811
    chapter, qid = await room(api, sm, pptx)
    assert (await wallet(api, OWL_FR))["coins"] == economy.DAILY_FREE_COINS - 2
    feed = await api.get("/api/arena/questions", params={"chapter_id": chapter}, headers=SEA)
    (item,) = feed.json()["questions"]
    assert item["status"] == "open" and item["author"]["nickname"] == "NightOwl7"

    grades["compact"].append(g(90))
    grades["mid"].append(g(90))  # a high draft pays only after mid confirms it (audit N-1)
    d = await send(api, sm, qid)
    mine = d["my_answer"]
    assert mine["status"] == "graded" and mine["score"] == 90 and mine["feedback"]["good"]
    assert grades["calls"] == ["compact", "mid"]
    w = await wallet(api, SEA)
    assert w["earned"] == economy.EARN["peer_answer_good"]
    assert w["points"] == economy.POINTS["peer_answer_good"]

    # the asker sees the answer (score, no private feedback) and pins it
    seen = (await api.get(f"/api/arena/questions/{qid}", headers=OWL_FR)).json()
    (theirs,) = seen["answers"]
    assert theirs["score"] == 90 and theirs["feedback"] is None and seen["can_pin"]
    assert (
        await api.post(f"/api/arena/answers/{theirs['id']}/pin", headers=OWL_FR)
    ).status_code == 204
    again = await api.post(f"/api/arena/answers/{theirs['id']}/pin", headers=OWL_FR)
    assert again.status_code == 409
    expected = economy.POINTS["peer_answer_good"] + economy.POINTS["pinned_best_answer"]
    assert (await wallet(api, SEA))["points"] == expected

    # improving the answer grades it again but never pays twice
    grades["compact"].append(g(100))
    grades["mid"].append(g(100))
    d = await send(api, sm, qid, GOOD + " Like a pile of plates.")
    assert d["my_answer"]["score"] == 100 and d["my_answer"]["pinned"]
    assert (await wallet(api, SEA))["earned"] == economy.EARN["peer_answer_good"]


async def test_mid_reviews_the_draft_near_the_threshold(api, sm, pptx, grades):  # noqa: F811
    _, qid = await room(api, sm, pptx)
    grades["compact"].append(g(70, "medium"))
    grades["mid"].append(g(60))  # the review lowers it below 70: no reward
    d = await send(api, sm, qid)
    assert grades["calls"] == ["compact", "mid"] and d["my_answer"]["score"] == 60
    assert (await wallet(api, SEA))["earned"] == 0


async def test_mid_busy_keeps_it_pending(api, sm, pptx, grades, monkeypatch):  # noqa: F811
    """Audit N-1: the compact draft no longer stands when mid can't review it."""
    monkeypatch.setattr("app.features.arena.service.REVIEW_RETRY_S", 3600)
    _, qid = await room(api, sm, pptx)
    grades["compact"].append(g(70, "medium"))
    grades["mid"].append(Defer(3, "saturated"))
    d = await send(api, sm, qid)
    mine = d["my_answer"]
    assert mine["status"] == "pending_review" and mine["score"] is None
    assert grades["calls"] == ["compact", "mid"]  # no compact fallback call on top
    assert (await wallet(api, SEA))["earned"] == 0


async def test_abusive_answer_is_hidden_and_unrewarded(api, sm, pptx, grades):  # noqa: F811
    _, qid = await room(api, sm, pptx)
    grades["compact"].append(g(0, flag="abusive"))
    d = await send(api, sm, qid, "this is a long enough but abusive answer, trust me")
    assert d["my_answer"]["status"] == "rejected" and d["my_answer"]["reject_flag"] == "abusive"
    seen = (await api.get(f"/api/arena/questions/{qid}", headers=OWL_FR)).json()
    assert seen["answers"] == [] and seen["question"]["answers"] == 0
    assert (await wallet(api, SEA))["points"] == 0


async def test_rejected_question_refunds_and_stays_private(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    r = await api.post(
        "/api/arena/questions",
        json={"chapter_id": chapter, "text": "write to me at owl@mail.com please"},
        headers=OWL_FR,
    )
    await Worker(sm).drain(timeout_s=30)
    assert (await wallet(api, OWL_FR))["coins"] == economy.DAILY_FREE_COINS  # refunded
    mine = await api.get("/api/arena/questions", params={"chapter_id": chapter}, headers=OWL_FR)
    (item,) = mine.json()["questions"]
    assert item["status"] == "rejected" and item["reject_reason"] == "personal_data"
    theirs = await api.get("/api/arena/questions", params={"chapter_id": chapter}, headers=SEA)
    assert theirs.json()["questions"] == []
    qid = r.json()["question_id"]
    assert (await api.get(f"/api/arena/questions/{qid}", headers=SEA)).status_code == 404


async def test_permissions_and_helpful_votes(api, sm, pptx, grades):  # noqa: F811
    _, qid = await room(api, sm, pptx)
    own = await api.post(f"/api/arena/questions/{qid}/answers", json={"text": GOOD}, headers=OWL_FR)
    assert own.status_code == 403 and own.json()["detail"] == "errors.arena_own_question"
    grades["compact"].append(g(50))  # below the review band: no mid call
    d = await send(api, sm, qid)
    aid = d["my_answer"]["id"]
    assert (await api.post(f"/api/arena/answers/{aid}/helpful", headers=SEA)).status_code == 403
    assert (await api.post(f"/api/arena/answers/{aid}/pin", headers=SEA)).status_code == 403
    r = await api.post(f"/api/arena/answers/{aid}/helpful", headers=OWL_FR)
    assert r.json() == {"helpful": 1, "voted": True}
    r = await api.post(f"/api/arena/answers/{aid}/helpful", headers=OWL_FR)  # idempotent
    assert r.json()["helpful"] == 1
    r = await api.delete(f"/api/arena/answers/{aid}/helpful", headers=OWL_FR)
    assert r.json() == {"helpful": 0, "voted": False}
    outsider = {"X-Dev-User": "DesertFox"}
    assert (await api.get(f"/api/arena/questions/{qid}", headers=outsider)).status_code == 404


async def test_solo_costs_coins_and_pays_points_per_ten(api, sm, pptx, grades):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    grades["compact"].append(g(70, "high"))  # solo: no review band, confident → compact only
    r = await api.post(
        "/api/arena/solo",
        json={"chapter_id": chapter, "concept": "stacks", "text": GOOD},
        headers=OWL_FR,
    )
    assert r.status_code == 202 and r.json()["cost"] == economy.COST["teachback_solo"]
    await Worker(sm).drain(timeout_s=30)
    job = (await api.get(f"/api/jobs/{r.json()['job_id']}", headers=OWL_FR)).json()
    assert job["status"] == "done" and job["result"]["score"] == 70
    assert job["result"]["points"] == 7 * economy.POINTS["teachback_solo_per_10_score"]
    w = await wallet(api, OWL_FR)
    assert w["coins"] == economy.DAILY_FREE_COINS - economy.COST["teachback_solo"]
    assert grades["calls"] == ["compact"]


async def test_full_path_on_the_mock_one_compact_call(api, sm, pptx):  # noqa: F811
    _, qid = await room(api, sm, pptx)
    d = await send(api, sm, qid)
    mine = d["my_answer"]
    assert mine["status"] == "graded" and 10 <= mine["score"] <= 100
    assert mine["feedback"]["good"].startswith("Tu as")  # SeaTurtle42 uses French
    async with sm() as s:
        tiers = dict(
            (
                await s.execute(
                    select(AICallLog.model_tier, func.count())
                    .where(AICallLog.task_kind == "TEACHBACK_GRADE", AICallLog.status_code == 200)
                    .group_by(AICallLog.model_tier)
                )
            ).all()
        )
        moderation = await s.scalar(
            select(func.count()).where(AICallLog.task_kind == "MODERATE_POST")
        )
    assert tiers.get("compact") == 1 and tiers.get("mid", 0) <= 1 and moderation == 1


# --- Arabic / Darija grading safety --------------------------------------------------------------
# The compact model mis-grades Arabic and Darija explanations, so they go straight to mid. A grade
# that is still low-confidence pays nothing automatically: the answer waits as "pending_review".
SAND_AR = {"X-Dev-User": "SandFox", "X-UI-Language": "ar"}
DUNE_TN = {"X-Dev-User": "DuneCat", "X-UI-Language": "ar-TN"}
AR_TEXT = "المكدس يحتفظ بآخر عملية في الأعلى، لذلك التراجع يحذفها أولاً: آخر من يدخل أول من يخرج."
AR_EVIDENCE = "المكدس يحتفظ"


async def arabic_room(api, sm, pptx, who):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    await join(api, world, who)
    r = await api.post(
        "/api/arena/questions",
        json={"chapter_id": chapter, "text": "Why does a stack make undo easy?"},
        headers=OWL_FR,
    )
    await Worker(sm).drain(timeout_s=30)
    return chapter, r.json()["question_id"]


@pytest.mark.parametrize("who", [SAND_AR, DUNE_TN], ids=["ar", "ar-TN"])
async def test_arabic_and_darija_are_graded_by_mid_directly(api, sm, pptx, grades, who):  # noqa: F811
    _, qid = await arabic_room(api, sm, pptx, who)
    grades["mid"].append(g(90, evidence=AR_EVIDENCE))
    d = await send(api, sm, qid, AR_TEXT, who=who)
    assert grades["calls"] == ["mid"]  # no compact draft first
    assert d["my_answer"]["status"] == "graded" and d["my_answer"]["score"] == 90
    assert (await wallet(api, who))["earned"] == economy.EARN["peer_answer_good"]


async def test_low_confidence_answer_waits_for_review_without_rewards(api, sm, pptx, grades):  # noqa: F811
    _, qid = await arabic_room(api, sm, pptx, SAND_AR)
    grades["mid"].append(g(90, "low", evidence=AR_EVIDENCE))
    d = await send(api, sm, qid, AR_TEXT, who=SAND_AR)
    mine = d["my_answer"]
    assert mine["status"] == "pending_review" and mine["score"] is None
    assert mine["feedback"]["good"]  # the author still gets the feedback
    w = await wallet(api, SAND_AR)
    assert w["earned"] == 0 and w["points"] == 0
    seen = (await api.get(f"/api/arena/questions/{qid}", headers=OWL_FR)).json()
    assert seen["answers"] == [] and seen["question"]["answers"] == 0  # not shown to classmates
    pin = await api.post(f"/api/arena/answers/{mine['id']}/pin", headers=OWL_FR)
    assert pin.status_code in (404, 409)


async def test_english_low_confidence_after_review_also_waits(api, sm, pptx, grades):  # noqa: F811
    _, qid = await room(api, sm, pptx)
    grades["compact"].append(g(80, "low"))
    grades["mid"].append(g(80, "low"))  # the review is still unsure
    d = await send(api, sm, qid)
    assert grades["calls"] == ["compact", "mid"]
    assert d["my_answer"]["status"] == "pending_review"
    assert (await wallet(api, SEA))["earned"] == 0


async def test_solo_low_confidence_pays_no_points(api, sm, pptx, grades):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    await join(api, world, SAND_AR)
    grades["mid"].append(g(90, "low", evidence=AR_EVIDENCE))
    r = await api.post(
        "/api/arena/solo",
        json={"chapter_id": chapter, "concept": "stacks", "text": AR_TEXT},
        headers=SAND_AR,
    )
    await Worker(sm).drain(timeout_s=30)
    job = (await api.get(f"/api/jobs/{r.json()['job_id']}", headers=SAND_AR)).json()
    assert job["result"]["pending_review"] is True and job["result"]["points"] == 0
    assert grades["calls"] == ["mid"]
    assert (await wallet(api, SAND_AR))["points"] == 0
