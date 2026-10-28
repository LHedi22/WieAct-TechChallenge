# Build plan — 27 Oct → 9 Nov 2026 (submit by 10 Nov)

Work ONE milestone at a time. Start in plan mode, end with `/verify`, tick boxes here.
Dates are targets; one team member builds everything (DECISIONS.md 2026-10-27), so apply the scope
guard in CLAUDE.md early. M0–M2 are the critical path — everything AI depends on them.

## M0 · Foundations (27–28 Oct)
- [ ] Monorepo layout from ARCHITECTURE.md; `docker compose up` brings db (postgres), qdrant, mock-llm, backend, worker, frontend
- [x] `backend/app/core/config.py` (pydantic-settings) reads every var in `.env.example`; app refuses to start if `CLOUD_API_KEY` is missing **only** when the resolved provider is cloud
- [ ] `.env` in `.gitignore`; `.env.example` complete; gitleaks runs in CI
- [ ] Alembic initial migration; SQLAlchemy models for users, worlds, jobs, ai_cache, ai_call_log
- [x] Frontend: Vite + TS + Tailwind with tokens, fonts, i18n (4 locales, RTL switch), router, `/styleguide` route with all primitives from DESIGN.md
- [ ] CI: ruff, pytest, eslint, tsc, vitest
**Done when:** fresh clone → `cp .env.example .env` → `docker compose up` → styleguide renders in EN and AR (RTL) and `/api/health` is green.

