"""Phase 5.1: every row of the platform error contract through the whole app (mock profile).

For each fault: set it on the mock (/_mock/config), start a real student activity, follow the job
the UI polls, take screenshots of the screen while waiting and at the end, check coins.
    C:\\Python311\\python.exe audit/tools/contract_probe.py
"""

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

API, WEB, MOCK = "http://localhost:8000", "http://localhost:5174", "http://127.0.0.1:9000"
OUT = Path("audit/artifacts/contract")
OUT.mkdir(parents=True, exist_ok=True)
REPORT = []


def http(method, url, body=None, cookie=None):
    h = {"Content-Type": "application/json"}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt, st, hd = r.read().decode(), r.status, r.headers
    except urllib.error.HTTPError as e:
        txt, st, hd = e.read().decode(), e.code, e.headers
    try:
        return st, json.loads(txt), hd
    except Exception:
        return st, txt, hd


def mock(**cfg):
    return http("PATCH", f"{MOCK}/_mock/config", cfg)[1]


ORIGINAL = http("GET", f"{MOCK}/_mock/config")[1]


def student(lang="en"):
    nick = f"ct_{uuid.uuid4().hex[:6]}"
    st, _, hd = http("POST", f"{API}/api/auth/signup", {"nickname": nick, "password": "audit-pass-123", "ui_language": lang})
    cookie = hd["set-cookie"].split(";")[0]
    st, w, _ = http("POST", f"{API}/api/worlds/join", {"code": "OLIVE-7Q2"}, cookie)
    http("PUT", f"{API}/api/profile", {"finish": True}, cookie)
    for c in w["courses"]:
        st, j, _ = http("POST", f"{API}/api/placement/start", {"course_id": c["id"]}, cookie)
        if isinstance(j, dict) and j.get("job_id"):
            follow(j["job_id"], cookie, 120)
        st, s, _ = http("GET", f"{API}/api/placement/{c['id']}", None, cookie)
        http("POST", f"{API}/api/placement/finish", {"course_id": c["id"], "answers": [0] * len(s.get("questions", []))}, cookie)
    http("POST", f"{API}/api/wallet/demo-purchase", {"product": "coin_pack"}, cookie)
    return nick, cookie, w


def follow(job_id, cookie, timeout=240, page=None, tag=None):
    seen, t0, shot_taken = [], time.time(), False
    while time.time() - t0 < timeout:
        st, j, _ = http("GET", f"{API}/api/jobs/{job_id}", None, cookie)
        snap = {k: j.get(k) for k in ("status", "stage", "queue_position", "eta_s", "waiting_reason", "quick_mode", "error")}
        if not seen or seen[-1] != snap:
            seen.append(snap)
        if page and not shot_taken and (j.get("waiting_reason") or j.get("queue_position")):
            page.screenshot(path=str(OUT / f"{tag}-waiting.png"))
            shot_taken = True
        if j["status"] in ("done", "failed", "cancelled"):
            return j, seen
        time.sleep(1.0)
    return j, seen


def coins(cookie):
    return http("GET", f"{API}/api/wallet", None, cookie)[1]["coins"]


def ui(pw, cookie):
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    name, val = cookie.split("=", 1)
    ctx.add_cookies([{"name": name, "value": val, "domain": "localhost", "path": "/"}])
    return b, ctx.new_page()


def scenario(pw, tag, cfg, start, settle=None, lang="en"):
    """start(cookie, world) -> (url_for_ui, job_id)."""
    nick, cookie, w = student(lang)
    before = coins(cookie)
    mock(**cfg)
    b, page = ui(pw, cookie)
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    try:
        url, job = start(cookie, w)
        page.goto(WEB + url)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / f"{tag}-start.png"))
        if settle:
            time.sleep(settle)
            mock(**{k: ORIGINAL[k] for k in cfg})
        final, seen = follow(job, cookie, page=page, tag=tag) if job else ({}, [])
    finally:
        mock(**{k: ORIGINAL[k] for k in cfg})
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / f"{tag}-end.png"))
    body = page.locator("body").inner_text()[:1500]
    b.close()
    after = coins(cookie)
    row = {"scenario": tag, "fault": cfg, "final": {k: final.get(k) for k in ("status", "quick_mode", "error")},
           "states": seen, "coins": [before, after], "ui_text_end": body, "console_errors": errs[:5]}
    REPORT.append(row)
    print(f"\n== {tag}: {row['final']} coins {before}->{after}")
    for s in seen:
        print("   ", s)
    return row


