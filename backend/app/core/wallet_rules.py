"""Pure wallet rules (docs/ECONOMY.md): no database, so they are easy to test. The ledger service
(app/features/wallet) applies them inside a transaction."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.core import economy


def tunis_day(dt: datetime | None = None) -> date:
    """The calendar day in Africa/Tunis: "today" for refills, the earn cap and streaks."""
    return (dt or datetime.now(UTC)).astimezone(economy.TZ).date()


def split_spend(cost: int, *, free: int, earned: int, purchased: int) -> dict[str, int] | None:
    """How a cost is paid from each bucket, in SPENDING_ORDER (expiring coins first).
    None when the balance is too low."""
    available = {"free": free, "earned": earned, "purchased": purchased}
    if cost > sum(max(0, v) for v in available.values()):
        return None
    split: dict[str, int] = {}
    left = cost
    for bucket in economy.SPENDING_ORDER:
        take = min(left, max(0, available[bucket]))
        if take:
            split[bucket] = take
            left -= take
    return split


def capped_earn(amount: int, *, earned_today: int) -> int:
    """Coins actually credited once the daily earn cap is applied."""
    return max(0, min(amount, economy.DAILY_EARN_CAP - earned_today))


def streak(activity_days: set[date], today: date) -> int:
    """Consecutive days with activity, ending today, or yesterday while today is still open."""
    day = today if today in activity_days else today - timedelta(days=1)
    n = 0
    while day in activity_days:
        n += 1
        day -= timedelta(days=1)
    return n
