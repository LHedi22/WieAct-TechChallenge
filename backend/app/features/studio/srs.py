"""Spaced repetition for flashcards (PRODUCT.md: Again < 1 min, Good 10 min, Easy 3 days).
An SM-2 style schedule kept deliberately small: one interval and one ease per student and card."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

Grade = Literal["again", "good", "easy"]
GRADES: tuple[Grade, ...] = ("again", "good", "easy")

AGAIN_S = 60
GOOD_FIRST_S = 600
EASY_FIRST_S = 3 * 86400
EASE_START = 2.5
EASE_MIN = 1.3
EASE_AGAIN = -0.2
EASE_EASY = 0.15
EASY_BONUS = 1.3
REVIEW_FROM_S = 86400  # a card due a day or more away counts as "review", else "learning"


@dataclass(frozen=True)
class State:
    interval_s: int = 0
    ease: float = EASE_START
    reps: int = 0


def _interval(s: State, grade: Grade) -> int:
    if grade == "again":
        return AGAIN_S
    if grade == "good":
        return GOOD_FIRST_S if s.interval_s < GOOD_FIRST_S else round(s.interval_s * s.ease)
    if s.interval_s < EASY_FIRST_S:
        return EASY_FIRST_S
    return round(s.interval_s * s.ease * EASY_BONUS)


def review(s: State, grade: Grade, now: datetime) -> tuple[State, datetime]:
    """The state after grading a card, and when it is due next."""
    interval = _interval(s, grade)
    if grade == "again":
        nxt = replace(s, interval_s=interval, ease=max(EASE_MIN, s.ease + EASE_AGAIN), reps=0)
    elif grade == "easy":
        nxt = replace(s, interval_s=interval, ease=s.ease + EASE_EASY, reps=s.reps + 1)
    else:
        nxt = replace(s, interval_s=interval, reps=s.reps + 1)
    return nxt, now + timedelta(seconds=interval)


def preview(s: State) -> dict[str, int]:
    """Seconds until the card comes back, per button (shown under Again / Good / Easy)."""
    return {g: _interval(s, g) for g in GRADES}


def stage(s: State | None) -> Literal["new", "learning", "review"]:
    if s is None:
        return "new"
    return "review" if s.interval_s >= REVIEW_FROM_S else "learning"
