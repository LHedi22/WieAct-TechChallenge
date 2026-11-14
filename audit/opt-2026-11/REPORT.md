# Optimization audit before the pitch — Captain Cat (13–14 Nov 2026)

**HEAD `ba1a36cd87530eef09478f5b8f9263274b27a156` on `main`** (`git status` clean before and after,
apart from this folder). The audit was read-only. Measurements ran on an isolated mock stack
(`-p cc-opt`, all host ports remapped by `/tmp/cc-opt/override.yml`, copied to `logs/scripts/`).
**Zero platform calls.** Ollama was running on the host but was not used.

Source tags:
- `code`: read in the source.
- `mock`: measured on cc-opt.
- `local`: earlier Ollama runs (`audit/artifacts/phase6/`).
- `platform-log`: the 30 Oct probe (`scripts/out/probe-cloud-20261030-1806.json`) and DECISIONS.md 2026-11-09.

**Mock and local numbers are never platform numbers.**

## 1. Verdict

The gateway, error contract, leases, coins and offline guards are solid. Every S0/S1 finding from the 2 Nov audit is fixed and has a test.

The largest remaining risk is a scenario the jury demo and a class test produce naturally: **several students opening the same chapter at the same moment.**
- 10 simultaneous Study-pack clicks made **10 jobs, charged 150 coins, sent 7 mid + 12 compact calls and 15 repeated identical requests** for one class pack (`mock`).
- 10 simultaneous quiz starts sent 7 mid verifier calls for one quiz set.

That breaks the "made once per class" story the report and pitch are built on. Fix it first. Then fix the study-pack coverage bug (N-6) and pin the RPM burst under 20/min.

## 2. Scorecard

| Criterion | Weight | State now | Biggest gap | Best next optimization |
| --- | --- | --- | --- | --- |
| Orchestration | 25 | All four official patterns are really implemented (`code`): escalation, draft-then-revise (quiz verify, Teach-Back), plan-once/execute-compact (study pack), narrow-before-generating (pool/notes/audio). Estimated split for a 30-student class is ≈ 83/17 compact/mid (§6). | Duplicate class jobs under concurrency double the mid use (OPT-01). Stats show 9 non-official pattern labels (OPT-08). DAILY_PLAN spends about half the class's mid budget on wording (OPT-09). | OPT-01, then OPT-08 |
| Constraints | 25 | ≤ 2 chat calls in flight in every run (`mock`, independent logger). Cache, single-flight, quota Defer, 400 shrink and repair all work and are tested. | `repeated_identical` went 0 → 19 in one 10-student run (`mock`). **21 chat calls in one 60 s window** vs the emailed 20/min (`mock`, both load runs). The low-quota pause never fires with the platform's headers (`code`). | OPT-01, OPT-04, OPT-06 |
| Relevance & usefulness | 20 | Five buildings work end to end. Tutor never leaked in 16/16 pressure turns (`local`). Teach-Back injection is closed (`local`). | Packs and audio cover only the first slides (N-6 root cause found, `mock` + `code`). Verifier still keeps ≈ 3 of 5 wrong keys (`local`). Moderation is uneven across languages (N-4, `local`). Arabic/Darija vocabulary is off (N-5, `local`). | OPT-02, OPT-07, OPT-11 |
| Resilience under load | 15 | 30/30 jobs done with 503+quota faults; interactive p50 25.6 s vs background 106.3 s (`mock`). Worker kill → refund; DOCX bomb contained in < 7 s; 30 pollers at 20 req/s, p95 143 ms (`mock`). | Queue ETA shows 1–8 s while the real wait is 19–60 s (`mock`). A Postgres restart now kills the running job (`mock`; the 6 Nov re-test said it finished). A timed-out verifier resends the identical mid request (`code`). | OPT-05, OPT-10, OPT-12 |
| Originality | 10 | Islands, Class Wisdom, Teach-Back Arena, Darija | — (not measurable) | Don't touch; show Class Wisdom live |
| Presentation | 5 | Video, README screenshots, admin Stats page | No real platform split, cache or refusal numbers exist yet (no slot run happened). REPORT.md and the .tex still carry stale or over-strong claims (§8). | OPT-03 (jury-slot runbook) |
| Bonus: user test / multilingual | — | 4 UI languages, 828 keys × 4, RTL | No user test ran. Darija is unreviewed and the local model wrote MSA. Offline placement is warmed for EN+AR only (F-OFF-2). | OPT-03, OPT-11 |

## 3. Top 10 optimizations

Ranked by (score gain × confidence) ÷ effort. Effort: S ≤ 1 h, M ≤ ½ day, L more.

| # | ID | Title | Criterion | Impact | Effort | Regression risk |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | OPT-01 | One job per shared class asset, even when classmates click together | Orchestration + Constraints | H | S–M | Low–Med |
| 2 | OPT-02 | Study-pack/audio/quiz context that covers the whole chapter | Relevance | H | S | Low |
| 3 | OPT-03 | Jury-slot runbook: warm-up in 4 languages + the evidence runs | Presentation + Constraints + bonus | H | M (slot time) | Low |
| 4 | OPT-04 | Keep any 60 s window under the platform's 20 requests | Constraints + Resilience | M | S | Low |
| 5 | OPT-05 | A timed-out no-fallback mid call never resends the identical request | Resilience + Constraints | M | S | Low |
| 6 | OPT-06 | Low-quota background pause that works without a reset header | Constraints | M | S | Low |
| 7 | OPT-07 | Deterministic moderation pre-filter + per-language examples (N-4) | Relevance + fairness | M | S | Low |
| 8 | OPT-08 | Report the official pattern names in the call log and stats | Orchestration (presentation) | M | S | Low |
| 9 | OPT-09 | Daily plan on compact (mid only when a student has weak spots) | Orchestration | M | S | Low |
| 10 | OPT-10 | Queue ETA that matches the real wait | Resilience (UX) | M | S | Low |

