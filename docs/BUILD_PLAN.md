# Build plan — 27 Oct → 9 Nov 2026 (submit by 10 Nov)

Work ONE milestone at a time. Start in plan mode, end with `/verify`, tick boxes here.
Dates are targets; one team member builds everything (DECISIONS.md 2026-10-27), so apply the scope
guard in CLAUDE.md early. M0–M2 are the critical path — everything AI depends on them.

## M0 · Foundations (27–28 Oct)
- [x] Monorepo layout from ARCHITECTURE.md; `docker compose up` brings db (postgres), qdrant, mock-llm, backend, worker, frontend
- [x] `backend/app/core/config.py` (pydantic-settings) reads every var in `.env.example`; app refuses to start if `CLOUD_API_KEY` is missing **only** when the resolved provider is cloud
- [x] `.env` in `.gitignore`; `.env.example` complete; gitleaks runs in CI
- [x] Alembic initial migration; SQLAlchemy models for users, worlds, jobs, ai_cache, ai_call_log
- [x] Frontend: Vite + TS + Tailwind with tokens, fonts, i18n (4 locales, RTL switch), router, `/styleguide` route with all primitives from DESIGN.md
- [x] CI: ruff, pytest, eslint, tsc, vitest
**Done when:** fresh clone → `cp .env.example .env` → `docker compose up` → styleguide renders in EN and AR (RTL) and `/api/health` is green.

_Status 28/10:_ **Done-when passes.** Fresh clone → `cp .env.example .env` → `docker compose up --build`
(with `NPM_REGISTRY=https://registry.yarnpkg.com/`, our network blocks registry.npmjs.org) → all 6 services
up, `/api/health` = `{"status":"ok","db":"ok","qdrant":"ok","provider":"mock"}`, Alembic at `0001 (head)`,
`/styleguide` renders in EN and AR (RTL) at 1440×900 and 390×844 with no console errors or horizontal
scroll. ruff, pytest (22 pass incl. the migration test against Postgres), eslint, tsc, vitest (17),
`i18n:check` and the constraint greps pass. CI (29/10, after the first push to GitHub): gitleaks +
constraint greps, backend (ruff, pytest against Postgres, Tesseract), mock-llm, frontend (eslint, tsc,
vitest, i18n) all green.

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
  - [x] Providers kept apart: Qdrant collection = `{prefix}-{provider}-{embedding model slug}` with
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
- [x] **In-slot model probe:** `python3 scripts/probe_models.py` → fills docs/MODELS.md results, prints recommended `.env` lines (models, embedding dim, ceilings, quota header names); record in DECISIONS.md
      _30/10:_ compact `llama3.2-3b`, mid `llama3.1-8b` (DECISIONS.md); **no embeddings model on our key** (OPEN: to ask the organisers)
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
- [x] Wallet ledgers, daily refill (Africa/Tunis), earn cap, refunds, demo purchase, out-of-coins screen
- [x] Points, streaks, class + global leaderboards (opt-out)
- [x] Teach-Back peer room (ask with moderation, answer, AI grade draft-then-revise, pin best, helpful votes, polling) + solo mode
**Done when:** two browsers in the same world can ask/answer and see scores and leaderboard change.

