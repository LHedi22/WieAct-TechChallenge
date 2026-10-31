# Learning World — Claude Code guide

Gamified peer-learning web app for university students (EdNova "GenAI Peer Learning Companion",
IEEE WIE ACT 5.0). Each course becomes an island on a Mediterranean archipelago map; each island
has five AI "buildings". **Phase 1 deadline: 10 Nov 2026** (report + repo + 90 s demo video).
A working end-to-end app is required — no mockups, no notebooks.

## Where we are (31 Oct)
M0–M7 built and green on the mock; M8 (ship) in progress (offline mode done; deploy, in-slot run,
report, video, avatar redesign left). **@docs/STATUS.md lists everything still
missing** (blockers, in-slot work, deploy, deliverables). Read it first and tick items there as
they close. Our cloud key has **no embeddings model**, so embeddings come from our own Ollama with
`bge-m3` (`EMBED_PROVIDER=local`; Mac in dev, a Railway service in production). Cloud models: compact `llama3.2-3b`, mid `llama3.1-8b`
(no thinking models → `LLM_DISABLE_THINKING=false`). We are slot **Group A**.

## Read before working
- @docs/PLATFORM.md — the LLM platform's hard limits and error contract (scored 25% + 15%)
- @docs/ARCHITECTURE.md — repo layout, AI gateway, jobs, data model, API
- @docs/BUILD_PLAN.md — milestones with acceptance criteria; work on ONE milestone at a time
- docs/PRODUCT.md — features and user flow (read the section for the feature you're building)
- docs/MODELS.md — which platform models we use and why (probe results)
- docs/ECONOMY.md — coin/point numbers (single source: `backend/app/core/economy.py`)
- docs/DESIGN.md — tokens, components, screens; **overrides the mockups where they disagree**
- docs/DECISIONS.md — open questions; never silently decide one, ask or log it there
- docs/DEPLOY.md — Railway (API + worker in one service) + Vercel + Qdrant Cloud; human steps
- docs/report/ — report draft (`REPORT.md`, fill the [in-slot] gaps) and video shot list

## Non-negotiable rules
1. **Never read, print, log or commit the API key.** It lives only in `.env` (gitignored).
   Never open `.env`; use `.env.example` to learn variable names.
2. **Read the provider settings from `settings.llm`** (`LLM_PROVIDER` + `CLOUD_`/`LOCAL_`/`MOCK_`
   profiles, resolved in `backend/app/core/config.py`); never hard-code base URLs or model names.
   Vector store is **Qdrant** (`QDRANT_URL`, `QDRANT_COLLECTION_PREFIX`, the profile's `*_EMBEDDING_DIM`) behind `VectorStore`.
3. **Every LLM / embeddings call goes through `backend/app/gateway/`.** No feature module imports
   `openai` directly. The frontend never talks to the LLM.
4. **Every AI action is a job** (row in `jobs`), executed by the worker; the frontend polls
   `GET /api/jobs/{id}` every 1.5 s. No streaming exists on the platform.
5. **Cache-first.** Shareable outputs (notes, flashcards, maps, audio scripts, quiz pools, tips)
   are keyed by `world, chapter, level, language` and generated once per class.
6. **Anonymous by design.** Nicknames only. Never add fields for real name, photo, age, gender,
   email-as-identity, address or voice. Demo data is synthetic/public only.
7. **Hints before answers.** The Socratic Tutor never states the final answer; quizzes give a hint
   and a second try before the explanation.
8. **All user-visible strings go through i18n** (`en`, `fr`, `ar`, `ar-TN` for Darija). Arabic is
   RTL: use logical CSS properties (`ms-`, `me-`, `ps-`, `start`, `end`), never `left/right`.
9. Economy numbers come from `economy.py` / `GET /api/economy`; never hard-code a coin amount in UI.

## Commands
```bash
docker compose up -d db qdrant mock-llm   # Postgres + Qdrant + mock LLM (work outside time slots)
python3 scripts/probe_models.py           # in-slot only: benchmark platform models → docs/MODELS.md
python3 scripts/probe_embeddings.py [names]  # in-slot only: find the cloud embeddings model
python3 scripts/export_stats.py [--api URL] [--load out.txt]  # /api/admin/stats → docs/report/
docker compose exec backend uv run python -m app.evals slot [--cloud]  # every AI feature × 4 langs → tests/evals/slot/outputs
cd backend && uv run uvicorn app.main:app --reload   # API on :8000
cd backend && uv run python -m app.worker            # job worker
cd backend && uv run pytest -q                       # backend tests
cd backend && uv run ruff check . && uv run ruff format .
cd frontend && pnpm dev                              # web on :5173
cd frontend && pnpm test && pnpm lint && pnpm typecheck
```
Switch to the real platform with `LLM_PROVIDER=cloud` (or `auto`) in `.env` — only during the team's
time slot (`/slot` tells you). Default for development and tests is the mock; local Ollama is dev-only.
Before any in-slot run, `CLOUD_API_KEY` must be filled in `.env` by a human; `probe_models.py` exits
with "Set CLOUD_BASE_URL and CLOUD_API_KEY" (zero calls made) if it isn't. `scripts/llm.py status`
only shows the key as set/empty for the *active* provider.

No `uv` or `node_modules` on the host? Run the checks inside the compose containers:
```bash
# backend (db up); some tests also read mock-llm/src, scripts/, docs/, design/, .env.example and
# docker-compose.yml, so mount them into the container with -v "$PWD/<path>:/<path>:ro"
docker compose run --rm -T --no-deps backend uv run pytest -q
docker compose exec -T frontend sh -c 'pnpm lint && pnpm typecheck && pnpm test --run && pnpm i18n:check'
```
If `db` can't bind port 5432, a host PostgreSQL is already using it; stop that service first.

Gotchas seen on the macOS dev machine:
- The stdlib scripts (`probe_*.py`, `export_stats.py`) fail with `CERTIFICATE_VERIFY_FAILED`
  against the platform (no request is sent): prefix them with `SSL_CERT_FILE=/etc/ssl/cert.pem`.
- Load test from the backend container: `docker compose run --rm -T --no-deps -v "$PWD/scripts:/scripts:ro"
  backend uv run python /scripts/load.py --jobs 10 --api http://backend:8000 --mock http://mock-llm:9000`.
  The `worker` container doesn't auto-reload: `docker compose restart worker` after backend changes.
- Regenerate API types inside the frontend container, then format them (the committed file is prettier-formatted):
  `docker compose exec -T frontend sh -c 'pnpm exec openapi-typescript http://backend:8000/openapi.json -o src/api/schema.d.ts && pnpm exec prettier --write src/api/schema.d.ts'`
- Force offline demo mode locally: `docker compose stop backend && docker compose run -d --service-ports
  --name lw-offline -e OFFLINE_DEMO_MODE=on backend` (afterwards `docker rm -f lw-offline && docker compose up -d backend`).
- The Docker MCP browser can't reach `localhost` and Vite rejects `host.docker.internal`: open
  `http://localhost:5173` and route `localhost:(5173|8000)` to `host.docker.internal` with the
  original Host header (`page.context().route` + `route.fetch`). Its screenshots stay in its container.

## Way of working
- Start each milestone in plan mode; write the plan, then implement in small commits.
- Write the test first for gateway, economy and grading logic.
- Before saying a milestone is done, run `/verify` and tick its acceptance criteria in
  `docs/BUILD_PLAN.md`.
- When a feature needs an AI call, follow the `ai-feature` skill.
- When building a screen, follow the `ui-screen` skill and compare with `design/mockups/`.
- Keep prompts in `backend/app/prompts/*.md` (versioned, multilingual), not inline in code.
- Log decisions you had to make in `docs/DECISIONS.md` (one line each).

## Scope guard
If time is short, cut in this order: Audio Studio → mind maps → Class Pool → global leaderboard
→ cosmetics. Never cut: gateway resilience, Quiz Hall, Socratic Tutor, Teach-Back peer room,
Class Wisdom, multilingual UI.