_Status 28/10:_ all code for M0 is written and committed; ruff, pytest (21 pass), eslint, tsc, vitest (17),
`i18n:check` and the constraint greps pass locally; `/styleguide` checked in a browser at 1440×900 and
390×844 in EN, AR and side by side. **Still open:** the Docker run (layout box, migration test against
Postgres — skipped without a DB) and the first CI run (no git remote yet, so gitleaks/CI haven't executed).

## M1 · Mock LLM + AI gateway (28–30 Oct) — 40% of platform score lives here
- [ ] `mock-llm/`: `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`; configurable latency per tier; fault injection via env or header: `503+Retry-After`, quota-exhausted+delay, `400` ceiling message, malformed JSON, concurrency > 2 rejected; quota headers emitted
- [ ] Gateway: router table, cache, RPM bucket + concurrency semaphore, priority lanes, error contract handling, compact fallback with `quick_mode`, 400 shrink-and-retry-once, JSON repair, call log
- [ ] **Provider switching (local / cloud / mock)** — decision 2026-10-27 in DECISIONS.md; ARCHITECTURE.md §Providers
  - [x] HUMAN (done 27/10: qwen3:8b on the 15.4 GB laptop; restart Ollama to apply the env vars): install Ollama (`winget install Ollama.Ollama`); set `OLLAMA_NUM_PARALLEL=2`,
        `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_KEEP_ALIVE=30m`; `ollama pull qwen3:1.7b qwen3:14b bge-m3`
        (`qwen3:8b` if under 16 GB RAM). Not blocking: dev runs on mock until this is done.
  - [ ] `LLM_PROVIDER=local|cloud|mock|auto` with `CLOUD_*`, `LOCAL_*`, `MOCK_*` profile variables
        (base URL, key, compact/mid/embedding model, embedding dim). `config.py` resolves one
        `settings.llm` object, and nothing else reads the profile variables. Default: mock until
        Ollama is installed, then local.
  - [ ] `auto` = cloud when our slot is live (slot logic moved into `app/core/slot.py`) and no 401
        "Key is blocked" has been seen since the slot started; otherwise local. Evaluated per job.
  - [ ] Production guard: `APP_ENV=production` allows only cloud. Outside the slot or on 401:
        Offline demo mode with cached cloud results only. Refuse to start with local or mock.
  - [ ] Same limiter (2 concurrent, `LLM_MAX_RPM`) for every provider.
  - [ ] `scripts/llm.py`: `use local|cloud|mock|auto` (rewrites only the `LLM_PROVIDER` line in `.env`,
        creating `.env` from `.env.example` if missing), `status` (provider, host, models, dim,
        collection, slot; shows the key only as set/empty), `check` (`GET /models`; for local, lists
        pulled models via `/api/tags` and prints the `ollama pull` command for any missing).
        Standard library only, works on Windows.
  - [ ] `scripts/setup_ollama.ps1` + `.sh`: check install, pull the models, warm them up, run
        `llm.py check`.
  - [ ] Qwen3 thinking off: append `" /no_think"` to the system message for qwen3 models; for cloud
        also send `chat_template_kwargs` `enable_thinking=false` and drop it on a 400; always strip
        `<think>…</think>`. Tested.
  - [ ] Providers kept apart: Qdrant collection = `{prefix}-{provider}-{embedding model slug}` with
        that provider's dim; `python -m app.rag.reindex --provider cloud` rebuilds the cloud
        collection; `ai_cache` keys and `ai_call_log` rows include provider and model;
        `/api/admin/stats` defaults to `provider=cloud`; Offline demo mode serves cloud-generated
        cache only; a dev-only Local/Cloud/Mock badge in the top bar.
  - [ ] Docker: backend and worker reach host Ollama at `http://host.docker.internal:11434/v1`
        (`extra_hosts: host-gateway` on Linux). Ollama runs on the host, not in compose.
  - [ ] `probe_models.py` gets `--provider local|cloud`, uses the profile variables, and tags its
        MODELS.md section with the provider.
- [ ] Jobs: create, worker loop (SKIP LOCKED), stages, `not_before`, queue position + ETA, coin reserve/commit/refund hooks
- [ ] `useJob` hook + `LoadingStages` + queue/quick-mode banners wired to a demo job
- [ ] `/api/admin/stats`: calls per tier, split %, tokens, cache hits, refusals, fallbacks
- [ ] Tests for every row of the error contract in PLATFORM.md
- [ ] **In-slot model probe:** `python3 scripts/probe_models.py` → fills docs/MODELS.md results, prints recommended `.env` lines (models, embedding dim, ceilings, quota header names); record in DECISIONS.md
**Done when:** a load script firing 30 jobs at mock (with 503 and quota faults on) completes all jobs, never exceeds 2 concurrent, shows fallbacks in stats, and the UI shows queue position, and `python scripts/llm.py use auto` switches between local and cloud at slot boundaries without restarting (verified against mock with `MOCK_BLOCKED`).

## M2 · Upload & indexing (30 Oct–1 Nov)
- [ ] Parsers: PDF (PyMuPDF), PPTX, DOCX, TXT, images + scanned pages via Tesseract (ara+fra+eng)
- [ ] Chunking with page/slide refs; batched CHUNK_TAG (background lane, burst); embeddings batched
- [ ] `VectorStore` interface + `QdrantVectorStore` (qdrant-client async): create the provider's collection if missing with `settings.llm` embedding dim + cosine, payload indexes on `world_id`, `course_id`, `chapter_id`, `level_tags`; idempotent upserts keyed by chunk UUID; delete-by-document
- [ ] Create-world wizard + join by code; staged indexing screen with real per-document progress
- [ ] Precompute after upload: quiz pool (intermediate, creator language)
- [ ] Seed script with 2 public/synthetic courses (e.g. Calculus I limits, Data Structures stacks/queues) — openly licensed
**Done when:** upload of a 30-page PDF + a PPTX finishes indexing and `search("limit 0/0")` returns the right chapter chunks.

## M3 · Onboarding + map (1–3 Nov)
- [ ] Sign up/login (nickname+password, argon2), landing with language picker
- [ ] Style test steps, result card, avatar builder
- [ ] World map (pixel scene, islands from layout JSON, mastery rings, top bar, side panel), list view, island view, building entry dialog with live costs
- [ ] Placement quiz (8 Q, free) sets course level
- [ ] Empty-world and island-locked states
**Done when:** a new user goes landing → sign up → style test → join demo world → placement → island in < 5 min.

## M4 · Quiz Hall + Socratic Tutor (2–4 Nov)
- [ ] Quiz: one-call generation (narrow-before-generating), hint + second try, explanations, results with next step, mistake tagging job, points
- [ ] Tutor: compact turns with answer-leak guard, escalation to mid on stuck, hint counter, ideas found, session summary
- [ ] Prompt eval script: 20 generated questions per language reviewed for correctness (store results for the report)
**Done when:** full quiz + tutor sessions work in EN, FR, AR on seeded material, under mock faults.

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