_Status 30/10:_ **Done-when passes** through the real UI (MCP Playwright, two browser contexts, compose
stack with mock-llm `p_503_mid` 0.15, seeded `OLIVE-7Q2`): Yasmine asks in the Data Structures arena
(20 → 18 coins, moderation job) → Karim sees it in the polled feed, answers → scored 84 by ONE compact
call (outside the review band, no mid) → +3 coins, +30 points → Yasmine sees the score and pins it →
+50 points → both leaderboards show Karim at 80. Also via the API with two dev users (a 45 answer: no
coins; improved to 84: +3 coins once). AR at 390×844: `dir=rtl`, no horizontal scroll. Tests: 223
backend (wallet, leaderboard, arena incl. review band, mid-busy keeps the draft, refunds, permissions),
25 mock-llm, 46 frontend; ruff, eslint, tsc, i18n (687 keys × 4), constraint greps pass. **Open:** load
smoke (10 jobs, 503 + quota) completes 10/10 with ≤ 2 in flight and all faults handled, but reports
FAIL on "no fallback observed": with ~4 interactive jobs a double 503 is rare, so that check is
chance-driven (same result before M5 today; M1's 30-job run saw 1) — make the check deterministic
(e.g. one forced-503 interactive job) before the demo; "ask the AI after 10 min without a peer answer"
deferred (DECISIONS); Darija strings drafted, need native review (M8); the visual compare with mockup 15
was done in EN at 1440×900, AR checked by layout metrics only.

## M6 · Daily challenges + Class Wisdom (6–7 Nov)
- [x] Daily plan (plan-once mid) + daily return screen + challenge progress tracking
- [x] Wisdom: tag counting, threshold → mid tip, tips on loading screens and Quiz Hall
**Done when:** 3 seeded students making the same mistake produce a tip shown on the next loading screen.

_Status 30/10:_ **Done-when passes**, in pytest (`test_done_when_seeded_tip_reaches_a_newcomer`: seed
→ ONE mid WISDOM_TIP call → a newcomer gets the tip, student_count 3; re-seeding makes no second call)
and through the real UI (MCP Playwright, compose stack on mock): `python -m app.seed` → seed-ana,
seed-bilel and seed-cyrine share one Calculus mistake → one tip in en + ar (the world's languages, one
call) → a brand-new Arabic student joins `OLIVE-7Q2` and the next loading screen (placement, then
Teach-Back solo) shows the Arabic tip, RTL. Daily: first `GET /api/daily` writes a rule plan at once,
the background DAILY_PLAN job (1 mid call) replaced it ("Planned for you") with the "why" lines;
side panel and daily return screen checked in AR at 1440×900 and 390×844 (no horizontal scroll);
Continue → map, no second redirect. Tests: 238 backend (daily: catalogue validation, rewards once, earn
cap, all-3 bonus, AI plan never overrides progress; wisdom: threshold, distinct students, one call for
N languages, no nicknames in the prompt, unusable reply → retried by the next student), 27 mock-llm,
50 frontend; ruff, eslint, tsc, i18n (710 keys × 4), constraint greps pass; load smoke (10 jobs, 503 +
quota) PASS with 2 fallbacks. **Open:** flashcard challenges + CHALLENGE_ITEMS wait for M7; the Quiz
Hall results wisdom card is covered by typecheck and the tip component test, not yet seen in a browser;
mock tips reuse the English concept word inside Arabic text (real models write it in the language);
new Darija strings need native review (M8); real-model tips/plans not yet generated (next slot).

## M7 · Study Studio → Audio Studio (7–8 Nov; cut Audio first)
- [x] Notes, flashcards with SRS, mind map; shared cache; Class Pool payment
- [x] Audio script + Web Speech player with transcript and speed

_Status 30/10 (Phase A):_ **Study Studio + Class Pool pass** through the real UI (Playwright/Chromium
against the compose stack on mock, demo world `OLIVE-7Q2`): student A (EN) opens the studio → 15
coins, generate panel → loading stages → notes with page refs, mind map, 12 cards; Space flips, 1/2/3
grade with the server's intervals (Again 1 min · Good 10 min · Easy 3 days). Student B (EN) opens it
free with no new call; B gives 15 coins to the pool; student C (AR, 390×844) pays an Arabic pack
from the pool (15 → 0), RTL, mirrored mind map, no horizontal scroll, no console errors. The log
shows exactly 1 NOTES_WRITE (mid) + 1 FLASHCARDS + 1 MAP_WRITE (compact) per pack and nothing
for later students. Tests: 251 backend (pack = 1 mid + 2 compact then free, shared pending job,
pool pay + refund on failure, failed map keeps notes and cards and a free run fills it, SRS, daily
`flashcards` challenge, quiz cards personal with no AI call, members only), 28 mock-llm, 55
frontend; ruff, eslint, tsc, i18n (769 keys × 4), constraint greps pass; load smoke (10 jobs,
503 + quota) PASS with 1 fallback. **Open:** "Turn these into flashcards" is covered by API and
component tests, not yet clicked in a browser; mock notes reuse English concept words inside
Arabic text (real models write in the language); new Darija strings need native review (M8); no
real-model pack yet (in-slot); Audio is Phase B.

_Status 30/10 (Phase B):_ **Audio Studio passes**: through the real UI (EN 1440×900, AR 390×844) a
student pays 15 coins → loading stages → the episode transcript (headless Chromium has no voices, so
the "no voice" transcript-only state shows, RTL, no horizontal scroll). Tests: 254 backend (1 mid call
per episode then free, shared job, pool refund on an unusable script and a fresh retry call), 29
mock-llm, 59 frontend (segment-by-segment speech with highlight, speed, jump, Darija and no-voice
transcript-only). All five buildings now open. **Open:** playback with real voices checked only with a
faked `speechSynthesis` (needs a desktop browser); Darija TTS stays OPEN (silma-tts); no real-model
episode yet (in-slot).

## M8 · Ship (8–9 Nov)
- [x] Offline demo mode (`/api/system/status` + banner, disables new AI actions)
- [ ] Deploy (Vercel + Render/Railway), seed demo world, Darija review by native speakers
- [ ] User test with ~10 students simultaneously (in-slot); export stats for report
- [ ] README (setup, architecture, GenAI module explanation, screenshots), demo video ≤ 1:30 (show shared world, fallback, queue + Wisdom tip), 6-page report

_Status 30/10 (in progress):_ **Offline demo mode passes**: interactive starts answer 503
`errors.offline` before any coin is reserved; background work waits for the next slot; a running
job caught by the switch fails with a refund (interactive) or requeues (background); the banner
shows on every screen with the next live time (Tunis, 24 h) and AI start buttons are disabled,
while saved results and the arena feed stay open. Checked with `OFFLINE_DEMO_MODE=on` in EN and AR
at 1440×900 and 390×844 (RTL, no horizontal scroll, no app console errors). Tests: 260 backend
(6 offline), 64 frontend; load smoke PASS with the new deterministic forced-503 fallback check.
**Deploy:** config in place (`backend/start-prod.sh` + `railway.toml`, `frontend/vercel.json`,
`docs/DEPLOY.md`; the start script smoke-tested in a container); accounts, secrets, seed and
warm-up are human steps. **Blocked:** no embeddings model on our cloud key (DECISIONS.md OPEN),
so cloud indexing can't run yet. **README** rewritten (GenAI module, setup, privacy, services);
screenshots still to capture. Report draft and video shot list in `docs/report/`; stats export
via `scripts/export_stats.py`. Human: Darija review, ~10-student user test, video.
