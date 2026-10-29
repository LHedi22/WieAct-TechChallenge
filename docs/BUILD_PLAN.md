# Build plan — 27 Oct → 9 Nov 2026 (submit by 10 Nov)

Work ONE milestone at a time. Start in plan mode, end with `/verify`, tick boxes here.
Dates are targets; one team member builds everything (DECISIONS.md 2026-10-27), so apply the scope
guard in CLAUDE.md early. M0–M2 are the critical path — everything AI depends on them.

## M0 · Foundations (27–28 Oct)
- [x] Monorepo layout from ARCHITECTURE.md; `docker compose up` brings db (postgres), qdrant, mock-llm, backend, worker, frontend
- [x] `backend/app/core/config.py` (pydantic-settings) reads every var in `.env.example`; app refuses to start if `CLOUD_API_KEY` is missing **only** when the resolved provider is cloud
- [ ] `.env` in `.gitignore`; `.env.example` complete; gitleaks runs in CI
- [x] Alembic initial migration; SQLAlchemy models for users, worlds, jobs, ai_cache, ai_call_log
- [x] Frontend: Vite + TS + Tailwind with tokens, fonts, i18n (4 locales, RTL switch), router, `/styleguide` route with all primitives from DESIGN.md
- [ ] CI: ruff, pytest, eslint, tsc, vitest
**Done when:** fresh clone → `cp .env.example .env` → `docker compose up` → styleguide renders in EN and AR (RTL) and `/api/health` is green.

_Status 28/10:_ **Done-when passes.** Fresh clone → `cp .env.example .env` → `docker compose up --build`
(with `NPM_REGISTRY=https://registry.yarnpkg.com/`, our network blocks registry.npmjs.org) → all 6 services
up, `/api/health` = `{"status":"ok","db":"ok","qdrant":"ok","provider":"mock"}`, Alembic at `0001 (head)`,
`/styleguide` renders in EN and AR (RTL) at 1440×900 and 390×844 with no console errors or horizontal
scroll. ruff, pytest (22 pass incl. the migration test against Postgres), eslint, tsc, vitest (17),
`i18n:check` and the constraint greps pass. **Open:** the two CI boxes — the workflow and gitleaks job are
in `.github/workflows/ci.yml`, but there is no git remote yet, so CI has never run.

## M1 · Mock LLM + AI gateway (28–30 Oct) — 40% of platform score lives here
- [x] `mock-llm/`: `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`; configurable latency per tier; fault injection via env or header: `503+Retry-After`, quota-exhausted+delay, `400` ceiling message, malformed JSON, concurrency > 2 rejected; quota headers emitted
- [x] Gateway: router table, cache, RPM bucket + concurrency semaphore, priority lanes, error contract handling, compact fallback with `quick_mode`, 400 shrink-and-retry-once, JSON repair, call log
- [ ] **Provider switching (local / cloud / mock)** — decision 2026-10-27 in DECISIONS.md; ARCHITECTURE.md §Providers
  - [x] HUMAN (done 27/10: qwen3:8b on the 15.4 GB laptop; restart Ollama to apply the env vars): install Ollama (`winget install Ollama.Ollama`); set `OLLAMA_NUM_PARALLEL=2`,
        `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_KEEP_ALIVE=30m`; `ollama pull qwen3:1.7b qwen3:14b bge-m3`
        (`qwen3:8b` if under 16 GB RAM). Not blocking: dev runs on mock until this is done.
  - [x] `LLM_PROVIDER=local|cloud|mock|auto` with `CLOUD_*`, `LOCAL_*`, `MOCK_*` profile variables
        (base URL, key, compact/mid/embedding model, embedding dim). `config.py` resolves one
        `settings.llm` object, and nothing else reads the profile variables. Default: mock until
        Ollama is installed, then local.
  - [x] `auto` = cloud when our slot is live (slot logic moved into `app/core/slot.py`) and no 401
        "Key is blocked" has been seen since the slot started; otherwise local. Evaluated per job.
  - [x] Production guard: `APP_ENV=production` allows only cloud. Outside the slot or on 401:
        Offline demo mode with cached cloud results only. Refuse to start with local or mock.
  - [x] Same limiter (2 concurrent, `LLM_MAX_RPM`) for every provider.
  - [x] `scripts/llm.py`: `use local|cloud|mock|auto` (rewrites only the `LLM_PROVIDER` line in `.env`,
        creating `.env` from `.env.example` if missing), `status` (provider, host, models, dim,
        collection, slot; shows the key only as set/empty), `check` (`GET /models`; for local, lists
        pulled models via `/api/tags` and prints the `ollama pull` command for any missing).
        Standard library only, works on Windows.
  - [ ] `scripts/setup_ollama.ps1` + `.sh`: check install, pull the models, warm them up, run
        `llm.py check`.
  - [x] Qwen3 thinking off: append `" /no_think"` to the system message for qwen3 models; for cloud
        also send `chat_template_kwargs` `enable_thinking=false` and drop it on a 400; always strip
        `<think>…</think>`. Tested.
  - [ ] Providers kept apart: Qdrant collection = `{prefix}-{provider}-{embedding model slug}` with
        that provider's dim; `python -m app.rag.reindex --provider cloud` rebuilds the cloud
        collection; `ai_cache` keys and `ai_call_log` rows include provider and model;
        `/api/admin/stats` defaults to `provider=cloud`; Offline demo mode serves cloud-generated
        cache only; a dev-only Local/Cloud/Mock badge in the top bar.
  - [ ] Docker: backend and worker reach host Ollama at `http://host.docker.internal:11434/v1`
        (`extra_hosts: host-gateway` on Linux). Ollama runs on the host, not in compose.
  - [x] `probe_models.py` gets `--provider local|cloud`, uses the profile variables, and tags its
        MODELS.md section with the provider.
