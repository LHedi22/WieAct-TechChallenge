# Learning World

> Working name. Your courses, turned into islands you explore — a GenAI peer-learning companion for
> university students, built for the EdNova "GenAI Peer Learning Companion" technical challenge
> (IEEE WIE ACT 5.0).

_This README is a skeleton. Claude Code completes it in milestone M8 (setup, screenshots,
GenAI module explanation, declared services)._

## What it does

Upload your course material once; every classmate who joins your world gets the same islands.
Each island has five buildings: **Quiz Hall** (hints before answers), **Socratic Tutor** (questions,
not answers), **Study Studio** (notes, flashcards, mind maps), **Audio Studio**, and the
**Teach-Back Arena** (explain to classmates, get AI-scored). Shared mistakes become anonymous
**Class Wisdom** tips. Arabic, Darija, French and English.

## How it uses the platform (GenAI module)

See `docs/ARCHITECTURE.md` → routing table and `docs/PLATFORM.md` → error contract.

- Compact model for triage, tagging, quiz generation, grading, tutor turns, moderation, fallback.
- Mid-size model only for synthesis and planning: notes, maps, audio scripts (once per class),
  daily plans (once per student per day), Class Wisdom tips, review of uncertain grades.
- One gateway: cache → priority queue → limiter (2 concurrent, < 20/min) → contract handling
  (quota delay requeue, 503 retry/fallback, 400 shrink) → call log.

## Setup

```bash
cp .env.example .env            # put the key in CLOUD_API_KEY (in .env only); never commit .env
docker compose up --build       # db, qdrant, mock-llm, backend, worker, frontend
```

Then open http://localhost:5173/styleguide (design system, EN/FR/AR/Darija, `?compare=1` for
English and Arabic side by side) and http://localhost:8000/api/health (`"status": "ok"`).
Migrations run automatically when the backend container starts.

**Windows:** run Docker Desktop first. Git Bash and PowerShell both work for the commands above
(`copy .env.example .env` in cmd). The repo forces LF line endings (`.gitattributes`), so a
Windows clone builds the Linux images unchanged.

Without Docker (dev loop):

```bash
docker compose up -d db qdrant                        # or a local Postgres on :5432
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && pnpm install && pnpm dev
```

Checks: `cd backend && uv run ruff check . && uv run pytest -q` ·
`cd frontend && pnpm lint && pnpm typecheck && pnpm test --run && pnpm i18n:check`.
`LLM_PROVIDER` in `.env` picks the model provider: `mock` (default), `local` (Ollama on your machine,
dev only), `cloud` (the EdNova platform, our time slot only) or `auto`. Production and the demo use
only `cloud` — see `docs/ARCHITECTURE.md` → Providers.

## Declared external services

See `docs/DECISIONS.md` → Declared external services.

## Privacy

Nicknames only. No names, photos, voices, ages, genders or addresses are collected. Demo data is
synthetic or openly licensed.
