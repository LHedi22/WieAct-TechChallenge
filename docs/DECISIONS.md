# Decisions & open questions

One line per entry, newest first. Claude Code appends here whenever it has to decide something
that isn't in the docs. Humans resolve OPEN items.

## Open (need a human or the organisers)
- OPEN: Is the platform's Qdrant reachable from our backend (URL + API key)? If not, host our own Qdrant
- OPEN: Install Ollama + pull models (human, any time before M1 ends). Until then: mock. Steps in BUILD_PLAN.md M1 → Provider switching
  - 27/10: Ollama 0.40.9 already installed on the dev laptop (15.4 GB RAM → `qwen3:8b` as mid). OLLAMA_* user env vars set; `qwen3:1.7b`, `qwen3:8b`, `bge-m3` pulled (not yet run). Left: restart Ollama so it reads the env vars; `.env` switch to `LLM_PROVIDER=local` once M1's provider code exists
- OPEN: Exact model names → run `scripts/probe_models.py` in our slot; pick per docs/MODELS.md
- OPEN: Quota header names and the exact status code for "team quota exhausted"
- OPEN: Does chat/completions support `response_format: json_object`?
- OPEN: Max response length ceiling (tokens) per request
- OPEN: Our slot group (A or B) and whether the alternation continues to 10/11
  - 27/10 19:03 Tunis (Group B half per slot.py): `GET /v1/models` → `401 auth_error "Key is blocked"`. Suggests we are **Group A** and that out-of-slot = 401 key blocked (gateway/system status should map this to offline demo mode). Re-check Wed 28/10 12:00.
- OPEN: Final app name (candidates: Jazira, Archipel, Kerkennah, Manara, Marsa, Atoll, Bahr, Learnipelago…) and mascot cat name — keep "Learning World" / `app.name` i18n key until decided
- OPEN: Pixel art source — draw the final sprites ourselves or use an openly licensed pack, and when?
- OPEN: Darija TTS — pregenerate with silma-tts-derja or transcript-only?

