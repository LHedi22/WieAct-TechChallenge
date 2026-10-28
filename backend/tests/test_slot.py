from datetime import datetime

from app.core.slot import TZ, current_slot, next_slot, slot_for, upcoming


def at(day: int, month: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def test_first_day_group_a_afternoon_b_morning():
    a = slot_for(at(20, 10, 0).date(), "A")
    b = slot_for(at(20, 10, 0).date(), "B")
    assert (a.start.hour, b.start.hour) == (12, 0)


def test_halves_swap_each_weekday_and_skip_weekends():
    # Wed 21/10 A morning; Fri 23/10 A morning; Mon 26/10 is the next open day after Fri.
    assert slot_for(at(21, 10, 0).date(), "A").start.hour == 0
    assert slot_for(at(24, 10, 0).date(), "A") is None  # Saturday
    fri, mon = slot_for(at(23, 10, 0).date(), "A"), slot_for(at(26, 10, 0).date(), "A")
    assert fri.start.hour != mon.start.hour


def test_matches_observed_27_and_28_october():
    # 27/10 19:03 Tunis: key blocked for group A; 28/10 12:00-24:00 is ours.
    assert current_slot(at(27, 10, 19, 3), "A") is None
    assert current_slot(at(28, 10, 12, 30), "A") is not None
    assert next_slot(at(28, 10, 11, 0), "A").start == at(28, 10, 12)


def test_upcoming_skips_slots_that_already_ended():
    slots = upcoming(at(27, 10, 21, 26), "A")
    assert all(s.end > at(27, 10, 21, 26) for s in slots)
    assert slots[0].start == at(28, 10, 12)


def test_window_closes_after_deadline():
    assert slot_for(at(11, 11, 0).date(), "A") is None
