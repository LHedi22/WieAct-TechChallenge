"""Audit-only: stats over llm_logger lines [start, end) — max in flight, max chat calls in any 60 s window, repeated identical 200 bodies."""
import json, sys, collections
f, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = [json.loads(l) for i, l in enumerate(open(f)) if a <= i < b]
chat = [r for r in rows if r.get("path", "").endswith("/chat/completions")]
emb = [r for r in rows if r.get("path", "").endswith("/embeddings")]
ts = sorted(r["ts"] for r in chat)
j = 0; best = 0
for i, t in enumerate(ts):
    while ts[j] < t - 60: j += 1
    best = max(best, i - j + 1)
ok = [r["body_sha"] for r in chat if r.get("status") == 200 and r.get("body_sha")]
rep = sum(c - 1 for c in collections.Counter(ok).values() if c > 1)
print(json.dumps({"lines": len(rows), "chat_calls": len(chat), "embed_calls": len(emb),
  "status": dict(collections.Counter(str(r.get("status")) for r in chat)),
  "by_model": dict(collections.Counter(r.get("model") for r in chat)),
  "max_in_flight": max([r.get("in_flight", 0) for r in rows] or [0]),
  "max_chat_calls_in_60s_window": best, "repeated_identical_200_bodies": rep,
  "faults": dict(collections.Counter(str(r.get("fault")) for r in chat))}))
