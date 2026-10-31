"""Daily challenges: instant rule plan + ONE plan-once DAILY_PLAN job per student per day,
validated against the catalogue; progress from real events; coins (capped) + points per
challenge and a bonus for all 3, each awarded once."""

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select

from app.core import economy
from app.core.wallet_rules import tunis_day
from app.features.daily import plan, service
from app.jobs.worker import Worker
from app.models import AICallLog, CoinLedger, DailyState, Job, Profile, User
from tests.test_quiz import answers_of, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user, pptx  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 2)
OWL_FR = as_user("NightOwl7", "fr")


def cand(chapter: str, *, mastery=None, weak=False, exam=None) -> plan.Candidate:
    return plan.Candidate(
        world_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        chapter_id=uuid.uuid4(),
        course="Calculus",
        chapter=chapter,
        mastery=mastery,
        weak=weak,
        exam_date=exam,
    )


# --- pure: catalogue, rule plan, AI validation, progress -----------------------------------------
def test_rule_plan_targets_the_weakest_chapter_then_the_nearest_exam():
    ok = cand("Derivatives", mastery=90)
    soon = cand("Integrals", exam=date(2026, 11, 5))
    weak = cand("Limits", mastery=30, weak=True)
    challenges = plan.rule_plan([ok, soon, weak], TODAY)
    assert [c["type"] for c in challenges] == ["quiz_questions", "quiz_score", "tutor_session"]
    assert {c["chapter"] for c in challenges} == {"Limits"}
    assert plan.ranked([ok, soon], TODAY)[0] is soon
    assert all(c["progress"] == 0 and not c["done"] for c in challenges)


def test_rule_plan_without_chapters_still_gives_three_challenges():
    challenges = plan.rule_plan([], TODAY)
    assert len(challenges) == 3 and all(c["chapter_id"] is None for c in challenges)
    assert "quiz_score" not in {c["type"] for c in challenges}  # needs a chapter


def test_ai_output_is_validated_snapped_and_filled_from_the_rule_plan():
    cands = [cand("Limits"), cand("Derivatives")]
    rule = plan.rule_plan(cands, TODAY)
    content = {
        "challenges": [
            {"type": "quiz_score", "chapter": 2, "target": 73, "why": "Derivatives next."},
            {"type": "podcast", "chapter": 1, "target": 5},  # not in the catalogue
            {"type": "quiz_score", "chapter": None, "target": 70},  # needs a chapter
            {"type": "quiz_score", "chapter": 2, "target": 90},  # duplicate
            {"type": "quiz_questions", "chapter": 9, "target": 300},  # unknown chapter → any
        ],
        "message": "  A calm day.  ",
    }
    out, message = plan.from_ai(content, cands, rule)
    assert [(c["type"], c["chapter"], c["target"]) for c in out] == [
        ("quiz_score", "Derivatives", 70),
        ("quiz_questions", None, 20),
        ("quiz_questions", "Derivatives", 10),  # from the rule plan
    ]
    assert out[0]["why"] == "Derivatives next." and message == "A calm day."
    garbage, none = plan.from_ai("not json", cands, rule)
    assert garbage == rule and none is None


def test_progress_counts_matching_events_only():
    c = cand("Limits")
    quiz = plan.challenge("quiz_score", 70, c)
    count = plan.challenge("quiz_questions", 5, None)
    other = str(uuid.uuid4())
    assert not plan.advance(quiz, "quiz_score", other, 1, 95)  # another chapter
    assert not plan.advance(quiz, "quiz_score", str(c.chapter_id), 1, 60)
    assert plan.advance(quiz, "quiz_score", str(c.chapter_id), 1, 80) and quiz["progress"] == 80
    assert not plan.advance(quiz, "quiz_score", str(c.chapter_id), 1, 100)  # already done
    for _ in range(4):
        assert not plan.advance(count, "quiz_questions", other, 1, None)
    assert plan.advance(count, "quiz_questions", other, 1, None) and count["progress"] == 5
    assert not plan.advance(count, "teachback", other, 1, None)


