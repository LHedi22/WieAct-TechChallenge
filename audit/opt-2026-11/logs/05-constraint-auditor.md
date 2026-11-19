# constraint-auditor pass (read-only, 13 Nov 2026, HEAD ba1a36c) — summary + verification

The agent read the backend; it ran nothing. Each claim below was re-checked by hand (file:line) before use in
REPORT.md. "Verified" = I read the lines; "corrected" = the agent's reading was wrong.

| Agent ID | Claim | Verification |
| --- | --- | --- |
| A1 | `QuotaState.low` stays true forever when no reset header arrives → background stalls | **corrected.** `quota.py:31-34` `resume_in_s()` returns 0 when `reset_s is None`, and the limiter pauses only on `resume_in_s()` (`gateway/service.py:114`, `limiter.py:119-121`). With the platform's headers (no reset, DECISIONS.md 2026-11-09) the background lane therefore **never** pauses on low quota. Opposite failure, same root cause → OPT-06. |
| A2 | Limiter process-local; `app.evals` / `app.rag.reindex` build their own Gateway | verified by `limiter.py:8` docstring; evals/reindex not re-read line by line → plausible, S3 for the pitch |
| A3 | Timed-out interactive mid task with `allow_fallback=False` is resent identically, then Defers | verified `gateway/service.py:348-369` (fallback branch needs `task.allow_fallback`; else `transient` → one resend → `Defer`), `quiz/verify.py:93` `allow_fallback=False` → OPT-05 |
| A4 | DAILY_PLAN is mid, one per student per day | verified `router.py:31`, `daily/service.py:198` (content-addressed key, so only byte-identical prompts share) → OPT-09 |
| A5 | ar/ar-TN Teach-Back grades are always mid | verified `arena/service.py:55,461` |
| A6 | studio/audio cache key contains the job id | verified `audio/service.py:135`; `studio/pack.py:235` uses `key` built with the job id (ARCHITECTURE routing table says "(+job)") → measured consequence in run 3 (OPT-01) |
| A7 | quiz/placement cache keys are not context-hashed | verified `quiz/pool.py:244`, `placement/service.py:131` |
| A8 | single-flight followers all retry together when the leader fails | verified `gateway/service.py:186-195` (`_run(task, follower=True)` registers no new flight) |
| A9 | INTENT_LANG, TRANSLATE_SHORT, CHALLENGE_ITEMS routed but never called | verified `router.py:19,32,36`; grep finds no `TaskKind.INTENT_LANG/TRANSLATE_SHORT/CHALLENGE_ITEMS` callers |
| A10 | no per-item gateway loops in features | not contradicted by anything seen; CHUNK_TAG batched 8/call (`rag/indexing.py:185`) |
| A11 | JSON repair has no own timeout/503 handling | not re-verified (S3) |
| A12 | background pause takes the max over all providers | verified `gateway/service.py:114` |
| A13 | non-official pattern labels in router/stats | verified `router.py:19-39`: batch, extraction, guard, summary, generate-once, classification, rewriting, repair, triage |
| contract | every error-contract row handled + tested | test names cross-checked with `grep "def test_"` (REPORT.md §3 table) |
