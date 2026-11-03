"""Phase 3: access-control matrix + answer-leak checks against the running audit API (mock profile).

Users (X-Dev-User, dev only): alice + bob are members of the seed world W1 (OLIVE-7Q2), alice owns
the private objects; bob is a member but not the creator; carol owns her own world W2 and is NOT a
member of W1. Prints one line per check: PASS/FAIL, expected vs actual.

    python audit/tools/acl_probe.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

API = "http://127.0.0.1:8000"
RUN = uuid.uuid4().hex[:6]
RESULTS: list[dict] = []


def call(user, method, path, body=None, raw=None, ctype=None):
    data, headers = None, {"X-Dev-User": user} if user else {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if raw is not None:
        data, headers["Content-Type"] = raw, ctype
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt


def check(name, status, ok_codes, detail=""):
    ok = status in ok_codes
    RESULTS.append({"check": name, "status": status, "expected": sorted(ok_codes), "pass": ok})
    print(f"{'PASS' if ok else 'FAIL'}  {status}  {name}  {detail}")
    return ok


def wait_job(user, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s, j = call(user, "GET", f"/api/jobs/{job_id}")
        if s == 200 and j.get("status") in ("done", "failed", "cancelled"):
            return j
        time.sleep(1.5)
    return None


def multipart(filename: str, content: bytes, ctype="text/plain"):
    b = uuid.uuid4().hex
    body = (
        f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def leak_keys(obj, keys=("answer_index", "answer", "explanation", "hint", "correct")):
    found = []

    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and v not in (None, "", []):
                    found.append(path + "." + k)
                walk(v, path + "." + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(obj)
    return found


def main():
    global API
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=API)
    API = ap.parse_args().api

    A, B, C = f"alice_{RUN}", f"bob_{RUN}", f"carol_{RUN}"
    for u in (A, B):
        s, w1 = call(u, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})
        assert s == 200, (s, w1)
    W1 = w1["id"]
    course = w1["courses"][0]
    CO, CH = course["id"], course["chapters"][0]["id"]
    DOC = (course["chapters"][0].get("documents") or [{}])[0].get("id")
    s, w2 = call(C, "POST", "/api/worlds", {"name": f"Carol world {RUN}"})
    W2 = w2["id"]
    s, c2 = call(C, "POST", f"/api/worlds/{W2}/courses", {"name": "Carol course", "chapters": ["Ch1"]})
    print("setup", W1, CO, CH, DOC, "carol world", W2, s)

    # --- alice's private objects ---
    s, pl = call(A, "POST", "/api/placement/start", {"course_id": CO})
    pjob = pl.get("job_id") if isinstance(pl, dict) else None
    if pjob:
        wait_job(A, pjob)
    s, pset = call(A, "GET", f"/api/placement/{CO}")
    print("placement GET", s, "leaks:", leak_keys(pset))
    check("placement set hides answers/explanations", 200 if not leak_keys(pset) else 500, {200}, str(leak_keys(pset))[:200])

    s, q = call(A, "POST", "/api/quiz/start", {"chapter_id": CH, "level": "intermediate"})
    print("quiz start", s, str(q)[:200])
    attempt = None
    if isinstance(q, dict):
        attempt = q.get("attempt_id")
        if not attempt and q.get("job_id"):
            wait_job(A, q["job_id"])
            s2, a = call(A, "POST", f"/api/quiz/attempts/from-job/{q['job_id']}")
            attempt = a.get("id") or a.get("attempt_id") if isinstance(a, dict) else None
    qjob = q.get("job_id") if isinstance(q, dict) else None
    if attempt:
        s, att = call(A, "GET", f"/api/quiz/attempts/{attempt}")
        lk = leak_keys(att)
        check("fresh quiz attempt hides answer/hint/explanation", 200 if not lk else 500, {200}, str(lk)[:200])
        # wrong answer once -> hint may appear but not answer_index/explanation
        s, r1 = call(A, "POST", f"/api/quiz/attempts/{attempt}/answer", {"q": 0, "choice": 0})
        s, att2 = call(A, "GET", f"/api/quiz/attempts/{attempt}")
        lk2 = leak_keys(att2, keys=("answer_index", "explanation"))
        print("after 1 answer:", str(r1)[:200], "leaks", lk2)

    s, t = call(A, "POST", "/api/tutor/start", {"chapter_id": CH, "level": "intermediate"})
    tsess = t.get("session_id") or t.get("id") if isinstance(t, dict) else None
    tjob = t.get("job_id") if isinstance(t, dict) else None
    print("tutor start", s, str(t)[:160])

    s, aq = call(A, "POST", "/api/arena/questions", {"chapter_id": CH, "text": f"Why does a limit of 0/0 need algebra first? {RUN}"})
    qid = (aq.get("id") or aq.get("question_id")) if isinstance(aq, dict) else None
    if isinstance(aq, dict) and aq.get("job_id"):
        wait_job(A, aq["job_id"])
    print("arena ask", s, str(aq)[:160])
    ans_id = None
    if qid:
        s, an = call(B, "POST", f"/api/arena/questions/{qid}/answers", {"text": "Because direct substitution gives an indeterminate form, so we factor and cancel the common term first."})
        ans_id = (an.get("id") or an.get("answer_id")) if isinstance(an, dict) else None
        if isinstance(an, dict) and an.get("job_id"):
            wait_job(B, an["job_id"])
        print("bob answers", s, str(an)[:160])

    # --- carol (non-member of W1) ---
    deny = {401, 403, 404}
    for m, p, body in [
        ("GET", f"/api/worlds/{W1}", None),
        ("GET", f"/api/worlds/{W1}/map", None),
        ("GET", f"/api/worlds/{W1}/indexing", None),
        ("GET", f"/api/courses/{CO}", None),
        ("POST", f"/api/courses/{CO}/presence", {"chapter_id": CH}),
        ("GET", f"/api/placement/{CO}", None),
        ("POST", "/api/placement/start", {"course_id": CO}),
        ("GET", f"/api/quiz/price?chapter_id={CH}&level=intermediate", None),
        ("POST", "/api/quiz/start", {"chapter_id": CH, "level": "intermediate"}),
        ("POST", "/api/tutor/start", {"chapter_id": CH, "level": "intermediate"}),
        ("GET", f"/api/studio/{CH}?level=intermediate", None),
        ("GET", f"/api/studio/{CH}/price?level=intermediate", None),
        ("GET", f"/api/studio/{CH}/cards?level=intermediate", None),
        ("POST", f"/api/studio/{CH}/generate", {"level": "intermediate", "pay": "me"}),
        ("GET", f"/api/audio/{CH}?level=intermediate", None),
        ("POST", f"/api/audio/{CH}/generate", {"level": "intermediate", "pay": "me"}),
        ("GET", f"/api/arena/questions?chapter_id={CH}", None),
        ("POST", "/api/arena/questions", {"chapter_id": CH, "text": "intruder question here please"}),
        ("POST", "/api/arena/solo", {"chapter_id": CH, "concept": "limits", "text": "intruder solo answer text"}),
        ("GET", f"/api/wisdom?world_id={W1}", None),
        ("GET", f"/api/worlds/{W1}/pool", None),
        ("POST", f"/api/worlds/{W1}/pool", {"amount": 1}),
        ("GET", f"/api/leaderboard?scope=world&period=all&world_id={W1}", None),
        ("POST", f"/api/worlds/{W1}/courses", {"name": "intruder course"}),
        ("POST", f"/api/courses/{CO}/chapters", {"title": "intruder chapter"}),
        ("DELETE", f"/api/courses/{CO}", None),
    ]:
        s, r = call(C, m, p, body)
        check(f"non-member {m} {p.split('?')[0]}", s, deny, str(r)[:120] if s < 400 else "")
    if qid:
        s, r = call(C, "GET", f"/api/arena/questions/{qid}")
        check("non-member GET arena question", s, deny, str(r)[:120])
        s, r = call(C, "POST", f"/api/arena/questions/{qid}/answers", {"text": "intruder answer text that is long enough"})
        check("non-member answers arena question", s, deny, str(r)[:120])
    if ans_id:
        s, r = call(C, "POST", f"/api/arena/answers/{ans_id}/helpful")
        check("non-member votes helpful", s, deny, str(r)[:120])
    body, ct = multipart("intruder.txt", b"intruder text " * 50)
    s, r = call(C, "POST", f"/api/chapters/{CH}/documents", raw=body, ctype=ct)
    check("non-member uploads document", s, deny, str(r)[:120])
    if DOC:
        s, r = call(C, "DELETE", f"/api/documents/{DOC}")
        check("non-member deletes document", s, deny, str(r)[:120])

    # --- cross-user private objects (carol and bob vs alice) ---
    for who in (B, C):
        tag = "member-bob" if who == B else "non-member-carol"
        for jid, label in ((qjob, "quiz job"), (tjob, "tutor job"), (pjob, "placement job")):
            if jid:
                s, r = call(who, "GET", f"/api/jobs/{jid}")
                check(f"{tag} reads alice's {label}", s, deny, str(r)[:120])
                s, r = call(who, "POST", f"/api/jobs/{jid}/cancel")
                check(f"{tag} cancels alice's {label}", s, deny | {409}, str(r)[:120])
        if attempt:
            s, r = call(who, "GET", f"/api/quiz/attempts/{attempt}")
            check(f"{tag} reads alice's attempt", s, deny, str(r)[:120])
            s, r = call(who, "POST", f"/api/quiz/attempts/{attempt}/answer", {"q": 1, "choice": 1})
            check(f"{tag} answers in alice's attempt", s, deny, str(r)[:120])
            s, r = call(who, "POST", f"/api/quiz/attempts/{attempt}/finish")
            check(f"{tag} finishes alice's attempt", s, deny, str(r)[:120])
            s, r = call(who, "POST", f"/api/quiz/attempts/{attempt}/flashcards")
            check(f"{tag} makes flashcards from alice's attempt", s, deny, str(r)[:120])
        if tsess:
            s, r = call(who, "GET", f"/api/tutor/{tsess}")
            check(f"{tag} reads alice's tutor session", s, deny, str(r)[:120])
            s, r = call(who, "POST", f"/api/tutor/{tsess}/turn", {"text": "hi", "action": "message"})
            check(f"{tag} posts a turn in alice's tutor session", s, deny, str(r)[:120])
            s, r = call(who, "POST", f"/api/tutor/{tsess}/end")
            check(f"{tag} ends alice's tutor session", s, deny, str(r)[:120])

    # --- bob: member but not creator ---
    s, r = call(B, "POST", f"/api/worlds/{W1}/courses", {"name": "bob course"})
    check("member (not creator) adds course", s, {403}, str(r)[:120])
    s, r = call(B, "POST", f"/api/courses/{CO}/chapters", {"title": "bob chapter"})
    check("member (not creator) adds chapter", s, {403}, str(r)[:120])
    body, ct = multipart("bob.txt", b"bob text " * 50)
    s, r = call(B, "POST", f"/api/chapters/{CH}/documents", raw=body, ctype=ct)
    check("member (not creator) uploads", s, {403}, str(r)[:120])
    if DOC:
        s, r = call(B, "DELETE", f"/api/documents/{DOC}")
        check("member (not creator) deletes document", s, {403}, str(r)[:120])
    s, r = call(B, "DELETE", f"/api/courses/{CO}")
    check("member (not creator) deletes course", s, {403}, str(r)[:120])
    if ans_id:
        s, r = call(B, "POST", f"/api/arena/answers/{ans_id}/pin")
        check("non-author pins an answer", s, {403}, str(r)[:120])
        s, r = call(B, "POST", f"/api/arena/answers/{ans_id}/helpful")
        check("author votes own answer helpful", s, {400, 403, 409}, str(r)[:120])
    if qid:
        # peer feedback stays with its author: alice (question author) must not see bob's ai_feedback
        s, r = call(A, "GET", f"/api/arena/questions/{qid}")
        leaked = [k for k in ("ai_feedback", "feedback") if k in json.dumps(r)]
        check("question author does not see another student's AI feedback", 200 if not leaked else 500, {200}, str(leaked))
        s, r = call(B, "GET", f"/api/arena/questions/{qid}")
        print("bob (author of answer) view:", str(r)[:300])

    # --- carol's own world cannot be retrieved into W1 ---
    s, r = call(A, "GET", f"/api/worlds/{W2}")
    check("alice reads carol's world W2", s, deny, str(r)[:120])

    # --- unauthenticated ---
    for m, p in (("GET", "/api/wallet"), ("GET", f"/api/worlds/{W1}"), ("GET", "/api/daily"), ("GET", f"/api/jobs/{qjob or uuid.uuid4()}")):
        s, r = call(None, m, p)
        check(f"anonymous {m} {p}", s, {401}, str(r)[:80])

    s, r = call(None, "GET", "/api/admin/stats?provider=all")
    check("anonymous admin stats (ADMIN_TOKEN blank)", s, {401, 403}, str(r)[:80])

    fails = [r for r in RESULTS if not r["pass"]]
    print(f"\n{len(RESULTS)} checks, {len(fails)} fail")
    json.dump(RESULTS, open("audit/logs/acl_results.json", "w"), indent=1)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