def chapter(w, course_prefix, idx=0):
    c = next(c for c in w["courses"] if c["name"].startswith(course_prefix))
    return w["id"], c["id"], c["chapters"][idx]["id"]


LEVELS = iter(["beginner", "advanced", "intermediate"])


def studio_start(level, course="Calculus", idx=1):
    def go(cookie, w):
        wid, cid, ch = chapter(w, course, idx)
        st, r, _ = http("POST", f"{API}/api/studio/{ch}/generate", {"level": level, "pay": "me"}, cookie)
        print("   studio generate", st, r)
        return f"/worlds/{wid}/courses/{cid}/studio?chapter={ch}&level={level}", (r or {}).get("job_id")
    return go


def solo_start(text):
    def go(cookie, w):
        wid, cid, ch = chapter(w, "Calculus", 0)
        st, r, _ = http("POST", f"{API}/api/arena/solo", {"chapter_id": ch, "concept": "limit", "text": text}, cookie)
        print("   solo", st, r)
        return f"/worlds/{wid}/courses/{cid}/arena?chapter={ch}&level=intermediate", (r or {}).get("job_id")
    return go


def tutor_start(cookie, w):
    wid, cid, ch = chapter(w, "Calculus", 0)
    st, r, _ = http("POST", f"{API}/api/tutor/start", {"chapter_id": ch, "level": "intermediate"}, cookie)
    if r.get("job_id"):
        follow(r["job_id"], cookie, 120)
    sid = r["session_id"]
    st, r2, _ = http("POST", f"{API}/api/tutor/{sid}/turn", {"text": "Why is 0/0 not equal to 1?", "action": "message"}, cookie)
    print("   tutor turn", st, r2)
    return f"/worlds/{wid}/courses/{cid}/tutor/{sid}", (r2 or {}).get("job_id")


if __name__ == "__main__":
  with sync_playwright() as pw:
      # 1. quota exhausted + delay: every call refused for ~25 s, then the platform recovers
      scenario(pw, "quota", {"p_quota": 1.0, "quota_delay_s": 5.0}, solo_start("A limit 0/0 is indeterminate: factor and cancel the common factor, then substitute."), settle=25)
      # 2. mid saturated (503 + Retry-After), interactive → one retry then compact (Quick mode)
      scenario(pw, "mid503", {"p_503_mid": 1.0, "p_quota": 0.0}, studio_start("beginner"))
      # 3. 400 ceiling: max_tokens above 200 refused → shrink + resend once
      scenario(pw, "ceiling400", {"max_tokens_ceiling": 200, "p_503_mid": 0.0}, tutor_start)
      # 4. malformed JSON on every reply → one compact repair call, then fail cleanly
      scenario(pw, "badjson", {"p_bad_json": 1.0, "p_503_mid": 0.0}, solo_start("Factor the numerator, cancel x-a, and substitute again to find the limit."))
      # 5. 401 "Key is blocked" (platform outside slot) with LLM_PROVIDER=mock (not auto)
      scenario(pw, "blocked401", {"blocked": True}, studio_start("advanced", "Calculus", 1))
      # 6. timeout: mid answers after 100 s > LLM_TIMEOUT_S=90
      scenario(pw, "timeout", {"latency_mid_ms": [100000, 100000], "p_503_mid": 0.0}, studio_start("intermediate", "Calculus", 1))

  json.dump(REPORT, open("audit/logs/contract_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
  print("\nsaved audit/logs/contract_probe.json")
