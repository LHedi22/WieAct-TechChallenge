"""Shot 13 helpers (dev stack only, no admin token needed or shown):

    C:/Python311/python.exe scripts/video/stats_page.py stats      # → raw/stats.json + raw/stats.html
    C:/Python311/python.exe scripts/video/stats_page.py offline on|auto

`stats` calls the same function as GET /api/admin/stats inside the backend container, for the
provider the demo ran on (local) and for cloud (our in-slot calls), and renders them as a page.
`offline` flips the offline_demo_mode runtime switch (what the admin Switches page does) so the
banner can be filmed for two seconds; always set it back to `auto` afterwards.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "docs/report/video/raw"


def in_backend(code: str) -> str:
    r = subprocess.run(["docker", "compose", "exec", "-T", "backend", "uv", "run", "python", "-c", code],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(r.stderr[-2000:])
    return r.stdout.strip().splitlines()[-1]


STATS = """
import asyncio, json
from app.core import db
from app.admin.stats import stats
async def main():
    out = {}
    async with db.get_sessionmaker()() as s:
        for p in ("local", "cloud"):
            out[p] = (await stats(None, s, p)).model_dump()
    print(json.dumps(out))
asyncio.run(main())
"""

OFFLINE = """
import asyncio
from app.core import db, flags
async def main():
    async with db.get_sessionmaker()() as s:
        await flags.write(s, "offline_demo_mode", {v!r}, "video-recording")
        await s.commit()
    print("ok")
asyncio.run(main())
"""


def bar(label: str, n: int, total: int, color: str) -> str:
    pct = 100 * n / total if total else 0
    return (f'<div class="row"><span class="lab">{html.escape(label)}</span>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<span class="num">{n}</span></div>')


def render(data: dict) -> str:
    loc, cloud = data["local"], data["cloud"]
    tiers = loc["by_tier"]
    compact, mid = tiers.get("compact", {}).get("calls", 0), tiers.get("mid", {}).get("calls", 0)
    embed = tiers.get("embed", {}).get("calls", 0)
    tasks = sorted(loc["by_task"].items(), key=lambda kv: -kv[1])[:9]
    tmax = max([n for _, n in tasks] or [1])
    refusals = ", ".join(f"{k} {v}" for k, v in loc["refusals"].items()) or "none"
    task_rows = "".join(bar(k, n, tmax, "#2f7fb5") for k, n in tasks)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>AI usage report</title><style>
body{{margin:0;background:#f7f3ea;font-family:'Segoe UI',system-ui,sans-serif;color:#16324a}}
.wrap{{max-width:1280px;margin:0 auto;padding:40px 48px}}
h1{{font-size:40px;margin:0}} .sub{{color:#5d6f7d;margin:6px 0 28px;font-size:18px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}}
.card{{background:#fff;border:3px solid #16324a;border-radius:6px;padding:18px 20px;box-shadow:4px 4px 0 #16324a}}
.k{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:#5d6f7d}} .v{{font-size:46px;font-weight:700;margin-top:4px}}
.small{{font-size:15px;color:#5d6f7d}}
.split{{display:flex;height:34px;border:3px solid #16324a;border-radius:6px;overflow:hidden;margin:10px 0}}
.split div{{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700}}
.two{{display:grid;grid-template-columns:1.1fr 1fr;gap:18px;margin-top:18px}}
.row{{display:flex;align-items:center;gap:10px;margin:7px 0}} .lab{{width:170px;font-size:15px;font-family:Consolas,monospace}}
.track{{flex:1;height:16px;background:#eee4d2;border-radius:3px}} .fill{{height:100%;border-radius:3px}} .num{{width:40px;text-align:end;font-weight:700}}
ul{{margin:8px 0 0;padding-inline-start:20px;line-height:1.7;font-size:17px}}
</style></head><body><div class="wrap">
<h1>AI usage report</h1>
<div class="sub">From <code>/api/admin/stats</code> · this demo session ran on our local open-source models (provider = local) ·
platform key in-slot: {cloud['calls']} calls, compact share {cloud['compact_share']*100:.0f}%</div>
<div class="grid">
 <div class="card"><div class="k">Model calls</div><div class="v">{loc['calls']}</div><div class="small">{loc['ok']} ok · {embed} embedding batches</div></div>
 <div class="card"><div class="k">Compact share</div><div class="v">{loc['compact_share']*100:.0f}%</div><div class="small">mid only where reasoning pays</div></div>
 <div class="card"><div class="k">Cache hits</div><div class="v">{loc['cache_hits']}</div><div class="small">shared class content, no new call</div></div>
 <div class="card"><div class="k">Repeated identical</div><div class="v">{loc['repeated_identical']}</div><div class="small">the organisers' cache indicator</div></div>
</div>
<div class="two">
 <div class="card"><div class="k">Calls per task</div>{task_rows}</div>
 <div class="card"><div class="k">Model routing</div>
  <div class="split"><div style="width:{100*compact/max(1,compact+mid):.0f}%;background:#5b8c3a">compact {compact}</div>
  <div style="width:{100*mid/max(1,compact+mid):.0f}%;background:#c0623a">mid {mid}</div></div>
  <ul><li>Escalation, draft-then-revise, plan-once, narrow-before-generating</li>
  <li>Fallbacks to Quick mode: {loc['fallbacks']} · refusals handled: {html.escape(refusals)}</li>
  <li>Every AI action is a queued job: 2 in flight, interactive before background</li>
  <li>Offline demo mode serves saved results only</li>
  <li>Nicknames only: no real names, photos, emails or voices stored</li></ul></div>
</div></div></body></html>"""


def main():
    cmd = sys.argv[1]
    if cmd == "stats":
        data = json.loads(in_backend(STATS))
        (RAW / "stats.json").write_text(json.dumps(data, indent=2))
        (RAW / "stats.html").write_text(render(data), encoding="utf-8")
        print(json.dumps(data["local"], indent=1)[:1500])
    elif cmd == "offline":
        print(in_backend(OFFLINE.format(v=sys.argv[2])))


if __name__ == "__main__":
    main()
