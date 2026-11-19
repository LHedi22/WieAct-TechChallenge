#!/usr/bin/env python3
"""The jury-slot evidence runs (docs/report/JURY_SLOT_RUNBOOK.md, audit OPT-03), in order.

    python3 scripts/jury_slot.py                                  # dry run: prints the plan
    python3 scripts/jury_slot.py --cloud --api https://<api> --chapter <id>

Without --cloud nothing runs and no request is sent. With --cloud each step asks y/N before it
starts (its estimated platform requests shown), steps done in the browser are only printed, and
a failed step stops the run. Standard library only.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass

BACKEND = "docker compose exec -T backend uv run python -m"


@dataclass(frozen=True)
class Step:
    key: str
    what: str
    command: str  # "" = a manual step in the browser
    requests: str
    mid: str


def plan(api: str, chapter: str) -> list[Step]:
    return [
        Step("1a", "seed the demo world, then again for the Class Wisdom tip",
             f"{BACKEND} app.seed", "~15", "~4"),
        Step("1b", "browser: placement for both courses in en, fr, ar, ar-TN", "", "16", "8"),
        Step("1c", "browser: study pack + audio per course in en and ar", "", "~18", "~8"),
        Step("2a", "every feature x 4 languages",
             f"{BACKEND} app.evals slot --cloud", "~35", "~13"),
        Step("2b0", "stop the worker: the in-process evals refuse beside it (OPT-19)",
             "docker compose stop worker", "0", "0"),
        Step("2b", "Teach-Back grading on real models",
             f"{BACKEND} app.evals teachback --cloud", "~33", "~22"),
        Step("2c", "verifier on fixture keys", f"{BACKEND} app.evals quiz-keys --cloud", "4", "4"),
        Step("2d", "verifier on generated quizzes",
             f"{BACKEND} app.evals quiz --langs en,fr,ar,ar-TN --n 10 --fresh", "8", "4"),
        Step("2e0", "start the worker again (the probe and the load test need it)",
             "docker compose start worker", "0", "0"),
        Step("2e", "moderation per language",
             f"python3 audit/tools/adversarial_probe.py --api {api} --parts moderation", "~8", "0"),
        Step("2f", "10 students on one chapter",
             f"python3 scripts/load_class.py --api {api} --code OLIVE-7Q2 --chapter {chapter}"
             " --students 10 --cloud", "~5-8", "~1"),
        Step("2g", "stats export for the report",
             f"python3 scripts/export_stats.py --api {api}", "0", "0"),
    ]  # fmt: skip


def show(steps: list[Step]) -> None:
    for s in steps:
        how = s.command or "(manual, in the browser)"
        print(f"{s.key}  {s.what}\n     {how}\n     ≈ {s.requests} requests, ≈ {s.mid} mid")


def main(argv: list[str] | None = None, ask=input, run=subprocess.call) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cloud", action="store_true", help="really run the steps (spends quota)")
    ap.add_argument("--api", default="<api>", help="the API base URL the host scripts call")
    ap.add_argument("--chapter", default="<chapter id>", help="chapter for the class load test")
    ap.add_argument("--from", dest="start", default="1a", help="start at this step key")
    a = ap.parse_args(argv)
    steps = plan(a.api, a.chapter)
    keys = [s.key for s in steps]
    if a.start not in keys:
        ap.error(f"--from must be one of {keys}")
    steps = steps[keys.index(a.start) :]
    if not a.cloud:
        show(steps)
        print("\nDry run: nothing was sent. Add --cloud (and --api, --chapter) during the slot.")
        return 0
    if "<" in a.api or "<" in a.chapter:
        print("--cloud needs a real --api and --chapter", file=sys.stderr)
        return 2
    for s in steps:
        show([s])
        if not s.command:
            ask("     Do it in the browser, then press Enter… ")
            continue
        if ask("     Run it? [y/N] ").strip().lower() != "y":
            print("     skipped")
            continue
        if code := run(shlex.split(s.command)):
            print(f"Step {s.key} failed (exit {code}); stopping.", file=sys.stderr)
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
