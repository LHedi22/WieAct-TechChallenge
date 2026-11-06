"""Phase 3/4: arena permissions + quiz reveal rules + double-submit, without destructive calls.
python audit/tools/arena_quiz_probe.py"""

import json
import sys
import time
import uuid

sys.path.insert(0, "audit/tools")
from acl_probe import call, check, wait_job, RESULTS  # noqa: E402

R = uuid.uuid4().hex[:6]
A, B, C = f"qa_{R}", f"qb_{R}", f"qc_{R}"
for u in (A, B, C):
    s, w = call(u, "POST", "/api/worlds/join", {"code": "OLIVE-7Q2"})
course = next(c for c in w["courses"] if c["name"].startswith("Calculus"))
CH = course["chapters"][0]["id"]

# --- quiz reveal: wrong answer -> hint only; second wrong -> answer+explanation
s, q = call(A, "POST", "/api/quiz/start", {"chapter_id": CH, "level": "intermediate"})
if q.get("job_id"):
    wait_job(A, q["job_id"])
    s, a = call(A, "POST", f"/api/quiz/attempts/from-job/{q['job_id']}")
    att_id = a.get("id") or a.get("attempt_id")
else:
    att_id = q["attempt_id"]
s, att = call(A, "GET", f"/api/quiz/attempts/{att_id}")
print("attempt keys:", list(att.keys()), "q0 keys:", list(att["questions"][0].keys()) if att.get("questions") else None)
qi = att.get("current", 0)
opts = att["questions"][qi]["options"]
wrong = next(i for i, o in enumerate(opts) if "misconception" in o.lower()) if any("misconception" in o.lower() for o in opts) else 1
s, r1 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": qi, "choice": wrong})
print("wrong #1 ->", json.dumps(r1)[:400])
check("after 1st wrong: no answer_index/explanation", 200 if not any(k in r1 and r1[k] not in (None, "") for k in ("answer_index", "explanation")) else 500, {200})
check("after 1st wrong: hint present", 200 if r1.get("hint") else 500, {200}, str(r1.get("status")))
s, r2 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": qi, "choice": wrong})
print("wrong #2 ->", json.dumps(r2)[:400])
s, r3 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": qi, "choice": wrong})
check("3rd answer on a finished question is rejected", s, {400, 409}, json.dumps(r3)[:200])
# answer a question ahead of current
s, r4 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": 9, "choice": 0})
check("answering a future question out of order is rejected", s, {400, 409}, json.dumps(r4)[:200])
s, r5 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": 99, "choice": 0})
check("answering q=99 is rejected (not 500)", s, {400, 404, 409, 422}, json.dumps(r5)[:200])
s, r6 = call(A, "POST", f"/api/quiz/attempts/{att_id}/answer", {"q": qi + 1, "choice": 99})
check("choice=99 is rejected (not 500)", s, {400, 409, 422}, json.dumps(r6)[:200])

# --- arena: A asks, B answers, C votes; B can't pin; A pins; B can't self-vote
s, aq = call(A, "POST", "/api/arena/questions", {"chapter_id": CH, "text": f"How do we compute a limit that gives 0/0? ({R})"})
wait_job(A, aq["job_id"])
qid = aq["question_id"]
s, an = call(B, "POST", f"/api/arena/questions/{qid}/answers", {"text": "Direct substitution gives 0/0, an indeterminate form. Factor numerator and denominator, cancel the common factor (x-a), then substitute again."})
wait_job(B, an["job_id"])
aid = an["answer_id"]
s, an2 = call(B, "POST", f"/api/arena/questions/{qid}/answers", {"text": "Second answer by the same student to the same question."})
check("a student cannot post two answers to one question", s, {400, 409}, json.dumps(an2)[:160])
s, r = call(B, "POST", f"/api/arena/answers/{aid}/pin")
check("answer author (not question author) cannot pin", s, {403}, json.dumps(r)[:160])
s, r = call(B, "POST", f"/api/arena/answers/{aid}/helpful")
check("author cannot vote own answer helpful", s, {400, 403, 409}, json.dumps(r)[:160])
s, r = call(C, "POST", f"/api/arena/answers/{aid}/helpful")
check("classmate votes helpful", s, {200, 201, 204})
s, r = call(C, "POST", f"/api/arena/answers/{aid}/helpful")
check("double helpful vote is idempotent", s, {200, 201, 204, 409}, json.dumps(r)[:160])
s, qa = call(A, "GET", f"/api/arena/questions/{qid}")
print("question view as asker:", json.dumps(qa)[:700])
s, qb = call(B, "GET", f"/api/arena/questions/{qid}")
print("question view as answerer:", json.dumps(qb)[:700])
s, qc = call(C, "GET", f"/api/arena/questions/{qid}")
fb_c = "ai_feedback" in json.dumps(qc) and json.dumps(qc).count("ai_feedback") and any(
    (x.get("ai_feedback") not in (None, {}, [])) for x in qc.get("answers", []) if isinstance(x, dict)
)
check("third student does not see B's AI feedback", 200 if not fb_c else 500, {200})
s, r = call(A, "POST", f"/api/arena/answers/{aid}/pin")
check("question author pins", s, {200, 201, 204}, json.dumps(r)[:160])
s, r = call(A, "POST", f"/api/arena/answers/{aid}/pin")
check("pinning twice pays once (status ok)", s, {200, 201, 204, 409}, json.dumps(r)[:160])
s, lb = call(B, "GET", "/api/wallet")
print("B wallet:", json.dumps(lb)[:400])
print(f"\n{sum(not r['pass'] for r in RESULTS)} fail / {len(RESULTS)}")
