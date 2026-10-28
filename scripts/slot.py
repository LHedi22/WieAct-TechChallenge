#!/usr/bin/env python3
"""Is our EdNova API key live right now? (Tunis time, alternating slots 20/10 -> 10/11/2026)

The slot pattern lives in backend/app/core/slot.py (one source for this script and the gateway).
Reads LLM_SLOT_GROUP from the environment or .env (only that variable, nothing else).
Exit code: 0 when live, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.slot import TZ, current_slot, next_slot, upcoming  # noqa: E402


def read_group() -> str:
    g = os.environ.get("LLM_SLOT_GROUP")
    if not g:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("LLM_SLOT_GROUP="):
                    g = line.split("=", 1)[1].strip()
    return (g or "A").upper()


def main() -> None:
    group = read_group()
    now = datetime.now(TZ)
    live = current_slot(now, group)
    if live:
        msg = f"LIVE until {live.end:%H:%M} Tunis time".replace("00:00", "24:00")
    else:
        nxt = next_slot(now, group)
        msg = f"not live; next slot {nxt.label()}" if nxt else "not live; no more slots"
    if "--brief" in sys.argv:
        hint = "Real platform OK." if live else "Use mock-llm."
        print(
            f"[EdNova key, group {group}] {msg}. {hint} (pattern unconfirmed - see docs/DECISIONS.md)"
        )
        return
    print(f"Now: {now:%a %d/%m %H:%M} Tunis - group {group}")
    print(msg)
    print("Upcoming slots:")
    for s in upcoming(now, group):
        print(f"  {s.label()}")
    sys.exit(0 if live else 1)


if __name__ == "__main__":
    main()
