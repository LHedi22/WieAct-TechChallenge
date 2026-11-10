"""Stage the demo-video data in the world Explorer-Amira creates on camera (shot 03).

Run after shot 03 (the world exists and is indexing), on the host, with the compose stack up:
    C:/Python311/python.exe scripts/video/prepare.py [step ...]
Steps (default: all, in order): wait, users, placement, wisdom, packs, arena.
Everything goes through the real API and job pipeline (no fabricated content); the only DB reads
are staging helpers (world/chapter ids, which placement answers are right so each explorer lands on
the level the shots need). Accounts are synthetic nicknames; nothing here reads .env.
"""

from __future__ import annotations

import http.cookiejar
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name("state.json")
API = "http://127.0.0.1:8000"
PASSWORD = "explorer-demo-2026"
NICK = {"A": "Explorer-Amira", "B": "Explorer-Youssef", "C": "Explorer-Sami", "D": "Explorer-Lina"}
LANG = {"A": "en", "B": "ar", "C": "en", "D": "ar"}
WISDOM_STUDENTS = ("Explorer-Nour", "Explorer-Rami", "Explorer-Ines")
ARENA_QUESTION = (
    "Why is the limit of (sin x)/x as x approaches 0 equal to 1, when plugging in x = 0 gives 0/0?"
)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sql(q: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "lw", "-d", "learningworld",
         "-At", "-F", "\t", "-c", q],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()
    return [r.split("\t") for r in out.splitlines() if r]


class Client:
    def __init__(self, who: str):
        self.who = who
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, ok=(200, 201, 202, 204)):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req, timeout=120) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = raw.decode(errors="replace")
            if e.code in ok:
                return e.code, payload
            return e.code, payload

    def login_or_signup(self):
        st, _ = self.call("POST", "/api/auth/login", {"nickname": NICK[self.who], "password": PASSWORD})
        if st >= 300:
            st, b = self.call("POST", "/api/auth/signup", {
                "nickname": NICK[self.who], "password": PASSWORD, "ui_language": LANG[self.who]})
            assert st == 201, (st, b)
        return self

    def wait_job(self, job_id: str, timeout=1800):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st, b = self.call("GET", f"/api/jobs/{job_id}")
            if b and b.get("status") in ("done", "failed", "cancelled"):
                log(f"  job {job_id[:8]} {b['status']} ({int(time.time()-t0)} s)"
                    + (f" error={b.get('error')}" if b.get("status") != "done" else ""))
                return b
            time.sleep(3)
        raise TimeoutError(job_id)


def state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def world() -> dict:
    s = state()
    wid = s["worldId"]
    courses = {}
    for cid, cname in sql(f"select id, name from courses where world_id='{wid}'"):
        chs = sql(f"select id, idx, title from chapters where course_id='{cid}' order by idx")
        courses[cname] = {"id": cid, "chapters": [{"id": c[0], "idx": int(c[1]), "title": c[2]} for c in chs]}
    return {"id": wid, "code": s["code"], "courses": courses}


def step_wait():
    w = world()
    log("waiting for indexing + quiz pools in", w["code"])
    while True:
        docs = sql(f"""select d.status, count(*) from documents d join chapters c on c.id=d.chapter_id
                       join courses co on co.id=c.course_id where co.world_id='{w['id']}' group by 1""")
        pools = sql(f"select count(*) from quiz_sets where world_id='{w['id']}'")[0][0]
        log("  documents", docs, "quiz sets", pools)
        if docs and all(s == "ready" for s, _ in docs) and int(pools) >= 2:
            return
        if any(s == "failed" for s, _ in docs):
            raise SystemExit("a document failed to index")
        time.sleep(15)


def clients() -> dict[str, Client]:
    return {k: Client(k).login_or_signup() for k in NICK}


def step_users():
    w = world()
    for k, c in clients().items():
        c.call("PUT", "/api/profile", {"languages": [LANG[k]], "finish": True})
        st, b = c.call("POST", "/api/worlds/join", {"code": w["code"]})
        log(f"{NICK[k]} join: {st}")


