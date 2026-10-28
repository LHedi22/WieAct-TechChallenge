"""Our EdNova key's time slots (Tunis time, alternating halves, 20/10 → 10/11/2026).

Pattern from the organisers' email: each weekday Group A has one half-day and Group B the other,
and the halves swap every weekday. Tue 20/10: A 12:00-24:00, B 00:00-12:00; Wed 21/10: A 00-12 …
Weekends are assumed closed (unconfirmed, docs/DECISIONS.md). Standard library only: scripts/slot.py
imports this module directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Tunis")
START = date(2026, 10, 20)
END = date(2026, 11, 10)
WEEKENDS_OPEN = False


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime  # exclusive

    def label(self) -> str:
        end = "24:00" if self.end.hour == 0 else f"{self.end:%H:%M}"
        return f"{self.start:%a %d/%m} {self.start:%H:%M}-{end}"


def _open(day: date) -> bool:
    return START <= day <= END and (WEEKENDS_OPEN or day.weekday() < 5)


def slot_for(day: date, group: str) -> Slot | None:
    """Our slot on `day`, or None."""
    if not _open(day):
        return None
    n = sum(1 for i in range(1, (day - START).days + 1) if _open(START + timedelta(days=i)))
    # Day 0 (Tue 20/10): Group A afternoon. Halves swap on every open day.
    afternoon = (n % 2 == 0) == (group.upper() == "A")
    start = datetime.combine(day, time(12) if afternoon else time(0), TZ)
    return Slot(start, start + timedelta(hours=12))


def current_slot(now: datetime, group: str) -> Slot | None:
    """The slot we are in right now, if any."""
    now = now.astimezone(TZ)
    s = slot_for(now.date(), group)
    return s if s and s.start <= now < s.end else None


def upcoming(now: datetime, group: str, days: int = 7) -> list[Slot]:
    """Slots that haven't ended yet, starting today."""
    now = now.astimezone(TZ)
    out = []
    for i in range(days):
        s = slot_for(now.date() + timedelta(days=i), group)
        if s and s.end > now:
            out.append(s)
    return out


def next_slot(now: datetime, group: str) -> Slot | None:
    future = [s for s in upcoming(now, group, days=25) if s.start > now.astimezone(TZ)]
    return future[0] if future else None
