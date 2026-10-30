"""Spaced repetition (PRODUCT.md: Again < 1 min, Good 10 min, Easy 3 days), pure functions."""

from datetime import UTC, datetime, timedelta

from app.features.studio import srs

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
DAY = 86400


def test_first_review_matches_the_product_intervals():
    new = srs.State()
    assert srs.preview(new) == {"again": 60, "good": 600, "easy": 3 * DAY}
    for grade, seconds in (("again", 60), ("good", 600), ("easy", 3 * DAY)):
        state, due = srs.review(new, grade, NOW)
        assert state.interval_s == seconds and due == NOW + timedelta(seconds=seconds)


def test_good_grows_by_ease_and_easy_grows_faster():
    s, _ = srs.review(srs.State(), "good", NOW)  # 10 min
    s, _ = srs.review(s, "good", NOW)
    assert s.interval_s == 600 * 2.5 and s.reps == 2
    easy, _ = srs.review(s, "easy", NOW)
    assert easy.interval_s >= 3 * DAY and easy.ease > s.ease
    long, _ = srs.review(srs.State(interval_s=4 * DAY, ease=2.5, reps=3), "easy", NOW)
    assert long.interval_s == round(4 * DAY * 2.5 * srs.EASY_BONUS)


def test_again_resets_and_lowers_ease_with_a_floor():
    s = srs.State(interval_s=5 * DAY, ease=1.4, reps=6)
    s, due = srs.review(s, "again", NOW)
    assert s.interval_s == 60 and s.reps == 0 and s.ease == srs.EASE_MIN
    assert due - NOW < timedelta(minutes=1, seconds=1)
    s, _ = srs.review(s, "again", NOW)
    assert s.ease == srs.EASE_MIN


def test_stage_buckets_for_the_counters():
    assert srs.stage(None) == "new"
    assert srs.stage(srs.State(interval_s=600, reps=1)) == "learning"
    assert srs.stage(srs.State(interval_s=3 * DAY, reps=1)) == "review"