**OPT-01: one job per shared class asset.**
- **Files:** `backend/app/features/studio/service.py:88-111`, `features/quiz/service.py:72-116`, `features/audio/service.py`, `features/placement/router.py:62-108`, `features/studio/pack.py:157,235`, `features/audio/service.py:135`, plus a migration if an index is used.
- **Change:**
  - Make the "is a classmate's job already pending? otherwise create one and charge" step atomic per (kind, chapter, level, language). Use a transaction-level advisory lock on that tuple, or a partial unique index on queued/running jobs keyed by it, with the loser attaching to the winner's job at cost 0.
  - Make the studio/audio gateway cache keys content-addressed (drop the job id) so a duplicate that slips through still hits single-flight.
  - The quiz start should charge only the student who triggers a generation, like the studio already intends.
- **Evidence:** `logs/32-same-chapter-10.log` and `logs/32-same-chapter-db.txt` (10 STUDY_PACK jobs × 15 coins, 1 `study_assets` notes row, NOTES_WRITE 7, MAP_WRITE 6, FLASHCARDS 6, repeated_identical +15; 10 quiz jobs × 5 coins, QUIZ_VERIFY 7).
- **Verify:**
  - A pytest that fires 10 concurrent `generate` calls and asserts 1 job, 1 charge and 1 NOTES_WRITE.
  - Re-run `logs/scripts/same_chapter.py` on a mock stack: `distinct_jobs: 1`, `repeated_identical` delta 0.

**OPT-02: context that covers the chapter (N-6 root cause).**
- **Files:** `backend/app/features/quiz/pool.py:78-95` (`pick_context`), `:157-182` (`chapter_context`, `CONTEXT_CHUNKS=6`, `SEARCH_K=12`).
- **Cause:** `pick_context` round-robins over each chunk's *first tag*, in document order. When most chunks have distinct first tags, it degenerates to "the first 6 chunks". On the Stacks-and-queues deck that is slides 1–5 + 7, five of them on stacks (`logs/40-stacks-chunks-mock.txt`). The slide chunks are also about 80 characters each, so a mid NOTES_WRITE call gets about 500 characters of course text.
- **Change:**
  - Choose chunks spread evenly across the chapter's position range (or by concept cluster) and fill to a character budget (e.g. ~6–8k characters) instead of a fixed count of 6.
  - Zero extra calls; one function shared by quiz, notes and audio.
- **Verify:**
  - A unit test on a 12-slide fixture asserts that both halves of the chapter are present.
  - A mock study pack's `refs` include slides 7–12.

**OPT-03: jury-slot runbook (human + slot time).**
- **Files:** `docs/DEPLOY.md` §4, `docs/report/SLOT_CHECKLIST.md`.
- **Change:**
  - Extend the warm-up to placement for both courses × **4** languages (F-OFF-2).
  - Run the evidence commands in §9 in order.
  - Fill REPORT/pitch numbers only from `export_stats.py`.
- **Why:** no platform split, cache or refusal number exists yet (no slot run happened; STATUS.md §2 is all unticked). The jury computes these on our key.
- **Verify:** `docs/report/` has a stats export with `provider=cloud`; offline placement opens in all 4 languages.

**OPT-04: RPM window.**
- **Files:** `backend/app/gateway/limiter.py:26-29`, `core/config.py:96`.
- **Problem:** bucket capacity = min(3, rpm), so 18 RPM + 3 burst gave **21 chat calls in one 60 s window** in both load runs (`logs/30-*.logger.json`, `31-*.logger.json`, `mock`). Email says 20/min and the platform header `x-litellm-key-rpm-limit` exists (DECISIONS 2026-11-09).
- **Change:** cap so that rpm + burst ≤ the platform limit (e.g. burst 2 at 18), or read the RPM limit header.
- **Verify:** the logger's max 60 s window ≤ 20 on a 30-job run.

**OPT-05: timed-out no-fallback mid.**
- **Files:** `backend/app/gateway/service.py:348-369`, `features/quiz/verify.py:86-95`.
- **Problem:** an interactive QUIZ_VERIFY (or Teach-Back review) that hits the 45 s budget is classed `transient` and resent identically once (another quota unit, a repeated identical request at the platform and up to 90 s of waiting), then Deferred.
- **Change:** on timeout of a `allow_fallback=False` interactive mid task, raise straight to the caller's "unavailable" path (unverified quiz for this student / the draft stands). The abandoned-slot logic stays.
- **Verify:** a test with mock mid latency 100 s gets one mid call and an unverified quiz in ≈ 45 s.

**OPT-06: low-quota pause.**
- **Files:** `backend/app/gateway/quota.py:22-34`, `gateway/service.py:114`.
- **Problem:** `resume_in_s()` returns 0 when `reset_s` is None, and the platform sends no reset header (DECISIONS 2026-11-09). So the background lane **never** pauses on low quota, although the .tex §"Built for Heavy Demand" says it does. The constraint-auditor read this the other way round (`logs/05-constraint-auditor.md`).
- **Change:** when no reset is given, pause for the bucket's refill time (≈ 60/RPM × the deficit) from the observation, and only for the active provider.
- **Verify:** a unit test with `remaining=2` and no reset header pauses background for a few seconds, then resumes.

**OPT-07: moderation.**
- **Files:** `backend/app/prompts/moderate_post.md`, `features/arena/service.py:~529`.
- **Change:**
  - A server-side pre-filter: phone, email and handle regexes → `personal_data` without a call; a short multilingual insult list including Darija → `abusive`.
  - One worked example per verdict per language in the prompt.
- **Cost:** 0 extra calls (fewer, when the filter decides).
- **Evidence:** N-4 (`audit/artifacts/phase6/adversarial-local-moderation-*.json`, `local`): the Darija insult was published, the FR study question rejected, `personal_data` was never returned.
- **Verify:** `adversarial_probe.py --parts moderation` on mock/local, and in-slot (SLOT_CHECKLIST step 4).

**OPT-08: official pattern names.**
- **Files:** `backend/app/gateway/router.py:19-39`, `admin/stats.py`.
- **Problem:** labels such as batch, extraction, guard, summary, classification, generate-once, rewriting, repair and triage reach `ai_call_log.pattern` and the admin stats. PLATFORM.md asks to use the four official names in logs.
- **Change:** keep the internal label, but add an `official_pattern` (escalation · draft-then-revise · plan-once/execute-compact · narrow-before-generating · fallback · none) and show the split by it on the Stats page the jury may see.
- **Verify:** the Stats page groups calls by the four names.

