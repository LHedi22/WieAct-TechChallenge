# Learning World — Claude Code guide

Gamified peer-learning web app for university students (EdNova "GenAI Peer Learning Companion",
IEEE WIE ACT 5.0). Each course becomes an island on a Mediterranean archipelago map; each island
has five AI "buildings". **Phase 1 deadline: 10 Nov 2026** (report + repo + 90 s demo video).
A working end-to-end app is required — no mockups, no notebooks.

## Read before working
- @docs/PLATFORM.md — the LLM platform's hard limits and error contract (scored 25% + 15%)
- @docs/ARCHITECTURE.md — repo layout, AI gateway, jobs, data model, API
- @docs/BUILD_PLAN.md — milestones with acceptance criteria; work on ONE milestone at a time
- docs/PRODUCT.md — features and user flow (read the section for the feature you're building)
- docs/MODELS.md — which platform models we use and why (probe results)
- docs/ECONOMY.md — coin/point numbers (single source: `backend/app/core/economy.py`)
- docs/DESIGN.md — tokens, components, screens; **overrides the mockups where they disagree**
- docs/DECISIONS.md — open questions; never silently decide one, ask or log it there

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
cd backend && uv run uvicorn app.main:app --reload   # API on :8000
cd backend && uv run python -m app.worker            # job worker
cd backend && uv run pytest -q                       # backend tests
cd backend && uv run ruff check . && uv run ruff format .
cd frontend && pnpm dev                              # web on :5173
cd frontend && pnpm test && pnpm lint && pnpm typecheck
```
Switch to the real platform with `LLM_PROVIDER=cloud` (or `auto`) in `.env` — only during the team's
time slot (`/slot` tells you). Default for development and tests is the mock; local Ollama is dev-only.

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