def test_reminder_is_due_after_the_chosen_time_until_all_are_done():
    state = DailyState(challenges=[{"done": False}, {"done": True}])
    profile = Profile(reminder_time=time(18, 0))
    before = datetime(2026, 11, 2, 16, 59, tzinfo=UTC)  # 17:59 in Tunis
    after = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
    assert not service.reminder_due(profile, state, before)
    assert service.reminder_due(profile, state, after)
    assert not service.reminder_due(Profile(reminder_time=None), state, after)
    state.challenges = [{"done": True}] * 3
    assert not service.reminder_due(profile, state, after)


# --- API + jobs ----------------------------------------------------------------------------------
async def count(sm, *where) -> int:
    async with sm() as s:
        return await s.scalar(select(func.count()).where(*where))


async def test_first_read_gives_a_rule_plan_now_and_one_mid_plan_job(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    first = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert len(first["challenges"]) == 3 and first["planned_by"] == "rule"
    assert first["first_open_today"] and first["plan_job_id"] and not first["all_done"]
    assert not first["returning"]  # signed up today: no "welcome back" screen
    assert first["coins"] == economy.DAILY_FREE_COINS
    again = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert again["plan_job_id"] == first["plan_job_id"]
    assert await count(sm, Job.kind == "DAILY_PLAN") == 1

    await Worker(sm).drain(timeout_s=30)
    planned = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert planned["planned_by"] == "ai" and planned["message"]
    assert [c["type"] for c in planned["challenges"]] == [
        "quiz_score",
        "quiz_questions",
        "teachback",
    ]
    assert planned["challenges"][0]["chapter_id"] and planned["challenges"][0]["why"]
    async with sm() as s:
        log = list(await s.scalars(select(AICallLog).where(AICallLog.task_kind == "DAILY_PLAN")))
        job = await s.scalar(select(Job).where(Job.kind == "DAILY_PLAN"))
    assert len(log) == 1 and log[0].model_tier == "mid" and job.cost == 0

    seen = (await api.post("/api/daily/seen", headers=OWL_FR)).json()
    assert not seen["first_open_today"]
    assert not (await api.get("/api/daily", headers=OWL_FR)).json()["first_open_today"]


async def test_ai_lines_hide_after_a_language_switch(api, sm, pptx):  # noqa: F811
    """The AI plan is written once, in the language of that moment. After a switch, its free-text
    lines (why, message) are left out rather than shown in the wrong language; no new AI call."""
    await indexed(api, sm, pptx)
    await api.get("/api/daily", headers=OWL_FR)
    await Worker(sm).drain(timeout_s=30)
    fr = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert fr["message"] and any(c["why"] for c in fr["challenges"])
    en = (await api.get("/api/daily", headers={**OWL_FR, "X-UI-Language": "en"})).json()
    assert en["message"] is None and not any(c["why"] for c in en["challenges"])
    assert [c["type"] for c in en["challenges"]] == [c["type"] for c in fr["challenges"]]
    back = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert back["message"] == fr["message"]
    assert await count(sm, Job.kind == "DAILY_PLAN") == 1


async def test_plan_cache_is_per_language(api, sm, pptx):  # noqa: F811
    """A plan rebuilt the same day in another language must not reuse the cached reply."""
    await indexed(api, sm, pptx)
    await api.get("/api/daily", headers=OWL_FR)
    await Worker(sm).drain(timeout_s=30)
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "NightOwl7"))
        await s.delete(await s.get(DailyState, (user.id, tunis_day())))
        await s.commit()
    await api.get("/api/daily", headers={**OWL_FR, "X-UI-Language": "en"})
    await Worker(sm).drain(timeout_s=30)
    async with sm() as s:
        calls = await s.scalar(
            select(func.count())
            .select_from(AICallLog)
            .where(AICallLog.task_kind == "DAILY_PLAN", AICallLog.cache_hit.is_(False))
        )
    assert calls == 2  # one per language, no cache hit across languages


async def set_challenges(sm, nickname: str, challenges: list[dict]) -> None:
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == nickname))
        state = await s.get(DailyState, (user.id, tunis_day()))
        state.challenges = challenges
        await s.commit()


