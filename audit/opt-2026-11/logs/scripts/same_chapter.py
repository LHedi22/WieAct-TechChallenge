"""Audit-only (not in the repo): N students on the SAME chapter at once, against the cc-opt mock stack.
Phases, each fired concurrently for all students: join -> studio generate -> quiz start -> tutor start.
Reports per phase: cost charged, distinct job ids (sharing), wait p50/p95, quick_mode, failures, and
/api/admin/stats deltas (calls per tier, repeated_identical). Dev auth via X-Dev-User (dev only)."""

import asyncio, json, os, sys, time, uuid
import httpx

API = os.environ.get("API", "http://backend:8000")
CH = os.environ["CHAPTER"]
LEVEL = os.environ.get("LEVEL", "advanced")
N = int(os.environ.get("N", "10"))
CODE = os.environ.get("CODE", "OLIVE-7Q2")
RUN = os.environ.get("RUN") or uuid.uuid4().hex[:5]
TOKEN = os.environ.get("ADMIN_TOKEN", "")


def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(round(q * (len(v) - 1))))], 1) if v else None


async def stats(c):
    r = await c.get("/api/admin/stats", params={"provider": "mock"}, headers={"X-Admin-Token": TOKEN})
    d = r.json()
    for t, v in (d.get("by_tier") or {}).items():
        d[t] = v.get("calls", 0)
    d["refusals"] = sum((d.get("refusals") or {}).values())
    for k, v in (d.get("by_task") or {}).items():
        d["task:" + k] = v
    return d


async def poll(c, user, job_id, t0):
    max_pos, eta0 = 0, None
    while True:
        v = (await c.get(f"/api/jobs/{job_id}", headers={"X-Dev-User": user})).json()
        if eta0 is None and v.get("eta_s") is not None:
            eta0 = v.get("eta_s")
        max_pos = max(max_pos, v.get("queue_position") or 0)
        if v["status"] in ("done", "failed", "cancelled") or time.monotonic() - t0 > 900:
            return {"status": v["status"], "wait_s": time.monotonic() - t0, "quick": v.get("quick_mode"),
                    "error": v.get("error"), "max_pos": max_pos, "first_eta_s": eta0}
        await asyncio.sleep(1.5)


async def student(c, i, phase):
    user = f"opt{RUN}s{i}"
    h = {"X-Dev-User": user}
    t0 = time.monotonic()
    if phase == "join":
        r = await c.post("/api/worlds/join", json={"code": CODE}, headers=h)
        return {"http": r.status_code}
    if phase == "buy":
        r = await c.post("/api/wallet/demo-purchase", json={"product": "coin_pack"}, headers=h)
        return {"http": r.status_code}
    if phase == "studio":
        r = await c.post(f"/api/studio/{CH}/generate", json={"level": LEVEL, "pay": "me"}, headers=h)
    elif phase == "quiz":
        r = await c.post("/api/quiz/start", json={"chapter_id": CH, "level": LEVEL}, headers=h)
    elif phase == "tutor":
        r = await c.post("/api/tutor/start", json={"chapter_id": CH, "level": LEVEL}, headers=h)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    out = {"http": r.status_code, "cost": body.get("cost"), "job": body.get("job_id"),
           "attempt": body.get("attempt_id"), "cached": body.get("cached")}
    if r.status_code == 200 and body.get("job_id"):
        out |= await poll(c, user, body["job_id"], t0)
    else:
        out["wait_s"] = time.monotonic() - t0
    return out


def summarize(phase, rows, before, after):
    waits = [r["wait_s"] for r in rows if "wait_s" in r]
    jobs = {r.get("job") for r in rows if r.get("job")}
    keys = ("calls", "compact", "mid", "embed", "repeated_identical", "cache_hits", "fallbacks", "refusals")
    keys += tuple(k for k in after if k.startswith("task:"))
    delta = {}
    for k in keys:
        a, b = after.get(k), before.get(k, 0)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[k] = a - b
    return {"phase": phase, "n": len(rows), "http": sorted({r["http"] for r in rows}),
            "costs": [r.get("cost") for r in rows], "distinct_jobs": len(jobs),
            "status": sorted({str(r.get("status")) for r in rows}), "quick": sum(1 for r in rows if r.get("quick")),
            "wait_p50": pct(waits, .5), "wait_p95": pct(waits, .95), "max_queue_pos": max([r.get("max_pos") or 0 for r in rows]),
            "first_eta_s": [r.get("first_eta_s") for r in rows if r.get("first_eta_s") is not None][:5],
            "stats_delta": delta, "errors": [r.get("error") for r in rows if r.get("error")]}


async def main():
    async with httpx.AsyncClient(base_url=API, timeout=60) as c:
        s0 = await stats(c)
        print("stats keys:", sorted(s0)[:40])
        for phase in os.environ.get("PHASES", "join,studio,quiz,tutor").split(","):
            b = await stats(c)
            rows = await asyncio.gather(*(student(c, i, phase) for i in range(N)))
            a = await stats(c)
            print(json.dumps(summarize(phase, rows, b, a)))
        s1 = await stats(c)
        print("TOTAL stats after:", json.dumps({k: s1[k] for k in s1 if not isinstance(s1[k], (list, dict))}))


asyncio.run(main())
