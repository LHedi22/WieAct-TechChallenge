"""Pure wallet rules (ECONOMY.md): spending order, earn cap, streaks, the Tunis day."""

from datetime import UTC, date, datetime

from app.core import economy
from app.core.wallet_rules import capped_earn, split_spend, streak, tunis_day


def test_spend_burns_free_then_earned_then_purchased():
    assert split_spend(5, free=20, earned=3, purchased=50) == {"free": 5}
    assert split_spend(8, free=5, earned=2, purchased=50) == {
        "free": 5,
        "earned": 2,
        "purchased": 1,
    }
    assert split_spend(8, free=0, earned=0, purchased=8) == {"purchased": 8}


def test_spend_exact_and_short_balances():
    assert split_spend(5, free=2, earned=3, purchased=0) == {"free": 2, "earned": 3}
    assert split_spend(5, free=2, earned=2, purchased=0) is None
    assert split_spend(0, free=0, earned=0, purchased=0) == {}


def test_earn_is_capped_per_day():
    cap = economy.DAILY_EARN_CAP
    assert capped_earn(3, earned_today=0) == 3
    assert capped_earn(3, earned_today=cap - 1) == 1
    assert capped_earn(3, earned_today=cap) == 0
    assert capped_earn(3, earned_today=cap + 5) == 0


def test_streak_counts_consecutive_days_ending_today_or_yesterday():
    today = date(2026, 11, 4)
    assert streak(set(), today) == 0
    assert streak({today}, today) == 1
    assert streak({date(2026, 11, 2), date(2026, 11, 3), today}, today) == 3
    # nothing yet today: yesterday's run still counts (the day isn't over)
    assert streak({date(2026, 11, 2), date(2026, 11, 3)}, today) == 2
    # a gap breaks it
    assert streak({date(2026, 11, 1), date(2026, 11, 3), today}, today) == 2
    assert streak({date(2026, 11, 1)}, today) == 0


def test_tunis_day_flips_at_local_midnight():
    # Tunis is UTC+1: 22:59 UTC is still the 29th, 23:00 UTC is the 30th
    assert tunis_day(datetime(2026, 10, 29, 22, 59, tzinfo=UTC)) == date(2026, 10, 29)
    assert tunis_day(datetime(2026, 10, 29, 23, 0, tzinfo=UTC)) == date(2026, 10, 30)