async def test_quiz_events_complete_challenges_and_reward_once(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    await api.get("/api/daily", headers=OWL_FR)
    stacks = plan.Candidate(
        world_id=uuid.UUID(world["id"]),
        course_id=uuid.UUID(world["course"]["id"]),
        chapter_id=uuid.UUID(chapter),
        course="Data Structures",
        chapter="Stacks",
        mastery=None,
        weak=False,
        exam_date=None,
    )
    await set_challenges(
        sm,
        "NightOwl7",
        [
            plan.challenge("quiz_questions", 5, None),
            plan.challenge("quiz_score", 70, stacks),
            plan.challenge("teachback", 1, stacks),
        ],
    )
    body = {"chapter_id": chapter, "level": "intermediate"}
    aid = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()["attempt_id"]
    right = await answers_of(sm)
    for i in range(10):
        await api.post(
            f"/api/quiz/attempts/{aid}/answer", json={"q": i, "choice": right[i]}, headers=OWL_FR
        )
    mid = (await api.get("/api/daily", headers=OWL_FR)).json()["challenges"]
    assert mid[0]["done"] and mid[0]["progress"] == 5 and not mid[1]["done"]
    await api.post(f"/api/quiz/attempts/{aid}/finish", headers=OWL_FR)
    after = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert after["challenges"][1]["done"] and after["challenges"][1]["progress"] == 100
    wallet = (await api.get("/api/wallet", headers=OWL_FR)).json()
    assert wallet["earned_today"] == 2 * economy.EARN["daily_challenge"]

    async with sm() as s:  # the third one, from a graded Teach-Back explanation
        user = await s.scalar(select(User).where(User.nickname == "NightOwl7"))
        done = await service.record(s, user.id, "teachback", chapter_id=uuid.UUID(chapter))
        again = await service.record(s, user.id, "teachback", chapter_id=uuid.UUID(chapter))
        await s.commit()
    assert done == [2] and again == []
    final = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert final["all_done"]
    after_all = (await api.get("/api/wallet", headers=OWL_FR)).json()
    assert after_all["earned_today"] == 3 * economy.EARN["daily_challenge"]
    gained = after_all["points"] - wallet["points"]
    assert gained == economy.POINTS["daily_challenge"] + economy.POINTS["all_challenges_bonus"]


async def test_challenge_coins_respect_the_daily_earn_cap(api, sm, pptx):  # noqa: F811
    await api.get("/api/daily", headers=OWL_FR)
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "NightOwl7"))
        s.add(
            CoinLedger(
                user_id=user.id,
                day=tunis_day(),
                bucket="earned",
                kind="earned",
                delta=economy.DAILY_EARN_CAP - 1,
                ref="answer:earlier",
            )
        )
        state = await s.get(DailyState, (user.id, tunis_day()))
        state.challenges = [plan.challenge("tutor_session", 1, None)] + state.challenges[1:]
        await s.commit()
        assert await service.record(s, user.id, "tutor_session") == [0]
        await s.commit()
    wallet = (await api.get("/api/wallet", headers=OWL_FR)).json()
    assert wallet["earned_today"] == economy.DAILY_EARN_CAP  # +1, not +3


async def test_ai_plan_never_replaces_a_plan_with_progress(api, sm, pptx):  # noqa: F811
    await indexed(api, sm, pptx)
    first = (await api.get("/api/daily", headers=OWL_FR)).json()
    async with sm() as s:
        user = await s.scalar(select(User).where(User.nickname == "NightOwl7"))
        target = first["challenges"][0]
        assert target["type"] == "quiz_questions"
        chapter_id = uuid.UUID(target["chapter_id"])
        await service.record(s, user.id, "quiz_questions", chapter_id=chapter_id)
        await s.commit()
    await Worker(sm).drain(timeout_s=30)
    after = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert after["planned_by"] == "rule"
    assert [c["type"] for c in after["challenges"]] == [c["type"] for c in first["challenges"]]
    assert after["challenges"][0]["progress"] == 1


async def test_no_row_today_means_nothing_to_track(sm):
    async with sm() as s:
        user = User(nickname="Quiet1", password_hash="!", ui_language="en")
        s.add(user)
        await s.commit()
        assert await service.record(s, user.id, "quiz_questions") == []
