#!/usr/bin/env python3
"""Load test: N students start AI jobs at once against the running stack (mock by default).

    cd backend && uv run python ../scripts/load.py --jobs 30 --faults 503,quota

Turns on mock faults through /_mock/config, fires the jobs (a third interactive, the rest
background), polls each like the UI (every 1.5 s), then reports wait times, the highest queue
position seen, max concurrency at the mock, fallbacks and refusals from /api/admin/stats.
Exits non-zero if any job did not finish, or more than 2 calls were ever in flight.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx

TERMINAL = {"done", "failed", "cancelled"}
FAULTS = {"503": {"p_503_mid": 0.35}, "quota": {"p_quota": 0.15, "quota_delay_s": 3}}


async def run_job(client: httpx.AsyncClient, lane: str, poll_s: float, timeout_s: float) -> dict:
    t0 = time.monotonic()
    created = await client.post("/api/dev/demo-jobs", json={"lane": lane})
    created.raise_for_status()
    job_id = created.json()["job_id"]
    max_pos = 0
    while True:
        view = (await client.get(f"/api/jobs/{job_id}")).json()
        max_pos = max(max_pos, view.get("queue_position") or 0)
        if view["status"] in TERMINAL or time.monotonic() - t0 > timeout_s:
            return {
                "lane": lane,
                "status": view["status"],
                "wait_s": time.monotonic() - t0,
                "max_queue_position": max_pos,
                "quick_mode": view["quick_mode"],
                "error": view.get("error"),
            }
        await asyncio.sleep(poll_s)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows pipes default to cp1252
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--mock", default="http://127.0.0.1:9000")
    ap.add_argument("--jobs", "--students", type=int, default=30, dest="jobs")
    ap.add_argument("--faults", default="503,quota", help="comma list: 503, quota (empty = none)")
    ap.add_argument("--latency", default="800-2500", help="mock mid latency ms (compact is 1/3)")
    ap.add_argument("--poll", type=float, default=1.5)
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()

    async with httpx.AsyncClient(base_url=a.mock, timeout=10) as mock:
        original = (await mock.get("/_mock/config")).json()
        lo, hi = (int(x) for x in a.latency.split("-"))
        changes: dict = {
            "latency_mid_ms": [lo, hi],
            "latency_compact_ms": [lo // 3, hi // 3],
            "p_503_mid": 0.0,
            "p_quota": 0.0,
            "p_bad_json": 0.05,
        }
        for f in filter(None, a.faults.split(",")):
            changes |= FAULTS[f.strip()]
        await mock.patch("/_mock/config", json=changes)
        await mock.delete("/_mock/stats")
        try:
            async with httpx.AsyncClient(base_url=a.api, timeout=30) as api:
                before = (await api.get("/api/admin/stats", params={"provider": "mock"})).json()
                lanes = ["interactive" if i % 3 == 0 else "background" for i in range(a.jobs)]
                print(
                    f"firing {a.jobs} jobs ({lanes.count('interactive')} interactive), "
                    f"faults: {a.faults or 'none'} …"
                )
                t0 = time.monotonic()
                results = await asyncio.gather(
                    *[run_job(api, lane, a.poll, a.timeout) for lane in lanes]
                )
                total = time.monotonic() - t0
                after = (await api.get("/api/admin/stats", params={"provider": "mock"})).json()
            mock_stats = (await mock.get("/_mock/stats")).json()
        finally:
            await mock.patch("/_mock/config", json={k: original[k] for k in changes})

    done = [r for r in results if r["status"] == "done"]
    waits = [r["wait_s"] for r in results]
    by_lane = {
        lane: [r["wait_s"] for r in results if r["lane"] == lane]
        for lane in ("interactive", "background")
    }
    refusals = {k: v - before["refusals"].get(k, 0) for k, v in after["refusals"].items()}
    fallbacks = after["fallbacks"] - before["fallbacks"]
    print(f"\nfinished in {total:.0f} s")
    print(f"jobs done            {len(done)}/{len(results)}")
    print(f"wait p50 / p95       {pct(waits, 0.5):.1f} s / {pct(waits, 0.95):.1f} s")
    for lane, w in by_lane.items():
        if w:
            print(f"  {lane:<18} p50 {pct(w, 0.5):.1f} s · p95 {pct(w, 0.95):.1f} s")
    print(f"max queue position   {max(r['max_queue_position'] for r in results)}")
    print(f"max concurrency      {mock_stats['max_concurrency_seen']} (mock-side)")
    print(f"calls at the mock    {mock_stats['calls']} · by status {mock_stats['by_status']}")
    print(f"quick-mode jobs      {sum(r['quick_mode'] for r in results)} · fallbacks {fallbacks}")
    print(f"refusals handled     {refusals or '-'}")
    failed = [r for r in results if r["status"] != "done"]
    for r in failed[:5]:
        print(f"  ! {r['lane']} job ended {r['status']} ({r['error']})")

    ok = not failed and mock_stats["max_concurrency_seen"] <= 2
    if "503" in a.faults and fallbacks == 0:
        print("  ! no fallback observed despite 503 faults")
        ok = False
    print("\nRESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
