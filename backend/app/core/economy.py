"""The coin & point economy — single source of truth (docs/ECONOMY.md), served at GET /api/economy.
The UI renders every price and reward from here; never hard-code a number in the frontend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

DAILY_FREE_COINS = 20  # refilled at local midnight (Africa/Tunis); free coins don't carry over
DAILY_EARN_CAP = 10  # max coins earned per day from challenges + peer answers
PURCHASED_COINS_EXPIRE = False
EXAM_PASS_DAILY_LIMIT = 15  # a high daily limit, never "unlimited"

COST = {
    "cached_content": 0,  # reopen notes, flashcards, maps, audio, past quizzes
    "flashcard_review": 0,
    "placement_quiz": 0,  # 8 questions, once per course
    "quiz": 5,  # 10 questions
    "tutor_session": 8,
    "teachback_solo": 8,
    "generate_shared_asset": 15,  # new notes / map / audio for a chapter+level+language
    "peer_question": 2,
}
EARN = {
    "peer_answer_good": 3,  # only if AI score >= PEER_ANSWER_THRESHOLD
    "daily_challenge": 3,  # each, 3 per day
    "creator_new_member": 5,
}
PEER_ANSWER_THRESHOLD = 70  # /100
WISDOM_THRESHOLD = 3  # distinct students with the same (concept, mistake_type) in a world

POINTS = {
    "quiz_correct_first_try": 10,
    "quiz_correct_second_try": 5,
    "activity_completed": 20,
    "peer_answer_good": 30,
    "pinned_best_answer": 50,
    "daily_challenge": 15,
    "all_challenges_bonus": 30,
    "teachback_solo_per_10_score": 3,
}
SPENDING_ORDER = ["free", "earned", "purchased"]

# Simulated for the hackathon ("demo purchase"); prices are placeholders to validate in user tests.
PRODUCTS = {
    "coin_pack": {"coins": 50, "price_tnd": 2},
    "exam_pass": {"days": 14, "price_tnd": 10},
}

# Teach-Back draft-then-revise: the mid model reviews a compact grade only when it is unsure, or
# when the score is this close to PEER_ANSWER_THRESHOLD (coins depend on that decision).
TEACHBACK_REVIEW_BAND = 10

# Avatar extras unlocked with points (points can never be bought; coins never buy cosmetics).
COSMETICS = {
    "cap": 0,
    "glasses": 0,
    "scarf": 0,
    "chechia": 300,
    "headphones": 500,
}

# What each building costs to enter. "shared" buildings are free when the class already made it.
BUILDINGS = {
    "quiz_hall": {"cost": COST["quiz"]},
    "socratic_tutor": {"cost": COST["tutor_session"]},
    "study_studio": {"cost": COST["generate_shared_asset"], "free_if_cached": True},
    "audio_studio": {"cost": COST["generate_shared_asset"], "free_if_cached": True},
    "teachback_arena": {"cost": COST["peer_question"], "answer_cost": 0},
}

TZ = ZoneInfo("Africa/Tunis")


def next_refill(now: datetime | None = None) -> datetime:
    """The next local midnight in Tunis, as an aware UTC datetime."""
    local = (now or datetime.now(UTC)).astimezone(TZ)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def as_dict() -> dict:
    return {
        "daily_free_coins": DAILY_FREE_COINS,
        "daily_earn_cap": DAILY_EARN_CAP,
        "exam_pass_daily_limit": EXAM_PASS_DAILY_LIMIT,
        "cost": COST,
        "earn": EARN,
        "points": POINTS,
        "peer_answer_threshold": PEER_ANSWER_THRESHOLD,
        "products": PRODUCTS,
        "cosmetics": COSMETICS,
        "buildings": BUILDINGS,
    }
