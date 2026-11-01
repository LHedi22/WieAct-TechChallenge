#!/usr/bin/env python3
"""Export /api/admin/stats as a Markdown table for the report (the same numbers the organisers
compute on our key: calls per tier, compact/mid split, tokens, cache hits, repeated identical
requests, refusals and how they were handled).

    python3 scripts/export_stats.py                                  # local API, provider=cloud
    python3 scripts/export_stats.py --api https://<site> --load scripts/out/load-cloud.txt
    ADMIN_TOKEN=… python3 scripts/export_stats.py --api https://<site>

Writes docs/report/stats-<provider>-<date>.md. `--load` appends a saved `scripts/load.py` output.
Standard library only. The admin token is read from the environment, never from the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(api: str, provider: str) -> dict:
    req = urllib.request.Request(f"{api.rstrip('/')}/api/admin/stats?provider={provider}")
    if token := os.environ.get("ADMIN_TOKEN"):
        req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def render(s: dict, load: str | None) -> str:
    chat = {k: v for k, v in s["by_tier"].items() if k != "embed"}
    chat_calls = sum(v["calls"] for v in chat.values()) or 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [
        f"# AI usage — provider `{s['provider']}` · {now}",
        "",
        "Source: `/api/admin/stats` (our `ai_call_log`; cache hits are served without a call).",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Calls to the platform (incl. retries) | {s['calls']} |",
        f"| Answered 200 | {s['ok']} |",
        f"| Compact share of chat calls | {s['compact_share']:.0%} |",
        f"| Served from cache (no call) | {s['cache_hits']} |",
        f"| Repeated identical requests | {s['repeated_identical']} |",
        f"| Compact fallbacks (Quick mode) | {s['fallbacks']} |",
        "",
        "| Tier | Calls | Share | Tokens in | Tokens out | Avg latency |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for tier, v in s["by_tier"].items():
        share = "—" if tier == "embed" else f"{v['calls'] / chat_calls:.0%}"
        out.append(
            f"| {tier} | {v['calls']} | {share} | {v['tokens_in']} | {v['tokens_out']} | "
            f"{v['avg_latency_ms'] / 1000:.1f} s |"
        )
    out += ["", "| Refusal | Count | Handling |", "| --- | --- | --- |"]
    handling = {
        "quota": "job requeued with the stated delay; queue position + ETA shown",
        "saturated": "interactive: one retry, then compact (Quick mode); background: retry later",
        "ceiling": "request shrunk (max_tokens / chunks / history) and resent once",
    }
    for k, n in s["refusals"].items():
        out.append(f"| {k} | {n} | {handling.get(k, '')} |")
    out += ["", "| Task | Calls |", "| --- | --- |"]
    out += [f"| {k} | {n} |" for k, n in sorted(s["by_task"].items(), key=lambda x: -x[1])]
    if s.get("quota_headers_seen"):
        out += ["", f"Quota headers seen: {', '.join(s['quota_headers_seen'])}"]
    if load:
        out += ["", "## Load test (`scripts/load.py`)", "", "```", load.strip(), "```"]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--provider", default="cloud", choices=["cloud", "local", "mock", "all"])
    ap.add_argument("--load", type=Path, help="a saved scripts/load.py output to append")
    a = ap.parse_args()
    try:
        stats = fetch(a.api, a.provider)
    except Exception as e:  # noqa: BLE001
        print(f"Could not read {a.api}/api/admin/stats: {e}")
        return 1
    md = render(stats, a.load.read_text() if a.load else None)
    dest = ROOT / "docs" / "report" / f"stats-{a.provider}-{datetime.now():%Y%m%d-%H%M}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(md)
    print(md)
    print(f"→ {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
