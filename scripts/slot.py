#!/usr/bin/env python3
"""Is our EdNova API key live right now? (Tunis time, alternating slots 20/10 -> 10/11/2026)

Pattern from the organisers' email: each weekday, Group A has one half-day and Group B the other,
and the halves swap every weekday. Tue 20/10: A 12:00-24:00, B 00:00-12:00; Wed 21/10: A 00:00-12:00 ...
Weekend handling is unconfirmed: we assume no slots on weekends and that the alternation advances
per weekday. Confirm with the organisers and adjust WEEKENDS_OPEN.

Reads LLM_SLOT_GROUP from the environment or .env (only that variable, nothing else).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Tunis")
START = date(2026, 10, 20)
END = date(2026, 11, 10)
WEEKENDS_OPEN = False


def read_group() -> str:
    g = os.environ.get("LLM_SLOT_GROUP")
    if not g:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("LLM_SLOT_GROUP="):
                    g = line.split("=", 1)[1].strip()
    return (g or "A").upper()


def slot_for(day: date, group: str) -> tuple[time, time] | None:
    """Return (start, end) of our slot on `day`, or None."""
    if not (START <= day <= END):
        return None
    if day.weekday() >= 5 and not WEEKENDS_OPEN:
        return None
    n, d = 0, START
    while d < day:
        d += timedelta(days=1)
        if d.weekday() < 5 or WEEKENDS_OPEN:
            n += 1
    # Every open day both groups get one half; the halves swap each open day.
    # Day 0 (Tue 20/10): Group A 12:00-24:00, Group B 00:00-12:00.
    a_afternoon = n % 2 == 0
    afternoon = a_afternoon if group == "A" else not a_afternoon
    return (time(12), time(23, 59, 59)) if afternoon else (time(0), time(11, 59, 59))


def status(now: datetime, group: str) -> tuple[bool, str]:
    today = slot_for(now.date(), group)
    if today and today[0] <= now.time() <= today[1]:
        return True, f"LIVE until {'24:00' if today[1].hour == 23 else '12:00'} Tunis time"
    for i in range(0, 25):
        d = now.date() + timedelta(days=i)
        s = slot_for(d, group)
        if s and datetime.combine(d, s[0], TZ) > now:
            return False, f"not live; next slot {d:%a %d/%m} {s[0]:%H:%M}-{'24:00' if s[1].hour == 23 else '12:00'}"
    return False, "not live; no more slots in the challenge window"


def main() -> None:
    group = read_group()
    now = datetime.now(TZ)
    live, msg = status(now, group)
    if "--brief" in sys.argv:
        print(f"[EdNova key, group {group}] {msg}. {'Real platform OK.' if live else 'Use mock-llm.'} (pattern unconfirmed - see docs/DECISIONS.md)")
        return
    print(f"Now: {now:%a %d/%m %H:%M} Tunis · group {group}")
    print(msg)
    print("Upcoming slots:")
    for i in range(7):
        d = now.date() + timedelta(days=i)
        s = slot_for(d, group)
        if s:
            print(f"  {d:%a %d/%m}  {s[0]:%H:%M}-{'24:00' if s[1].hour == 23 else '12:00'}")
    sys.exit(0 if live else 1)


if __name__ == "__main__":
    main()