def _placement(c: Client, course_id: str, target: str):
    st, b = c.call("POST", "/api/placement/start", {"course_id": course_id})
    if st == 409 or (isinstance(b, dict) and b.get("level")):
        log(f"  {NICK[c.who]} placement already done"); return
    if isinstance(b, dict) and b.get("job_id"):
        c.wait_job(b["job_id"])
    lang = LANG[c.who]
    rows = sql(f"select questions from placement_sets where course_id='{course_id}' and language='{lang}' "
               "order by created_at desc limit 1") if False else \
        sql(f"select questions from placement_sets where course_id='{course_id}' and language='{lang}' limit 1")
    qs = json.loads(rows[0][0])
    weight = {"beginner": 1, "intermediate": 2, "advanced": 3}
    total = sum(weight.get(q.get("difficulty", "intermediate"), 2) for q in qs)
    answers, earned = [], 0
    for q in qs:
        wq = weight.get(q.get("difficulty", "intermediate"), 2)
        right = target == "advanced" or (earned + wq) / total <= 0.62
        if right:
            earned += wq
        answers.append(q["answer_index"] if right else (q["answer_index"] + 1) % len(q["options"]))
    st, b = c.call("POST", "/api/placement/finish", {"course_id": course_id, "answers": answers})
    log(f"  {NICK[c.who]} placement → {st} {b.get('level') if isinstance(b, dict) else b}")


def step_placement():
    w = world()
    cs = clients()
    calc, ds = w["courses"]["Calculus I"]["id"], w["courses"]["Data Structures"]["id"]
    _placement(cs["A"], calc, "advanced")
    _placement(cs["A"], ds, "intermediate")
    for k in ("B", "C", "D"):
        _placement(cs[k], calc, "intermediate")
    _placement(cs["C"], ds, "intermediate")


def step_wisdom():
    w = world()
    code = f"""
import asyncio
from app.core import db
from app.jobs.worker import Worker
from app.seed.wisdom import seed_wisdom
async def main():
    sm = db.get_sessionmaker()
    jobs = await seed_wisdom(sm, {w['code']!r}, students={WISDOM_STUDENTS!r})
    print('tip jobs', jobs)
asyncio.run(main())
"""
    r = subprocess.run(["docker", "compose", "exec", "-T", "backend", "uv", "run", "python", "-c", code],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    log(r.stdout.strip()[-400:], r.stderr.strip()[-400:] if r.returncode else "")
    log("waiting for the tip")
    for _ in range(200):
        n = sql(f"select count(*) from wisdom_tips where world_id='{w['id']}'")[0][0]
        if int(n) > 0:
            log("  tips:", sql(f"select language, student_count from wisdom_tips where world_id='{w['id']}'"))
            return
        time.sleep(10)
    raise SystemExit("no tip")


def _pack(c: Client, kind: str, chapter_id: str, level: str):
    st, b = c.call("POST", f"/api/{kind}/{chapter_id}/generate", {"level": level, "pay": "me"})
    log(f"  {NICK[c.who]} {kind} {level}: {st} {b}")
    if isinstance(b, dict) and b.get("job_id"):
        j = c.wait_job(b["job_id"])
        if j["status"] != "done":
            raise SystemExit(f"{kind} failed")


def step_packs():
    w = world()
    cs = clients()
    ch1 = w["courses"]["Calculus I"]["chapters"][0]["id"]
    for k in ("A", "C"):  # clearly labelled demo purchase (the shots spend more than a day's coins)
        cs[k].call("POST", "/api/wallet/demo-purchase", {"product": "coin_pack"})
    # Packs at intermediate: on the laptop the local mid model misses its budget and the compact
    # fallback's 700-token notes only fit at this level (advanced notes were cut off: BadOutput).
    _pack(cs["D"], "studio", ch1, "intermediate")   # Arabic pack; B opens it free on the phone
    _pack(cs["C"], "studio", ch1, "intermediate")   # English pack; A opens it free (shot 09)
    _pack(cs["C"], "audio", ch1, "intermediate")    # English episode (shot 11)


def step_arena():
    w = world()
    c = clients()["C"]
    ch1 = w["courses"]["Calculus I"]["chapters"][0]["id"]
    st, b = c.call("GET", f"/api/arena/questions?chapter_id={ch1}")
    if isinstance(b, dict) and any(ARENA_QUESTION[:30] in json.dumps(q) for q in b.get("questions", [])):
        log("question already asked"); return
    st, b = c.call("POST", "/api/arena/questions", {"chapter_id": ch1, "text": ARENA_QUESTION})
    log("ask:", st, b)
    if isinstance(b, dict) and b.get("job_id"):
        c.wait_job(b["job_id"])


STEPS = {"wait": step_wait, "users": step_users, "placement": step_placement,
         "wisdom": step_wisdom, "packs": step_packs, "arena": step_arena}

if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    for name in sys.argv[1:] or list(STEPS):
        log("==", name)
        STEPS[name]()
    log("done")