## Decided
- 2026-10-29 · M3 sign-in: argon2 password hashes; a self-contained signed cookie `lw_session` (user id + issued-at, HMAC-SHA256 with SECRET_KEY, HttpOnly, 30 days; no sessions table); `SESSION_COOKIE_SAMESITE`/`SECURE` settings for a cross-site deploy (none + true). `X-Dev-User` still works outside production, only when the header is sent; `GET /api/auth/session` answers 200 null when signed out
- 2026-10-29 · M3 wallet: `/api/wallet` returns the economy defaults (20 free coins, 0 points, no streak, real Tunis refill time) until the M5 ledgers; `/api/economy` (typed) is the only source of prices in the UI
- 2026-10-29 · M3 style test: 4 scenario questions scored on the server (1 point per style to start, +1 per answer, largest-remainder rounding to 100%); top two styles → suggested buildings (visual → Study Studio, practice → Quiz Hall, listening → Audio Studio, teaching → Teach-Back)
- 2026-10-29 · M3 placement: 8 questions per course + language from one compact call (2 chunks per chapter), shared by the class in `placement_sets`; the client never receives answers; level from difficulty-weighted score (< 40% beginner, ≤ 75% intermediate, else advanced); seeds `chapter_mastery` (< 50% = weak spot). Classmates starting together share one job
- 2026-10-29 · M3 side panel shows "Your class" (members + code) until M5 (leaderboard) and M6 (challenges) fill their slots; "on this island now" = presence pinged every 30 s, shown for 2 minutes
- 2026-10-29 · M3 avatar: pixel placeholder from {skin s1–s5, outfit o1–o5, extra}; extras priced in points in economy.py (`COSMETICS`), locked until points exist (M5). Skin tones added to tokens.json (`avatarSkin`). Map/island positions live in `design/assets/layout.json` (1–8 islands, reserved label slots); the scene is not mirrored in RTL
- 2026-10-29 · M3 building entry: the dialog (chapter, level, cost, balance after) is complete; Confirm leads to an "opens soon" screen until M4 opens Quiz Hall and Tutor — no coins spent
- 2026-10-29 · M2 users before sign-in: one seam `api/deps.py::current_user`; outside production the `X-Dev-User` header (nickname only, created on first sight, default `demo`) and `X-UI-Language`; production answers 401 until M3 adds cookie sessions
- 2026-10-29 · M2 embeddings go through `gateway.embed` (same contract: quota/503 → Defer, 400 → shrink the batch once and remember, 401 under auto → restart every batch on the new provider so one document never mixes providers); own RPM bucket `LLM_EMBED_MAX_RPM`, shared 2-concurrent limit; logged with tier `embed`, excluded from the compact/mid split
- 2026-10-29 · M2 request economy: CHUNK_TAG 8 chunks/call (first 1,200 characters of each), embeddings 32/call → ~5 calls for a 30-page PDF; CHUNK_TAG cached by file hash; same file twice in a chapter is indexed once; search queries' embeddings cached
- 2026-10-29 · M2 chunking without a tokenizer: 2,000 characters ≈ 500 tokens, 240 overlap, never across a page or slide; scanned PDF pages (< 25 characters of text) and images through Tesseract `ara+fra+eng` at 200 dpi
- 2026-10-29 · M2 Qdrant (OPEN upstream: platform Qdrant reachable?): our own Qdrant (compose) by default, as already declared
- 2026-10-29 · M2 precompute: one QUIZ_POOL per chapter (intermediate, creator's language, compact, one call) when its last file is ready; the mockup's "Recording audio chapters" row is dropped (Audio is first to cut). Mock embeddings are hashed bag-of-words so search is meaningful offline
- 2026-10-29 · M2 island accents `island-1…6` are assigned by the server in creation order (DESIGN.md), not chosen in the wizard; join codes `WORD-XXX` from 20 Mediterranean words + 3 unambiguous characters; the world is created only after its courses and chapters are entered
- 2026-10-29 · M2 dev search runs as a `DEV_SEARCH` job (`POST /api/dev/search-jobs`) so even a dev query goes through the worker's limiter; "Go to my world" on the indexing screen waits for the M3 map
- 2026-10-28 · M1 quota signal (OPEN upstream): a 429, or any error whose message says "quota"/"rate limit", is quota; delay from `Retry-After` → `x-ratelimit-reset*` → a number in the message → 30 s. The job is requeued with `not_before`; the UI shows position + ETA
- 2026-10-28 · M1 503: interactive retries once (waiting `Retry-After`, capped at 5 s), then mid falls back to compact (`quick_mode`); background never falls back, it is requeued. Quick-mode answers are not cached, so the class later gets the mid-size version
- 2026-10-28 · M1 400 ceiling: resend once with the ceiling parsed from the message (else ×0.6), and remember it per provider so later calls don't hit it again
- 2026-10-28 · M1 `LLM_JSON_MODE=auto`: send `response_format=json_object`, drop it per model on a 400; always tolerant-parse, then ONE compact repair call
- 2026-10-28 · M1 single-flight: identical cacheable tasks in flight at once share one model call (found by the stats test: two classmates opening the same notes made two calls)
- 2026-10-28 · M1 worker: one process (the limiter is process-local); background jobs in flight capped at `LLM_MAX_CONCURRENCY`, interactive up to 6, so a waiting student is never stuck behind precompute; a job fails after 8 attempts (deferrals included) and coins are refunded
- 2026-10-28 · M1 `auto`: cloud while the slot is live, the cloud profile is set and no cloud 401 is in `ai_call_log` since the slot started; else local. Production + cloud outside the slot → offline demo mode (cached cloud results only)
- 2026-10-28 · M1 queue ETA = position × average latency of the last 30 successful calls ÷ concurrency (8 s default), or the `not_before` wait if longer
- 2026-10-28 · Tests use a separate `<db>_test` database (created on demand) so they never touch dev data; mock-llm runs in-process for backend tests
- 2026-10-28 · `python -m app.rag.reindex --provider cloud` needs chunks, so it lands with M2; M1 ships the per-provider collection naming (`collection_for`)
- 2026-10-28 · Our network blocks `registry.npmjs.org` by hostname (same Cloudflare IPs answer as `registry.yarnpkg.com`); the frontend image takes `NPM_REGISTRY` (default npmjs) for Corepack and pnpm — set `NPM_REGISTRY=https://registry.yarnpkg.com/` locally
- 2026-10-27 · M0: `LLM_PROVIDER=auto` resolves to `local` until M1 adds slot-aware per-job resolution (`app/core/slot.py`); the cloud key is required only when the resolved provider is cloud
- 2026-10-27 · M0: production refuses any `LLM_PROVIDER` other than `cloud` (including `auto`) and the default `SECRET_KEY`
- 2026-10-27 · M0: `mock-llm` is a health-only stub and `app.worker` an idle heartbeat so compose runs; both are built in M1
- 2026-10-27 · Frontend: Tailwind 3.4 with `tailwind.config.ts` reading `design/tokens.json` (no new colour tokens; tints via opacity); React 19, Vite 6, ESLint 9 (jsx-a11y doesn't support ESLint 10 yet)
- 2026-10-27 · Stepped corners = `radius.pixelStep` (2px) + ink border + lip shadow; no clip-path, which would clip the lip and the focus ring
- 2026-10-27 · Sprites: `Sprite` draws generated placeholders; `design/assets/sprites/<name>.png` replaces them with no code change
- 2026-10-27 · Darija strings are Claude drafts, flagged by `_review` in `ar-TN.json`, for native-speaker review (M8); `ar-TN` falls back to `ar`, then `en`
- 2026-10-27 · Docker: the backend venv lives at `/opt/venv` so the `./backend` bind mount (possibly holding a Windows `.venv`) never shadows it; the frontend image is built from the repo root so it can read `design/`
- 2026-10-27 · One team member does all the work (backend, AI, frontend, product, report, video), milestones in sequence with Claude Code; the 3-person split is dropped. Dates kept; the scope guard in CLAUDE.md applies early
- 2026-10-27 · Local dev models (Ollama) = qwen3:1.7b (compact), qwen3:14b (mid; qwen3:8b on laptops under 16 GB RAM), bge-m3 (embeddings, 1024 dims); fallbacks qwen2.5:1.5b / qwen2.5:14b. Cloud models come from `scripts/probe_models.py` in our slot; prefer the Qwen3 family if the platform lists it
- 2026-10-27 · Local models are dev-only, switched via `LLM_PROVIDER=local|cloud|mock|auto` (work scheduled in M1). Production and the demo use only the platform: the rules forbid replacement services during the demo, and live AI output must come from the platform
- 2026-10-27 · Vector DB = Qdrant (one collection, payload filters world/course/chapter); Postgres keeps relational data only — no pgvector
- 2026-10-27 · Platform base URL `https://llm.felcloud.io/v1`, key name hack-04 (key only in `.env`)
- 2026-10-27 · Economy numbers from ECONOMY.md override mockup placeholder numbers (see DESIGN.md §Mockup fixes)
- 2026-10-27 · Exam Pass = high daily limit (15 AI activities/day), never "unlimited"
- 2026-10-27 · Purchases simulated for the hackathon; Konnect/D17 described in business note only
- 2026-10-27 · Style B (16-bit pixel art) for the world, readable fonts for text — as in the mockup style guide
- 2026-10-26 · Stack: React+Vite+TS+Tailwind+Framer Motion+react-i18next / FastAPI+OpenAI SDK+Postgres; Postgres job queue with polling; no WebSockets
- 2026-10-26 · Sign-up: nickname + password only, no Google sign-in
- 2026-10-26 · Map: tap/click to enter, no walking avatar; list-view toggle

## Declared external services (must appear in README + report)
- Tesseract OCR (local, open source) — scanned pages and board photos
- Qdrant (open source) — vector store; self-hosted only if the platform's Qdrant is not reachable
- PostgreSQL (our hosting) — relational data
- silma-tts-derja (Apache-2.0, local) — Darija audio, if used
- Browser Web Speech API — TTS for ar/fr/en (client side, no data sent by us)
- Ollama (local, open source) — dev only, never used in production or the demo
- Hosting: Vercel (frontend), Render or Railway (backend + Postgres)
- No other LLM or AI API is used.
