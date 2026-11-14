#!/usr/bin/env python3
"""Class load test on real features (audit OPT-30): N students sign up, join one world and hit the
SAME chapter at once, phase by phase (study pack, quiz, tutor), polling each job like the UI.
Unlike load.py it needs no mock-only endpoint and no dev header, so it also runs against the
cloud provider or the deployed site, where every AI call spends our quota.

    cd backend && uv run python ../scripts/load_class.py --code OLIVE-7Q2 --chapter <id>

Against a backend on the cloud provider it refuses to start (before any sign-up) unless `--cloud`
is given. Reports per phase: HTTP codes, coins charged, distinct jobs (sharing), wait p50/p95,
the highest queue position, Quick-mode jobs, and the /api/admin/stats deltas (calls per tier,
cache hits, repeated identical requests, fallbacks, refusals) when ADMIN_TOKEN is set.
Exits 1 if a job did not finish.

`--next-chapter <id>` (Group E, prefetch): each student first studies `--chapter` like the UI
(the studio page is opened before the pack is asked for, the quiz is finished), waits `--think`
seconds, then runs the same phases on the next chapter; those rows are labelled `next:<phase>`.
Run it with PREFETCH_ENABLED on and off on the backend to compare the next-chapter waits."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
import uuid
from typing import Any

import httpx

TERMINAL = {"done", "failed", "cancelled"}
PHASES = {
    "studio": lambda ch, lvl: (f"/api/studio/{ch}/generate", {"level": lvl, "pay": "me"}),
    "quiz": lambda ch, lvl: ("/api/quiz/start", {"chapter_id": ch, "level": lvl}),
    "tutor": lambda ch, lvl: ("/api/tutor/start", {"chapter_id": ch, "level": lvl}),
}
STAT_KEYS = ("calls", "cache_hits", "repeated_identical", "fallbacks")
# --next-chapter: what a studying student does besides the start (the page load, the finish)
STUDY = {"studio": lambda ch, lvl: f"/api/studio/{ch}?level={lvl}"}
FINISH = lambda attempt: f"/api/quiz/attempts/{attempt}/finish"  # noqa: E731


def rounds(chapter: str, next_chapter: str | None) -> list[tuple[str, str]]:
    """(label prefix, chapter) for each round of phases."""
    return [("", chapter)] + ([("next:", next_chapter)] if next_chapter else [])


def pct(values: list[float], q: float) -> float | None:
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(q * (len(v) - 1))))], 1) if v else None


def refuse(provider: str | None, cloud: bool) -> str | None:
    """Why the run must not start, or None."""
    if provider == "cloud" and not cloud:
        return "the backend runs on the cloud provider: pass --cloud to spend platform quota"
    return None


def flat_stats(d: dict[str, Any]) -> dict[str, int]:
    out = {k: int(d.get(k) or 0) for k in STAT_KEYS}
    for tier, v in (d.get("by_tier") or {}).items():
        out[tier] = int((v or {}).get("calls", 0))
    out["refusals"] = sum((d.get("refusals") or {}).values())
    return out


def summarize(phase: str, rows: list[dict], before: dict, after: dict) -> dict[str, Any]:
    waits = [r["wait_s"] for r in rows if r.get("wait_s") is not None]
    return {
        "phase": phase,
        "students": len(rows),
        "http": sorted({r["http"] for r in rows}),
        "coins_charged": sum(r.get("cost") or 0 for r in rows),
        "distinct_jobs": len({r["job"] for r in rows if r.get("job")}),
        "status": sorted({r["status"] for r in rows if r.get("status")}),
        "quick_mode": sum(1 for r in rows if r.get("quick")),
        "wait_p50_s": pct(waits, 0.5),
        "wait_p95_s": pct(waits, 0.95),
        "max_queue_position": max((r.get("max_pos") or 0 for r in rows), default=0),
        "stats_delta": {k: after[k] - before.get(k, 0) for k in after} if after else {},
    }


class Student:
    def __init__(self, api: str, name: str) -> None:
        self.name = name
        self.client = httpx.AsyncClient(base_url=api, timeout=60)  # its own cookie jar

    async def start(self, code: str, language: str) -> int:
        body = {"nickname": self.name, "password": secrets.token_urlsafe(12)}
        r = await self.client.post("/api/auth/signup", json=body | {"ui_language": language})
        if r.status_code != 201:
            return r.status_code
        return (await self.client.post("/api/worlds/join", json={"code": code})).status_code

    async def act(
        self, phase: str, chapter: str, level: str, timeout_s: float, study: bool = False
    ) -> dict:
        path, body = PHASES[phase](chapter, level)
        t0 = time.monotonic()
        if study and phase in STUDY:
            await self.client.get(STUDY[phase](chapter, level))
        r = await self.client.post(path, json=body)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        row = {"http": r.status_code, "cost": data.get("cost"), "job": data.get("job_id")}
        if r.status_code != 200 or not row["job"]:
            row |= {"wait_s": time.monotonic() - t0}
            if study and phase == "quiz" and data.get("attempt_id"):
                await self.client.post(FINISH(data["attempt_id"]))
            return row
        max_pos = 0
        while True:  # poll like the UI
            v = (await self.client.get(f"/api/jobs/{row['job']}")).json()
            max_pos = max(max_pos, v.get("queue_position") or 0)
            if v["status"] in TERMINAL or time.monotonic() - t0 > timeout_s:
                row |= {"status": v["status"], "quick": v.get("quick_mode"),
                        "wait_s": time.monotonic() - t0, "max_pos": max_pos}  # fmt: skip
                if study and phase == "quiz" and v["status"] == "done":
                    a = await self.client.post(f"/api/quiz/attempts/from-job/{row['job']}")
                    if a.status_code == 200:
                        await self.client.post(FINISH(a.json()["id"]))
                return row
            await asyncio.sleep(1.5)


async def stats(c: httpx.AsyncClient, provider: str) -> dict:
    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        return {}
    r = await c.get("/api/admin/stats", params={"provider": provider},
                    headers={"X-Admin-Token": token})  # fmt: skip
    return flat_stats(r.json()) if r.status_code == 200 else {}


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--code", required=True, help="the world's join code")
    ap.add_argument("--chapter", required=True, help="chapter id every student opens")
    ap.add_argument("--students", type=int, default=10)
    ap.add_argument("--level", default="intermediate")
    ap.add_argument("--language", default="en")
    ap.add_argument("--phases", default="studio,quiz,tutor")
    ap.add_argument("--timeout", type=float, default=900, help="max wait per job (s)")
    ap.add_argument("--cloud", action="store_true", help="allow a backend on the cloud provider")
    ap.add_argument("--next-chapter", help="study --chapter, think, then start this chapter")
    ap.add_argument("--think", type=float, default=90, help="seconds between the two chapters")
    a = ap.parse_args(argv)
    phases = [p for p in a.phases.split(",") if p]
    if bad := [p for p in phases if p not in PHASES]:
        ap.error(f"unknown phase(s) {bad}; choose from {sorted(PHASES)}")
    async with httpx.AsyncClient(base_url=a.api, timeout=30) as c:
        provider = (await c.get("/api/health")).json().get("provider")
        if why := refuse(provider, a.cloud):
            print(f"Refusing: {why}", file=sys.stderr)
            return 2
        run = uuid.uuid4().hex[:5]
        students = [Student(a.api, f"load{run}s{i:02d}") for i in range(a.students)]
        try:
            joined = await asyncio.gather(*(s.start(a.code, a.language) for s in students))
            print(json.dumps({"provider": provider, "run": run, "joined": sorted(set(joined))}))
            ok = True
            study = bool(a.next_chapter)
            for label, chapter in rounds(a.chapter, a.next_chapter):
                if label:
                    print(json.dumps({"thinking_s": a.think}))
                    await asyncio.sleep(a.think)
                for phase in phases:
                    before = await stats(c, provider)
                    rows = await asyncio.gather(
                        *(s.act(phase, chapter, a.level, a.timeout, study) for s in students)
                    )
                    out = summarize(label + phase, rows, before, await stats(c, provider))
                    ok &= all(r.get("status") in (None, "done") for r in rows)
                    print(json.dumps(out))
        finally:
            await asyncio.gather(*(s.client.aclose() for s in students))
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
