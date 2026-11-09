#!/usr/bin/env python3
"""Write one redacted debug bundle (Markdown) to debug/bundles/ (gitignored): what a person or the
bug-fixer agent reads first about a bug.

    ADMIN_TOKEN=… python3 scripts/debug_bundle.py --job <job id>
    ADMIN_TOKEN=… python3 scripts/debug_bundle.py --user <student id>
    ADMIN_TOKEN=… python3 scripts/debug_bundle.py --since 2026-11-09T10:00
    … --logs compose      # also append matching worker/backend log lines (docker compose logs)
    … --logs path/to.log  # or from a saved log file

The bundle comes from GET /api/admin/debug/bundle (job timeline, calls, traces if any, worker
heartbeat around that time, the student's invariants). Log lines are filtered to the job / student
ids plus warnings and errors, capped at 200, and redacted here the same way (keys, bearer tokens).
Standard library only. The admin token is read from the environment, never from the command line
or a file; the script never opens .env and makes no model call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "debug" / "bundles"
MAX_LOG_LINES = 200
# same shapes as backend/app/gateway/trace.py (scripts are standard library only)
SECRETS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|admin[_-]?token|secret[_-]?key|password|authorization)"
        r"(\s*[:=]\s*)[\"']?[^\s\"',}]{4,}"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
)


def redact(text: str) -> str:
    for rx in SECRETS:
        if rx.groups >= 2:
            text = rx.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
        else:
            text = rx.sub("[redacted]", text)
    return text


def fetch(api: str, params: dict[str, str]) -> dict:
    url = f"{api.rstrip('/')}/api/admin/debug/bundle?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    if token := os.environ.get("ADMIN_TOKEN"):
        req.add_header("X-Admin-Token", token)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def log_lines(source: str, ids: list[str], since: str | None) -> list[str]:
    if source == "compose":
        cmd = ["docker", "compose", "logs", "--no-color", "worker", "backend"]
        if since:
            cmd[3:3] = [f"--since={since}"]
        try:
            raw = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT).stdout
        except (OSError, subprocess.SubprocessError) as e:
            return [f"(could not read docker compose logs: {type(e).__name__})"]
    else:
        raw = Path(source).read_text(encoding="utf-8", errors="replace")
    keep = [
        line
        for line in raw.splitlines()
        if any(i and i in line for i in ids) or re.search(r"\b(WARNING|ERROR|Traceback)\b", line)
    ]
    return [redact(line) for line in keep[-MAX_LOG_LINES:]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job")
    g.add_argument("--user")
    g.add_argument("--since", help="ISO time; failed or deferred jobs since then")
    ap.add_argument("--logs", help="'compose' or a log file to filter and append")
    a = ap.parse_args()
    params = {k: v for k, v in {"job_id": a.job, "user": a.user, "since": a.since}.items() if v}
    try:
        data = fetch(a.api, params)
    except Exception as e:  # noqa: BLE001
        print(f"Could not read {a.api}/api/admin/debug/bundle: {e}")
        print("Is ADMIN_TOKEN set in this shell (any value in dev, the same as the API's)?")
        return 1
    md = data["markdown"]
    if a.logs:
        ids = [x for x in (a.job, a.user) if x] + re.findall(r"`([0-9a-f-]{36})`", md)
        lines = log_lines(a.logs, ids, a.since)
        md += "\n## Log lines (filtered, redacted)\n\n```\n" + "\n".join(lines) + "\n```\n"
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / data["name"]
    dest.write_text(md, encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}")  # ASCII: Windows consoles are often cp1252
    return 0


if __name__ == "__main__":
    sys.exit(main())