- [x] Jobs: create, worker loop (SKIP LOCKED), stages, `not_before`, queue position + ETA, coin reserve/commit/refund hooks
- [x] `useJob` hook + `LoadingStages` + queue/quick-mode banners wired to a demo job
- [x] `/api/admin/stats`: calls per tier, split %, tokens, cache hits, refusals, fallbacks
- [x] Tests for every row of the error contract in PLATFORM.md
- [ ] **In-slot model probe:** `python3 scripts/probe_models.py` → fills docs/MODELS.md results, prints recommended `.env` lines (models, embedding dim, ceilings, quota header names); record in DECISIONS.md
**Done when:** a load script firing 30 jobs at mock (with 503 and quota faults on) completes all jobs, never exceeds 2 concurrent, shows fallbacks in stats, and the UI shows queue position, and `python scripts/llm.py use auto` switches between local and cloud at slot boundaries without restarting (verified against mock with `MOCK_BLOCKED`).

_Status 28/10:_ load test PASS — `load.py --jobs 30 --faults 503,quota` against the compose stack:
30/30 done, 53 calls (15×503, 8×quota, all handled), max 1 in flight (≤ 2), 1 compact fallback,
interactive p50 38 s vs background 126 s; `/dev/jobs` shows queue position + ETA (#32, ~94 s) in EN
and AR. auto switching is covered by the contract tests with the real gateway and a blocked mock key
(in-slot 401 → local on the same job, next job local without restart, back to cloud in the next
slot); not yet re-run in Docker (one compose mock can't block only the cloud profile). Tests: 99
backend, 16 mock-llm, 23 frontend. **Open:** setup_ollama scripts written + syntax-checked but not run
(Ollama not started); Docker → host Ollama untested; reindex CLI moves to M2; the dev provider badge
is on /dev/jobs (no top bar until M3); the in-slot probe (human).

## M2 · Upload & indexing (30 Oct–1 Nov)
- [x] Parsers: PDF (PyMuPDF), PPTX, DOCX, TXT, images + scanned pages via Tesseract (ara+fra+eng)
- [x] Chunking with page/slide refs; batched CHUNK_TAG (background lane, burst); embeddings batched
- [x] `VectorStore` interface + `QdrantVectorStore` (qdrant-client async): create the provider's collection if missing with `settings.llm` embedding dim + cosine, payload indexes on `world_id`, `course_id`, `chapter_id`, `level_tags`; idempotent upserts keyed by chunk UUID; delete-by-document
- [x] Create-world wizard + join by code; staged indexing screen with real per-document progress
- [x] Precompute after upload: quiz pool (intermediate, creator language)
- [x] Seed script with 2 public/synthetic courses (e.g. Calculus I limits, Data Structures stacks/queues) — openly licensed
**Done when:** upload of a 30-page PDF + a PPTX finishes indexing and `search("limit 0/0")` returns the right chapter chunks.

_Status 29/10:_ **Done-when passes**, through the real UI (host: API + worker + mock-llm, compose db +
Qdrant): `/worlds/new` wizard → upload the synthetic 30-page Calculus PDF (one scanned page, OCR'd) and
a 12-slide Data Structures PPTX → both `ready` in 35 s, 2 quiz pools → `search("limit 0/0")` top 5 are
all Limits pages (p. 1-13) of the Calculus chapter; "push pop LIFO stack" → the stack slides. Cost: 6
CHUNK_TAG + 2 EMBED calls for both files (+ 2 query embeddings), 0 repeated identical. Also a pytest
(`test_done_when_…`). Indexing screen checked in EN and AR at 1440×900 and 390×844 (RTL, no overflow,
no console errors). Backend image builds with Tesseract ara/eng/fra. Tests: 150 backend, 19 mock-llm,
29 frontend; load smoke (10 jobs, 503 + quota) PASS. M1's reindex CLI landed here
(`python -m app.rag.reindex --provider cloud`). **Open:** Arabic OCR on a real Arabic scan not yet
tried; real embeddings (bge-m3 / platform) not yet run — the mock's bag-of-words vectors only prove the
pipeline; sign-in is a dev seam (`X-Dev-User`) until M3.

## M3 · Onboarding + map (1–3 Nov)
- [x] Sign up/login (nickname+password, argon2), landing with language picker
- [x] Style test steps, result card, avatar builder
- [x] World map (pixel scene, islands from layout JSON, mastery rings, top bar, side panel), list view, island view, building entry dialog with live costs
- [x] Placement quiz (8 Q, free) sets course level
- [x] Empty-world and island-locked states
**Done when:** a new user goes landing → sign up → style test → join demo world → placement → island in < 5 min.

_Status 29/10:_ **Done-when passes** through the real UI (Playwright, host API + worker + mock-llm,
compose db + Qdrant, seeded world `OLIVE-7Q2`): a brand-new user goes landing → sign up → 4-question
style test → goals → result + avatar → languages → join with "olive 7q2" → map (islands locked) →
placement (8 questions; generated on first use, then shared) → result → island in **11 s scripted**
(first run, incl. generating the placement set) / 5 s when the set is cached — a human reading and
answering everything fits well inside 5 minutes. EN and AR (RTL panels, un-mirrored geography) at
1440×900 and 390×844, no horizontal scroll, no console errors. Tests: 177 backend, 20 mock-llm, 37
frontend; load smoke (10 jobs, 503 + quota) PASS. **Open / deferred:** side panel shows "Your class"
until M5 (leaderboard) and M6 (challenges); wallet numbers are economy placeholders until M5;
building Confirm leads to "opens soon" until M4; sprites are placeholders; on the CPU platform the
first placement generation will take longer than on the mock (one compact call, then cached).

## M4 · Quiz Hall + Socratic Tutor (2–4 Nov)
- [x] Quiz: one-call generation (narrow-before-generating), hint + second try, explanations, results with next step, mistake tagging job, points
- [x] Tutor: compact turns with answer-leak guard, escalation to mid on stuck, hint counter, ideas found, session summary
- [ ] Prompt eval script: 20 generated questions per language reviewed for correctness (store results for the report)
**Done when:** full quiz + tutor sessions work in EN, FR, AR on seeded material, under mock faults.

_Status 29/10:_ **Done-when passes** through the real UI (Playwright, host API + worker + mock-llm with
`p_503_mid` 0.15 + `p_quota` 0.1, compose db + Qdrant, seeded `OLIVE-7Q2`): for each of EN, FR, AR a new
user signs up → joins → placement → Quiz Hall (wrong answer → hint → second try on 6 questions, one skip,
results with points, weak spot and the Tutor next step) → Socratic Tutor (a message, 2× "I'm stuck" →
mid turn, a hint, End → summary) in 36–39 s scripted; no console errors; AR at 390×844 has no horizontal
scroll. Final run: 18 compact + 3 mid calls (mid only from escalation), quiz and placement sets from the
class cache, **0 repeated identical requests** (the first run found 32 — double starts under StrictMode,
per-attempt tag keys, unshared tutor plans — fixed and tested); the first run drew 23 faults (503, quota,
ceiling), all handled, 2 compact fallbacks. Tests: 194 backend, 42 frontend. **Open:** the eval box —
the script and its automatic checks run on the mock, but "reviewed for correctness" needs real-model
outputs from our slot (prompt-evaluator agent or a human); KaTeX replaced by the built-in `MathText`
(npm registry blocked); coins for Quiz/Tutor are recorded on jobs, charged from M5.

## M5 · Economy, leaderboards, Teach-Back (4–6 Nov)
- [ ] Wallet ledgers, daily refill (Africa/Tunis), earn cap, refunds, demo purchase, out-of-coins screen
- [ ] Points, streaks, class + global leaderboards (opt-out)
- [ ] Teach-Back peer room (ask with moderation, answer, AI grade draft-then-revise, pin best, helpful votes, polling) + solo mode
**Done when:** two browsers in the same world can ask/answer and see scores and leaderboard change.

## M6 · Daily challenges + Class Wisdom (6–7 Nov)
- [ ] Daily plan (plan-once mid) + daily return screen + challenge progress tracking
- [ ] Wisdom: tag counting, threshold → mid tip, tips on loading screens and Quiz Hall
**Done when:** 3 seeded students making the same mistake produce a tip shown on the next loading screen.

## M7 · Study Studio → Audio Studio (7–8 Nov; cut Audio first)
- [ ] Notes, flashcards with SRS, mind map; shared cache; Class Pool payment
- [ ] Audio script + Web Speech player with transcript and speed

## M8 · Ship (8–9 Nov)
- [ ] Offline demo mode (`/api/system/status` + banner, disables new AI actions)
- [ ] Deploy (Vercel + Render/Railway), seed demo world, Darija review by native speakers
- [ ] User test with ~10 students simultaneously (in-slot); export stats for report
- [ ] README (setup, architecture, GenAI module explanation, screenshots), demo video ≤ 1:30 (show shared world, fallback, queue + Wisdom tip), 6-page report
