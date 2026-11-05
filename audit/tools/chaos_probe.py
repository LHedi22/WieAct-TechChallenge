"""Phase 5.3/5.4: dependency outages through the app (mock profile). Toxiproxy is not installed on this
laptop, so outages are made with `docker stop/start` and the mock's fault switches.
    PYTHONIOENCODING=utf-8 python audit/tools/chaos_probe.py"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, "audit/tools")
from acl_probe import call  # noqa: E402

MOCK = "http://127.0.0.1:9000"
OUT = []
P = os.environ.get("AUDIT_PROJECT", "lw-audit")  # compose project whose containers are stopped
ONLY = set(sys.argv[1:]) or {"1", "2", "3", "4"}  # scenarios to run (each fits a 10-min step)


def mock(**cfg):
    req = urllib.request.Request(f"{MOCK}/_mock/config", data=json.dumps(cfg).encode(), headers={"Content-Type": "application/json"}, method="PATCH")
    return json.load(urllib.request.urlopen(req))


def docker(*a):
    return subprocess.run(["docker", *a], capture_output=True, text=True).stdout.strip()


def follow(u, job, timeout=240):
    t0, states = time.time(), []
    while time.time() - t0 < timeout:
        s, j = call(u, "GET", f"/api/jobs/{job}")
        if s != 200:
            states.append(f"GET job -> {s}")
            time.sleep(2)
            continue
        snap = (j["status"], j.get("waiting_reason"), j.get("error"))
        if not states or states[-1] != snap:
            states.append(snap)
        if j["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(2)
    return states, round(time.time() - t0)


def student():
    u = f"ch_{uuid.uuid4().hex[:5]}"
    w = call(u, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})[1]
    ch = next(c for c in w["courses"] if c["name"].startswith("Calculus"))["chapters"][0]["id"]
    call(u, "POST", "/api/wallet/demo-purchase", {"product": "coin_pack"})
    return u, ch


def record(name, u, start_resp, states, secs, coins_before):
    coins_after = call(u, "GET", "/api/wallet")[1]["coins"]
    row = {"scenario": name, "start": start_resp, "states": states, "seconds": secs, "coins": [coins_before, coins_after]}
    OUT.append(row)
    print(f"\n== {name}: start={start_resp} after {secs}s coins {coins_before}->{coins_after}")
    for s in states:
        print("    ", s)


# 1. Embeddings failing while chat works: tutor start needs a query embedding (narrow-before-generating)
if "1" in ONLY:
    u, ch = student()
    c0 = call(u, "GET", "/api/wallet")[1]["coins"]
    mock(p_503_embed=1.0)
    try:
        s, r = call(u, "POST", "/api/tutor/start", {"chapter_id": ch, "level": "beginner"})
        states, secs = follow(u, r["job_id"], 150) if isinstance(r, dict) and r.get("job_id") else ([], 0)
    finally:
        mock(p_503_embed=0.0)
    record("embeddings 503 (chat up)", u, (s, r), states, secs, c0)

# 2. Qdrant down for 40 s while a tutor session starts
if "2" in ONLY:
    u, ch = student()
    c0 = call(u, "GET", "/api/wallet")[1]["coins"]
    docker("stop", f"{P}-qdrant-1")
    try:
        s, r = call(u, "POST", "/api/tutor/start", {"chapter_id": ch, "level": "advanced"})
        hs, health = call(None, "GET", "/api/health")
        print("health while qdrant down:", hs, health)
        time.sleep(40)
    finally:
        docker("start", f"{P}-qdrant-1")
    states, secs = follow(u, r["job_id"], 200) if isinstance(r, dict) and r.get("job_id") else ([], 0)
    record("qdrant down 40 s", u, (s, r), states, secs, c0)

# 3. Postgres restart while a study pack is running
if "3" in ONLY:
    u, ch = student()
    c0 = call(u, "GET", "/api/wallet")[1]["coins"]
    s, r = call(u, "POST", f"/api/studio/{ch}/generate", {"level": "intermediate", "pay": "me"})
    time.sleep(3)
    docker("restart", f"{P}-db-1")
    time.sleep(10)
    states, secs = follow(u, r["job_id"], 240) if isinstance(r, dict) and r.get("job_id") else ([], 0)
    record("postgres restart mid-job", u, (s, r), states, secs, c0)
    hs, health = call(None, "GET", "/api/health")
    print("health after db restart:", hs, health)

# 4. API restart while a job runs (worker untouched): the job must finish, polling must resume
if "4" in ONLY:
    u, ch = student()
    c0 = call(u, "GET", "/api/wallet")[1]["coins"]
    s, r = call(u, "POST", "/api/tutor/start", {"chapter_id": ch, "level": "intermediate"})
    docker("restart", f"{P}-backend-1")
    time.sleep(15)
    states, secs = follow(u, r["job_id"], 200) if isinstance(r, dict) and r.get("job_id") else ([], 0)
    record("API restart mid-job", u, (s, r), states, secs, c0)

json.dump(OUT, open(f"audit/logs/chaos_probe-{'-'.join(sorted(ONLY))}.json", "w"), indent=1, default=str)