**OPT-09: daily plan on compact.**
- **Files:** `backend/app/gateway/router.py:31`, `features/daily/service.py:~190-200`.
- **Problem:** with caching, DAILY_PLAN is ≈ 30 of ≈ 58 mid calls per class-day (§6, `code`).
- **Change:** compact writes the "why" lines over the rule plan. Escalate to mid only for students with weak spots or an exam within 7 days.
- **Effect:** frees mid for the quiz verifier, where quality matters.
- **Verify:** a test that a new student's plan makes 1 compact call; the §6 split recomputed.

**OPT-10: ETA.**
- **Files:** `backend/app/jobs/service.py:94-137`.
- **Problem:** ETA = queue position × average *call* latency ÷ 2, but jobs make 2–4 calls and queued jobs deferred to a future `not_before` still count as "ahead". Measured first ETAs were 1–8 s against waits of p50 19–25 s and p95 34–60 s (`logs/32-same-chapter-10.log`, `mock`).
- **Change:** estimate with per-kind average job duration (from finished jobs) and skip future-deferred jobs.
- **Verify:** on a same-chapter run, first ETA within ±50 % of the actual wait.

## 4. All findings

| ID | Area | Sev | Evidence | Measured / inferred | Source | Recommendation | Effort |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OPT-01 · **fixed** `65ebdbb` | jobs/cache | S1 | `logs/32-same-chapter-10.log`, `32-same-chapter-db.txt`; `studio/service.py:95-111` | measured | mock + code | §3 | S–M |
| OPT-02 | RAG | S1 | `quiz/pool.py:78-95,157-182`; `logs/40-stacks-chunks-mock.txt`; N-6 | measured (chunk pick) + inferred (output) | mock + code + local | §3 | S |
| OPT-03 | demo | S1 | STATUS.md §2 unticked; no `cloud-*` eval outputs; no stats export in `docs/report/` | inferred | code/docs | §3, §9 | M |
| OPT-04 | limiter | S2 | `limiter.py:28`; logger max 21/60 s | measured | mock | §3 | S |
| OPT-05 | gateway | S2 | `service.py:348-369`, `verify.py:93` | inferred | code | §3 | S |
| OPT-06 | quota | S2 | `quota.py:31-34`; DECISIONS 2026-11-09 (no reset header) | inferred | code + platform-log | §3; also fix the .tex claim | S |
| OPT-07 | moderation | S2 | N-4 artifacts | measured | local | §3 | S |
| OPT-08 | orchestration | S3 | `router.py:19-39` | code | code | §3 | S |
| OPT-09 | orchestration | S2 | `router.py:31`; §6 | inferred | code | §3 | S |
| OPT-10 · **fixed** `fb7a94e, a134f8c, f1d8ed4` | UX | S2 | `jobs/service.py:94-137`; ETA 1–8 s vs 19–60 s | measured | mock | §3 | S |
| OPT-11 | language | S2 | N-5 artifacts; `_voice_rules.md:8` example «النهاية (limite)» copied into unrelated outputs | measured | local | Per chapter × language glossary from CHUNK_TAG concepts via the unused TRANSLATE_SHORT (1 compact call per chapter per language, cached), injected into notes/audio/tutor/grade prompts; replace the copied example with a placeholder | M |
| OPT-12 · **fixed** `f3fc431, 0c66103` | worker | S2 | `logs/61-chaos-db-restart.log`: worker survived, job `failed errors.job_interrupted` after 83 s (refunded); `Worker.execute()` raised `DBAPIError` uncaught; API 500 during the restart. AUDIT 6 Nov said "pack finished" | measured | mock | Retry the job's DB writes with the same backoff the loop uses, or requeue instead of failing on a DB error inside `execute` | S–M |
| OPT-13 | latency | S2 | mid `llama3.1-8b` 13.4 tok/s; 373 tokens in 23.6 s (probe). Local notes 370–510 tokens (`logs/11-local-output-sizes.txt`). Interactive mid budget 45 s (`config.py:89`) | inferred | platform-log + local | A first study pack/audio on the platform may often time out into Quick mode (≈ 30–40 s of generation plus prefill of a ~3k-token context on CPU). Measure in-slot; if so, generate packs for the demo chapters on the background lane at upload (precompute) or raise the budget only for NOTES/AUDIO | S (+ slot) |
| OPT-14 | verifier | S2 | `quiz/pool.py:250-276`: < 5 kept → regenerate + re-verify. Local verifier kept 5 of 19 (AUDIT 6 Nov) | inferred | code + local | A first quiz on real models is likely 2 compact + 2 mid, not "1 + 1" (the .tex says 1 + 1). Ask the verifier for a 1-line worked step before its answer (0 extra calls, +~150 tokens), and generate 12 questions so 5+ survive more often | S |
| OPT-15 | verifier quality | S2 | AUDIT residual 2: 3 of 5 kept items wrong (`local`) | measured | local | Same as OPT-14; also drop items where the verifier is "sure" but the explanation contradicts the key (server check) | S |
| OPT-16 | grading | S2 | AUDIT residual 1: AR/Darija don't rank weak < acceptable < strong (`local`) | measured | local | Arabic and Darija calibration examples (one per rubric level) in `_teachback_rubric.md`: 0 extra calls. Re-run SLOT_CHECKLIST step 1 | S |
| OPT-17 | cache | S3 | `quiz/pool.py:244`, `placement/service.py:131` keys have no context hash | code | code | Add a context hash so edited material regenerates | S |
| OPT-18 | single-flight | S3 | `gateway/service.py:186-195` | code | code | Followers re-enter `run()` so one becomes the new leader | S |
| OPT-19 | limiter scope | S3 | `limiter.py:8`; evals/reindex build their own Gateway | code | code | Refuse `--cloud` CLIs while a worker heartbeat is fresh, or document "stop the worker first" | S |
| OPT-20 | unused kinds | S3 | INTENT_LANG, TRANSLATE_SHORT, CHALLENGE_ITEMS (`router.py:19,32,36`) | code | code | Use TRANSLATE_SHORT for OPT-11; mark the other two "reserved" in ARCHITECTURE | S |
| OPT-21 | frontend | S3 | `logs/70-vite-build.log`: one 942.5 KB entry (296.6 KB gz); only AdminApp lazy (`App.tsx:33`); 4 locales eager (200 KB raw, `i18n/index.ts:4-7`) | measured | mock | Lazy-load the five buildings and non-active locales: ≈ −40 % first load on phones (estimate). Low score value | M |
| OPT-22 | polling | info | `logs/46-poll-bench-30.txt`: 30 pollers → 20 req/s, p50 61 ms, p95 143 ms, max 309 ms. `useJob` stops on terminal status; TanStack stops when the tab is hidden; no backoff | measured | mock | No change needed. Optional backoff to 3 s after 60 s queued | S |
| OPT-23 | DB | info | `logs/45-explain-hot-queries.txt`: job by id, queue position, avg latency, ai_cache, leaderboard all < 0.1 ms (index scans; small tables) | measured | mock | None | — |
| OPT-24 | a11y | S2 | `logs/50-axe-summary.txt`: color-contrast 181 nodes / 14 screens (top: `bg-olive-light/30` ×60, `bg-terracotta-light/25|30` ×52); Tutor `list` 8 nodes; no commit to `design/tokens.json` since | measured (old scans) | mock | Opaque tints / darker ink in tokens (F-A11Y-1); `li` markup in the Tutor (F-A11Y-2) | S |
| OPT-25 | security | S3 | `main.py:35` `openapi_url="/openapi.json"` always (F-SEC-3) | code | code | `None` in production | S |
| OPT-26 · **fixed** `c622fd9` | API | S3 | No NUL stripping in `backend/app` (F-API-1) | code | code | Strip `\x00` in free-text input models | S |
| OPT-27 · **fixed** `5e3dcde` | quiz | S3 | `quiz/service.py:245-266` accepts any `i` (F-QUIZ-1) | code | code | Enforce `i == attempt.current` (or pending) | S |
| OPT-28 | auth | S3 | `api/deps.py:21` ASCII only; uniqueness case-sensitive (F-SEC-6) | code | code | casefold uniqueness; explain the rule | S |
| OPT-29 | CI | S3 | `tests/db.py:23-31` timeout 2 s + `conftest.py:86` skip (F-TEST-1); today 0 skipped | code | code | Fail instead of skip when `CI=true` | S |
| OPT-30 | tooling | S2 | `scripts/load.py:38` reads `provider=mock`, needs `/_mock` and `/api/dev/demo-jobs` (F-LOAD-1) | code | code | Blocks the "load test against cloud" box; use a real-feature script (like `logs/scripts/same_chapter.py`) with `--provider` | S |
| OPT-31 · **fixed** `eadfebc, 7a2f27c` | economy | S3 | `economy.py:27` `creator_new_member` never used; no badge code; `en.json:153` "between 1 and 50 coins" hard-coded | code | code | Cut or implement; read the 50 from `/api/economy` | S |
| OPT-32 | deploy | S1 (if the demo is on the deployed site) | `frontend/vercel.json:8` still `REPLACE-WITH-RAILWAY-DOMAIN` | code | code | Can't tell whether a deploy exists outside the repo; confirm before the pitch | S |
| OPT-33 | flaky test | S3 | `logs/02-frontend-verify.log` 1 failed / 93; 3 re-runs 93/93 | measured | mock | Find the flaky spec (name not captured in the tail) | S |

