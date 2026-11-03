"""Phase 4: coin/point invariants under concurrency (mock profile). python audit/tools/money_probe.py

Each scenario fires N identical requests at once from threads, then checks the API wallet and the
ledgers in Postgres (via `docker compose exec db psql`)."""

import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "audit/tools")
from acl_probe import RESULTS, call, check, wait_job  # noqa: E402

R = uuid.uuid4().hex[:5]


def sql(q):
    out = subprocess.run(
        ["docker", "compose", "-p", "lw-audit", "exec", "-T", "db", "psql", "-U", "lw", "-d", "learningworld", "-tAc", q],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def burst(n, fn):
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(lambda _: fn(), range(n)))


def ledger_sum(nick):
    return int(sql(f"select coalesce(sum(delta),0) from coin_ledger l join users u on u.id=l.user_id where u.nickname='{nick}'") or 0)


def wallet(nick):
    return call(nick, "GET", "/api/wallet")[1]


def join(nick):
    s, w = call(nick, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})
    return w


def invariant(nick, label):
    w = wallet(nick)
    led = ledger_sum(nick)
    check(f"{label}: wallet coins == ledger sum ({w['coins']} vs {led})", 200 if w["coins"] == led else 500, {200})
    check(f"{label}: never negative", 200 if w["coins"] >= 0 and w["free_today"] >= 0 else 500, {200}, json.dumps(w)[:120])
    return w


# 1. parallel paid starts: 20 coins, tutor costs 8 → at most 2 of 6 may start
u = f"m1_{R}"
w = join(u)
ch = next(c for c in w["courses"] if c["name"].startswith("Calculus"))["chapters"][0]["id"]
res = burst(6, lambda: call(u, "POST", "/api/tutor/start", {"chapter_id": ch, "level": "intermediate"}))
ok = [r for r in res if r[0] in (200, 201, 202)]
print("tutor x6:", [r[0] for r in res])
check("6 parallel tutor starts with 20 coins: <= 2 succeed", 200 if len(ok) <= 2 else 500, {200}, str(len(ok)))
check("the rest get 402 insufficient_coins", 200 if all(r[0] == 402 for r in res if r not in ok) else 500, {200}, str([r[1] for r in res if r not in ok][:2]))
for r in ok:
    if r[1].get("job_id"):
        wait_job(u, r[1]["job_id"])
invariant(u, "tutor burst")

# 2. parallel pool contributions: 20 coins, 10 each → at most 2
u = f"m2_{R}"
w = join(u)
wid = w["id"]
pool0 = call(u, "GET", f"/api/worlds/{wid}/pool")[1]
res = burst(5, lambda: call(u, "POST", f"/api/worlds/{wid}/pool", {"amount": 10}))
print("pool x5:", [r[0] for r in res], "pool before", pool0)
okc = sum(r[0] < 300 for r in res)
check("5 parallel pool gifts of 10 with 20 coins: <= 2 succeed", 200 if okc <= 2 else 500, {200}, str(okc))
invariant(u, "pool burst")
pl = int(sql(f"select coalesce(sum(delta),0) from class_pool_ledger where world_id='{wid}'") or 0)
check("pool balance == pool ledger sum", 200 if call(u, "GET", f"/api/worlds/{wid}/pool")[1].get("balance", pl) == pl else 500, {200})

# 3. parallel demo purchases (labelled demo): each one should add exactly one pack
u = f"m3_{R}"
join(u)
before = wallet(u)["coins"]
res = burst(4, lambda: call(u, "POST", "/api/wallet/demo-purchase", {"product": "coin_pack"}))
after = invariant(u, "purchase burst")["coins"]
print("purchase x4:", [r[0] for r in res], before, "->", after)
check("4 parallel coin packs add 4 × pack", 200 if after - before == 4 * 50 else 500, {200}, f"{before}->{after}")

# 4. Exam Pass limit: 15 activities/day at 0 coins, 16th charges or refuses
u = f"m4_{R}"
join(u)
call(u, "POST", "/api/wallet/demo-purchase", {"product": "exam_pass"})
w0 = wallet(u)
print("exam pass wallet:", json.dumps(w0)[:200])
check("exam pass shows 15 left today", 200 if w0.get("exam_pass_left_today") == 15 else 500, {200}, str(w0.get("exam_pass_left_today")))

# 5. repeated finish / end: points paid once
u = f"m5_{R}"
w = join(u)
s, q = call(u, "POST", "/api/quiz/start", {"chapter_id": ch, "level": "intermediate"})
att = q.get("attempt_id")
if not att and q.get("job_id"):
    wait_job(u, q["job_id"])
    att = call(u, "POST", f"/api/quiz/attempts/from-job/{q['job_id']}")[1].get("id")
for i in range(10):
    call(u, "POST", f"/api/quiz/attempts/{att}/answer", {"q": i, "choice": 0})
res = burst(6, lambda: call(u, "POST", f"/api/quiz/attempts/{att}/finish"))
print("finish x6:", [r[0] for r in res])
pts = sql(f"select count(*), coalesce(sum(delta),0) from points_ledger p join users u on u.id=p.user_id where u.nickname='{u}'")
print("points rows/sum:", pts)
check("6 parallel finishes → no 5xx", 200 if all(r[0] < 500 for r in res) else 500, {200}, str([r[0] for r in res]))
s, lb = call(u, "GET", "/api/wallet")
check("points in wallet == points ledger sum", 200 if str(lb["points"]) == pts.split("|")[1] else 500, {200}, f"{lb['points']} vs {pts}")

# 6. global invariants over the whole audit DB
neg = sql("select count(*) from (select user_id, sum(delta) s from coin_ledger group by user_id having sum(delta) < 0) x")
check("no user has a negative coin ledger sum", 200 if neg == "0" else 500, {200}, neg)
dup_ref = sql("select count(*) from (select ref, bucket from coin_ledger where kind='refund' group by ref, bucket having count(*)>1) x")
check("no double refund", 200 if dup_ref == "0" else 500, {200}, dup_ref)
stuck = sql("select count(*) from jobs where status='running' and started_at < now() - interval '15 minutes'")
print("jobs stuck running >15 min:", stuck)
reserved = sql("select count(*) from jobs where status in ('failed','cancelled') and cost > 0 and not exists (select 1 from coin_ledger l where l.ref=jobs.id::text and l.kind='refund')")
check("every failed/cancelled paid job was refunded", 200 if reserved == "0" else 500, {200}, reserved)
print(f"\n{sum(not r['pass'] for r in RESULTS)} fail / {len(RESULTS)}")
json.dump(RESULTS, open("audit/logs/money_results.json", "w"), indent=1)