## 5. Status of the 2 Nov audit findings at HEAD

| ID | Status | Evidence |
| --- | --- | --- |
| F-DOS-1 | **fixed** | `tests/test_parse_safety.py::test_docx_bomb_fails_fast_and_does_not_block_the_queue`, `::test_archive_check_rejects_a_bomb_and_accepts_real_files`; live: 1 MB bomb `failed` in < 7 s, Tutor done in 4 s (`logs/62-chaos-docx-bomb.log`) |
| F-ACL-1 | fixed | `tests/test_worlds_acl.py::test_the_creator_can_still_manage_course_material` (+ member 403 cases) |
| F-RES-1 | fixed | `tests/test_job_lease.py::test_stale_running_jobs_are_failed_not_requeued`, `::test_a_live_job_keeps_its_lease_and_is_never_swept`; live: worker kill → `failed job_interrupted` at 63 s, coins refunded (`logs/60-chaos-worker-kill.log`) |
| F-CACHE-1 | fixed (for DAILY_PLAN) | `test_identical_new_students_share_one_plan_call`, `test_a_personal_difference_gets_its_own_plan`; **new repeats from OPT-01** |
| F-VID-1 | fixed | `test_forced_quick_mode_is_counted_apart`, `test_forced_quick_mode_turns_itself_off`, `test_legacy_force_quick_endpoints_use_the_switch` |
| F-DOC-2 | partly fixed | README/.tex reworded; the "37 → 0" claim no longer holds under concurrent clicks (OPT-01) |
| F-OFF-1 | fixed | `test_production_serves_platform_content`; migration 0012 (DECISIONS 2026-11-05) |
| F-OFF-2 | **still open** | DEPLOY.md §4 step 3 warms "EN and AR" only |
| F-RES-2 | fixed (fallback tasks); partly for no-fallback tasks | `tests/test_gateway_timeout.py::test_interactive_mid_timeout_falls_back_to_compact_at_once`; OPT-05 |
| F-QUICK-1 | fixed | `test_a_quick_mode_pack_is_marked_and_upgraded_for_free`, `test_a_quick_mode_audio_script_is_upgraded_for_free` |
| F-ACL-2 | fixed | `tests/test_job_auth.py::test_class_jobs_are_visible_to_members_but_only_the_owner_cancels`, `::test_a_job_without_owner_is_not_public` |
| F-SEC-1 | fixed | `tests/test_cookie_secure.py::test_production_defaults_to_secure` |
| F-SEC-2 | fixed | `admin/auth.py:3,144`; `test_blank_token_hides_every_admin_route` |
| F-SEC-3 | **still open** | `main.py:35` |
| F-SEC-4 | fixed | `tests/test_logout_revokes.py::test_a_copied_cookie_stops_working_after_logout` |
| F-SEC-5 | fixed | `test_sign_in_is_rate_limited_per_ip`; `auth/ratelimit.py:40-57` |
| F-SEC-6 | **still open** | `api/deps.py:21`; no casefold uniqueness |
| F-TEST-1 | **still open** (didn't trigger today: 529 passed, 0 skipped) | `tests/db.py:23-31`, `conftest.py:86` |
| F-LOAD-1 | **still open** | `scripts/load.py:38` |
| F-A11Y-1 / F-A11Y-2 | **still open** | no token/markup change since the scans (`git log -- design/tokens.json`) |
| F-RPM-1 | partly fixed | burst now ≤ 3 (`limiter.py:28`) but still 21/60 s (OPT-04) |
| F-CACHE-2 | **still open** | `rag/indexing.py:185` key = `doc.sha256` |
| F-API-1 | **still open** | no NUL handling in `backend/app` |
| F-QUIZ-1 | **still open** | `quiz/service.py:245-266` |
| F-UI-1 | can't tell | not re-checked (needs a browser) |
| F-DOC-1 | partly fixed | README 529/93/828 ✓; `docs/report/REPORT.md` still 304/66/793 |
| F-DOC-3 | **still open** | `.env.example:44` `true` vs DEPLOY.md `false` |
| CA-1 (limiter process-local) | open by design | OPT-19 |
| CA-2 (`LOG_PROMPTS` dead config) | can't tell | `config.py:127` still defined |
| CA-4 (unused kinds) | still open | OPT-20 |
| CA-5 ("1 and 50 coins") | still open | `en.json:153` |
| N-1 injection | fixed (`local`) | `6496eee`; graded set 0 points in 4 languages |
| N-2 scores | partly fixed | no constant 74; AR/Darija don't rank (`local`) → OPT-16 |
| N-3 keys | partly fixed | fixtures 12/12; ≈ 3 of 5 kept items still wrong (`local`) → OPT-14/15 |
| N-4 moderation | **still open** | prompt unchanged since 6 Nov (`git log -- backend/app/prompts`) → OPT-07 |
| N-5 language | **still open** | → OPT-11 |
| N-6 coverage | **still open, root cause found** | → OPT-02 |
| N-7 worker vs Postgres restart | fixed for the process; **regressed for the running job** | `logs/61-chaos-db-restart.log` → OPT-12 |
| N-8 health | fixed | `8ea7fb4`; health reports `degraded` |
| N-9 embedding retries | fixed | `63d06fb` circuit breaker |

REQUIREMENTS.md partial/missing rows:
- **Missing:** creator reward, badges, "Notify me" on the empty world.
- **Partial:** identical-request rule (OPT-01), offline cloud-only (fixed; F-OFF-2 open), timeouts (OPT-05), report numbers (§8).
- **Done:** README screenshots (STATUS 10/11), video (`docs/report/video/`), force-quick switch, provider tagging.

## 6. Call budget per action and the compact/mid split (`code`, counts per action; embeddings are our own bge-m3, not platform requests)

| Action | Compact | Mid | Shared by | Notes |
| --- | --- | --- | --- | --- |
| Upload/indexing | ⌈chunks/8⌉ CHUNK_TAG | 0 | class | + ⌈chunks/32⌉ EMBED (own Ollama). The 4 seed files made 8 CHUNK_TAG (`mock`). Then the QUIZ_POOL precompute per chapter: 1 + 1 (+1 + 1 on regen) |
| Placement (course × language) | 1 PLACEMENT_QUIZ | 1 QUIZ_VERIFY | class (same language) | +1 c + 1 m if < 5 survive |
| Quiz (chapter × level × language × seed) | 1 QUIZ_GENERATE | 1 QUIZ_VERIFY | class | +1 c + 1 m on regen (likely on real models, OPT-14); +1 QUIZ_GRADE_TAG per attempt with mistakes (background) |
| Tutor session (5 turns) | 1 plan (shared) + 5 turns + 0–1 guard + 1 summary ≈ 7 | 0–1 (escalation after 2 × stuck) | plan only | 10 simultaneous starts → 1 plan call (`mock`, `logs/33-*`) |
| Study pack | 2 (FLASHCARDS, MAP) | 1 NOTES_WRITE | class | measured 1 + 2 when alone; **7 + 12 under 10 concurrent clicks** (OPT-01) |
| Audio episode | 0 | 1 AUDIO_SCRIPT | class | same race as the studio |
| Teach-Back ask | 1 MODERATE_POST | 0 | — | |
| Teach-Back answer EN/FR | 1 draft | +1 review if low confidence or in the band | — | |
| Teach-Back answer AR/Darija | 0 | 1 (direct) | — | `arena/service.py:55,461` |
| Daily plan | 0 | 1 per student per day | only byte-identical prompts | OPT-09 |
| Wisdom tip | 0 | 1 per (world, concept, mistake type), all languages | class | |

**One typical student-day** (2 placements, 1 quiz, 1 tutor session, 1 study pack, 1 EN Teach-Back answer, daily plan):
- **First student** (generates everything): ≈ 14 compact / 6 mid → **≈ 71/29**. With quiz/placement regenerations (likely on real models): ≈ 17/9 → **≈ 66/34**.
- **Each later classmate:** ≈ 9 compact / 1.8 mid → **≈ 83/17**.

**Class of 30, same chapter, same language:** 14 + 29 × 9 ≈ 275 compact and 5.8 + 29 × 1.8 ≈ 58 mid → **≈ 83/17** (`code` estimate).
- About 30 of those 58 mid calls are daily plans.
- If 10 students write Teach-Back in Arabic or Darija, about 10 calls move from compact to mid (≈ 80/20).

That is well below the ≈ 60/40 capacity guide: it is not "everything to mid", and mid sits where reasoning matters. OPT-09 moves the daily-plan mid calls to the verifier and grading instead.

Under concurrency **without OPT-01**, a class of 10 clicking the same new pack and quiz together added +7 mid +12 compact and +7 mid (measured).

**max_tokens vs real lengths:**

| Task | max_tokens | Real output | Source |
| --- | --- | --- | --- |
| QUIZ_GENERATE (10 Q) | 1,400 | ≈ 1,130 (probe: 3 Q = 340–373 tokens) | `platform-log` (`logs/10-probe-out-tokens.txt`) |
| NOTES_WRITE | 700 | ≈ 370–510 (estimated from characters) | `local` (`logs/11-local-output-sizes.txt`) |
| AUDIO_SCRIPT | 700 | ≈ 270–380 | `local` |

- QUIZ_GENERATE is about right.
- AUDIO_SCRIPT could drop to ~500. That only caps the worst-case latency, since quota is counted in requests.
- No budget is "far above" in a way that costs quota.

**JSON_REPAIR rate:**
- `mock`: 0 repairs in 187 logged calls (`logs/47-calllog-by-task-mock.txt`).
- `local`: Darija quiz and study pack failed *after* a repair.
- Per-task rate: can't tell, because no per-call logs from the local or platform runs were kept.

## 7. Load and chaos numbers (all `mock`, cc-opt stack)

Commands (logs in `logs/`):
```
/tmp/cc-opt/dc = docker compose -p cc-opt -f docker-compose.yml -f audit/compose/mock.yml -f /tmp/cc-opt/override.yml
<dc> run --rm -T --no-deps -v $PWD/scripts:/scripts:ro backend uv run python /scripts/load.py --api http://backend:8000 --mock http://mock-llm:9000 --jobs 30 --faults 503,quota
<dc> run ... load.py ... --jobs 30 --faults ""
<dc> run --rm -T --no-deps -v /tmp/cc-opt:/opt-audit:ro -e CHAPTER=<Stacks and queues> -e LEVEL=advanced -e N=10 backend uv run python /opt-audit/same_chapter.py
python3 /tmp/cc-opt/chaos.py worker | db | bomb     # host, API :18000
<dc> run ... -e N=30 -e D=30 backend uv run python /opt-audit/pollbench.py
python3 /tmp/cc-opt/logstat.py <logger jsonl> <start> <end>   # independent in-flight / 60 s window / repeats
```

| Run | Result |
| --- | --- |
| 30 jobs, faults 503 + quota (`30-*`) | 30/30 in 163 s · interactive p50 25.6 s / p95 49.5 s · background p50 106.3 s / p95 156.9 s · max queue position 23 · 54 calls (31 × 200, 16 × 503, 7 × 429) · fallbacks 2; the forced-503 job finished in Quick mode · logger: max in flight 2, **max 21 chat calls in 60 s**, 0 repeated identical · PASS |
| 30 jobs, no faults (`31-*`) | 30/30 in 93 s · interactive p50 9.5 s / p95 26.5 s · background p50 62.4 s / p95 90.0 s · max queue position 30 · 30 calls · logger: max in flight 2, **21 in 60 s** · PASS |
| 10 students, same chapter (`32-*`, `33-*`) | studio: **10 jobs, 10 × 15 coins**, waits p50 24.8 s / p95 59.8 s, NOTES 7 · MAP 6 · FLASHCARDS 6, repeated_identical +15. Quiz: **10 jobs × 5 coins**, 1 QUIZ_GENERATE + **7 QUIZ_VERIFY**, repeated +4, waits p50 18.8 s / p95 34.0 s. Tutor: 10 sessions, **1** compact call, p50 3.2 s. First ETAs shown: 1–16 s (studio 1–5 s) |
| `/api/admin/stats` right after the same-chapter run (`mock`, `32-same-chapter-10.log` "TOTAL") | calls 140 incl. embeddings · cache_hits 16 · **repeated_identical 19** (0 before that run) · fallbacks 2 · refusals 29 handled |
| Worker kill mid pack (`60-*`) | `failed errors.job_interrupted` after 63 s; 15 coins refunded; the worker came back |
| Postgres restart mid pack (`61-*`) | worker process stayed up (backoff logged); **job failed** after 83 s (refunded); one poll answered 500 |
| DOCX bomb (`62-*`) | 1,015,554-byte bomb → document `failed` within 7 s; a classmate's Tutor start done in 4 s |
| Polling, 30 students (`46-*`) | 600 requests in 30 s = 20 req/s · p50 61 ms · p95 143 ms · max 309 ms (dev uvicorn `--reload`) |
| Hot queries (`45-*`) | all < 0.1 ms (index scans) |

**Bottlenecks:**
- The design limit (2 in flight, 18 RPM) and per-call latency dominate everything.
- The worker runs 6 interactive + 2 background jobs at once (`jobs/worker.py:79-84`, `app/worker.py:29`).
- The API and DB are nowhere near a limit at 30 students.

**Logger artifact:** the logger's `in_flight: 3` readings were all `GET /v1/models` health probes. Those go to the embeddings provider (our own Ollama in production), outside the limiter. Every chat call stayed at 2 or fewer.

## 8. Doc and claim drift (the code wins)

| Where | Says | HEAD / measurement |
| --- | --- | --- |
| .tex abstract, §Sustainability; README | "a study pack costs three platform requests whether the class has 5 students or 40" | True one click at a time; 10 simultaneous clicks → 7 mid + 12 compact (OPT-01) |
| .tex Table "Platform requests per action" | quiz "1 compact + 1 mid-size answer check" | up to 2 + 2 when < 5 items survive (`quiz/pool.py:268-276`), likely on real models |
| .tex §Built for Heavy Demand | "reads the quota headers and pauses background work when the quota runs low" | with the platform's headers (no reset) the pause is always 0 (`quota.py:31-34`, OPT-06) |
| .tex highlights | "repeated identical requests cut from 37 to 0 on our test setup" | 19 in one 10-student same-chapter run today (`mock`) |
| .tex §Quality | "none of eight attempts…", "16 attempts… all failed" | measured on **local** substitutes only; the .tex doesn't say so in those lines (the Limitations paragraph does) |
| .tex §Built for Heavy Demand; README; REPORT.md §7 | load test "median 38 s against 126 s" | 28 Oct numbers; today 25.6 s vs 106.3 s (faults) and 9.5 s vs 62.4 s (no faults) |
| REPORT.md §6 | 304 backend · 66 frontend · 793 keys | 529 · 93 · 828 |
| REPORT.md §3 | split, repeated identical "[in-slot]" | still unmeasured on the platform |
| ARCHITECTURE.md §RAG:146 | "top-k=8 by vector → compact filter keeps the 3–4 most relevant" | `SEARCH_K=12`, no filter call, `CONTEXT_CHUNKS=6` round-robin (`quiz/pool.py:33-34,157-182`) |
| ARCHITECTURE.md routing table | INTENT_LANG, TRANSLATE_SHORT as live rows | never called (`router.py:19,36`) |
| ARCHITECTURE.md routing table | studio/audio cache "(+job)" | true; that is why concurrent duplicates don't single-flight |
| PLATFORM.md | quota header names "not documented" | known since 9/11 (DECISIONS.md:167) |
| MODELS.md "Current picks" | "pending probe; prefer Qwen3"; "Quota headers: X-Frame-Options" | picked `llama3.2-3b`/`llama3.1-8b` (same file, below); headers known (DECISIONS 2026-11-09) |
| AUDIT.md 6 Nov re-test | "Postgres restart mid-pack: the pack finished" | today the job failed (OPT-12) |
| DEPLOY.md §4 | warm-up "in EN and in AR" | 4 languages needed for offline placement (F-OFF-2) |
| `.env.example:44` | `LLM_DISABLE_THINKING=true` | DEPLOY/DECISIONS say `false` |
| CLAUDE.md | "Where we are (1 Nov)", slots ahead | slots ended 10 Nov; deliverables submitted |
| `frontend/vercel.json:8` | `REPLACE-WITH-RAILWAY-DOMAIN` | no deployed domain recorded in the repo |

## 9. What needs a platform run (jury slot, widened tier)

Request counts come from `code` and SLOT_CHECKLIST (`local` measurements). They are estimates until the slot. Do OPT-01, OPT-02 and OPT-04 first, so the numbers the jury computes are the good ones.

| # | Goal | Command | ≈ requests | ≈ mid |
| --- | --- | --- | --- | --- |
| 1 | Warm the demo world (offline-proof) | `uv run python -m app.seed` (twice, DEPLOY §4); then placement for 2 courses × **4** languages; one study pack + one audio per course in EN and AR | indexing ~8 compact + 3 pools × 2–4; placement 8 × 2–4; packs 4 × 3; audio 4 × 1 → ≈ 60–80 | ≈ 25–35 |
| 2 | N-1/N-2 on real models | `uv run python -m app.evals teachback --cloud` | ≈ 33 | ≈ 22 |
| 3 | N-3 keys | `uv run python -m app.evals quiz-keys --cloud`, then `quiz --langs en,fr,ar,ar-TN --n 10 --fresh` | 4 + 16 | 4 + 8 |
| 4 | N-4 moderation | `python audit/tools/adversarial_probe.py --api <api> --parts moderation` | 16 | 0 |
| 5 | Every feature × 4 languages | `docker compose exec backend uv run python -m app.evals slot --cloud` | ≈ 30 | ≈ 17 |
| 6 | Real concurrency evidence | the same-chapter script (needs a `--provider cloud` stats read; F-LOAD-1 blocks `load.py`) with 10 real or scripted students | ≈ 20 after OPT-01 | ≈ 3 |
| 7 | Numbers for the pitch | `SSL_CERT_FILE=/etc/ssl/cert.pem ADMIN_TOKEN=… python3 scripts/export_stats.py` | 0 | 0 |
| | **Total** | | **≈ 200–220** | **≈ 80–90** |

**What we can show the jury now:**
- The orchestration indicator: Stats page compact/mid split, and per-pattern once OPT-08 is in.
- The cache indicator: `repeated_identical`, cache hits, "free for the class" (cost 0).
- Refusals handled: Stats refusals by kind, the forced Quick-mode switch, the queue banner with position and ETA.
- The error-contract tests (`tests/test_gateway_contract.py`).
- The DOCX bomb and worker-kill recovery (both measured).

**What only the slot can show:**
- The real split and repeated-identical count on our key.
- Real mid latency vs the 45 s budget (OPT-13).
- The "team quota exhausted" status code (still unseen).
- Verifier and grading quality and Darija on `llama3.1-8b`.

## 10. Don't touch before the pitch

- `backend/app/gateway/service.py` error-contract branches and their tests, `limiter.py` concurrency (only the burst constant in OPT-04), `errors.py`, `breaker.py`.
- Coin ledgers, advisory locks and refunds (`wallet/service.py`), job leases and the sweep, `start-prod.sh` watchdog.
- The parse child process and archive checks (F-DOS-1), and the production startup guards in `config.py`.
- Tutor prompts and guard (0/16 leaks, `local`), the Teach-Back injection defence and rubric totalling.
- Offline demo mode, provenance filtering, the forced-Quick switch (the video depends on it).
- i18n files and RTL layout, the drawn art, the brand assets, the recorded video.
- The routing table's tiers. OPT-08 changes only labels; OPT-09 is the one deliberate tier move.

## 11. Juror Q&A prep

| # | Likely question | Honest answer | Evidence |
| --- | --- | --- | --- |
| 1 | What's your compact/mid split on our key? | We haven't measured it on the platform yet. Our estimate for a class of 30 is about 83/17. Mid goes to notes, audio, answer-key checks, Arabic grading and stuck tutor turns. | §6; `router.py` |
| 2 | Why so few mid calls if mid is better? | Mid is the scarce resource, so it goes where reasoning changes the result. Everything shared is made once per class. Compact output that a student sees is checked by mid where errors matter (answer keys, uncertain grades). | `quiz/verify.py`, `arena/service.py:55,461` |
| 3 | How do you avoid repeated identical requests? | Class tables keyed by chapter × level × language, `ai_cache` on the full request, and single-flight in the gateway. We found and fixed a concurrency gap (OPT-01). Say whether it's fixed by pitch day. | `logs/32-*`; `tests/test_gateway_contract.py::test_concurrent_identical_requests_make_one_call` |
| 4 | What happens on 503 / quota / ceiling? | 503 on an interactive mid call: one retry, then compact (Quick mode badge); background retries later. Quota: requeue with the stated delay and show queue position. 400: shrink and resend once. Each row has a test. | `tests/test_gateway_contract.py`; `logs/30-*` |
| 5 | Do you respect 2 concurrent / 20 per minute? | Always ≤ 2 in flight (independent proxy). Per minute we pace at 18 with a small burst; a full burst touched 21 in one window on the mock, so we are capping it (OPT-04). | `logs/30-*.logger.json` |
| 6 | Can a student trick the grader or the tutor? | On local substitutes, 0 of 8 injection attempts earned points and 0 of 16 pressure turns leaked an answer. Not yet re-run on the platform models. | AUDIT.md 6 Nov; `audit/artifacts/phase6/` |
| 7 | Are the quiz answers correct? | A mid model solves each item blind and only confirmed items publish. On local models it still let about 3 in 5 wrong keys through on hard items, so we call it a safety net and label unverified items. | AUDIT.md N-3 residuals; `quiz/verify.py` |
| 8 | How good is the Darija? | The UI is fully translated but not yet reviewed by native speakers. The local model often answered in MSA; we're adding a chapter glossary and Darija examples. | N-5; OPT-11 |
| 9 | What if the server crashes mid-job? | The job's lease expires, it fails with a clear message, and the coins are refunded once. Measured: 63 s after a worker kill. A database restart doesn't kill the worker. | `logs/60-*`, `61-*`; `tests/test_job_lease.py` |
| 10 | Did real students use it? | Not yet: the planned 10-student test needed a platform slot. Everything so far is automated journeys in 4 languages × 4 browsers and synthetic students. | STATUS.md §2; AUDIT errata (16/16) |

## 12. Fixes on `fix/opt-audit-prefetch` (2026-11-14, all `mock`)

Each fix has a test that failed on the code before it. The §4 rows carry the commit hashes.

### Group A: jobs and coins

| Finding | Status | Commits |
| --- | --- | --- |
| OPT-01 one job per shared class asset | fixed | `65ebdbb` |
| OPT-12 ride out a Postgres outage | fixed | `f3fc431`, `0c66103` |
| OPT-10 ETA from real job durations | fixed | `fb7a94e`, `5a275fb`, `a134f8c`, `f1d8ed4` |
| OPT-27 answer only the current question | fixed | `5e3dcde` |
| OPT-26 NUL characters in free text | fixed | `c622fd9` |
| OPT-31 hard-coded "1 and 50" pool limit | fixed | `eadfebc` |
| OPT-31 `creator_new_member` never paid, no badge code | fixed: both cut (team decision 14 Nov) | `7a2f27c` |

Re-measured on a fresh cc-opt stack (`down -v` of cc-opt only, then `python -m app.seed`), with the
same commands as §7. Logs are in `audit/opt-2026-11/after/`.

| Run (`mock`) | Before (`logs/`) | After (`after/`) |
| --- | --- | --- |
| 10 students, same chapter: study pack | **10 jobs, 10 × 15 coins**, NOTES 7 · MAP 6 · FLASHCARDS 6, repeated_identical +15, wait p50 24.8 s / p95 59.8 s | **1 job, 1 × 15 coins** (9 join free), NOTES 1 · MAP 1 · FLASHCARDS 1, repeated_identical +0, wait p50 15.9 s / p95 15.9 s (`32-*`) |
| 10 students, same chapter: quiz | **10 jobs × 5 coins**, 1 QUIZ_GENERATE + **7 QUIZ_VERIFY**, repeated +4, wait p50 18.8 s / p95 34.0 s | **1 job, 1 × 5 coins**, 1 QUIZ_GENERATE + **1 QUIZ_VERIFY**, repeated +0, wait p50 11.0 s / p95 11.0 s (`32-*`) |
| 10 students, same chapter: Tutor start | 10 × 402 (wallets emptied by the 15 + 5 charges) | 9 × 200 + 1 × 402 (only the student who paid both is short); `33-*` with fresh students: 10 × 200, 0 calls, p50 1.6 s |
| First ETA shown vs real wait | studio 1–5 s for p50 24.8 s; quiz 2–8 s for p50 18.8 s | studio **15 s for 17.3 s**, quiz **10 s for 9.3 s** (`32c-*`, once the kind has history). A first-ever study pack showed 4 s for 15.9 s before `a134f8c` |
| Logger over the same-chapter runs | — | 20 chat calls, max in flight 2, max 7 in a 60 s window, 0 repeated identical bodies |
| Postgres restart mid study pack | job **failed** `errors.job_interrupted` after 83 s (refunded); one poll got **500** | job **done** 18 s after the restart, charged 15 once; worker logged "database back after 1s"; the poll during the restart got **503** (`61-*`) |

## Logs index (`audit/opt-2026-11/logs/`)

- **Baseline:** `00-baseline-git.txt` · `01-backend-verify.log` (ruff ✓, format ✓, **529 passed, 0 skipped**) · `02*-frontend-*.log` (lint ✓, tsc ✓, vitest 92/93 then 93/93 × 3, i18n 828 × 4) · `03-constraint-greps.log` (all empty = pass) · `05-constraint-auditor.md`
- **Probe and local data:** `10-probe-out-tokens.txt` (platform-log) · `11-local-output-sizes.txt` (local)
- **Setup:** `20-seed.log`
- **Load:** `30-*`, `31-*` (load.py + logger + stats) · `32-*`, `33-*` (same chapter) · `32-inflight3.txt`
- **Hot paths:** `40-stacks-chunks-mock.txt` · `45-explain-hot-queries.txt` · `46-poll-bench-30.txt` · `47-calllog-by-task-mock.txt`
- **Frontend:** `50-axe-summary.txt` · `70-vite-build.log`
- **Chaos:** `60-*`, `61-*`, `62-*`
- **Raw logger:** `llm-calls-mock-cc-opt.jsonl`
- **Scripts used:** `scripts/` (same_chapter.py, chaos.py, logstat.py, pollbench.py, load_run.sh, override.yml)
