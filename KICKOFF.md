# How to start with Claude Code

## One-time setup
1. Create the GitHub repo, unzip this folder into it, commit everything (`.env` is already ignored).
2. `cp .env.example .env`, set `LLM_SLOT_GROUP` (A or B) and paste the hack-04 key into `CLOUD_API_KEY` **in `.env` only**.
   Leave `LLM_PROVIDER=mock` for normal dev. In your slot: run `python3 scripts/probe_models.py`
   and paste the printed model lines into the `CLOUD_*` variables in `.env`.
3. Install: Docker, `uv` (Python 3.12), Node 22 + `pnpm`, Tesseract with `ara`, `fra`, `eng` packs.
   `jq` is optional: the hooks fall back to Python without it.
   *Optional, can wait until M1:* Ollama for local dev models outside our slot
   (`winget install Ollama.Ollama`, then `ollama pull qwen3:1.7b qwen3:8b bge-m3`; `qwen3:14b` instead
   of `qwen3:8b` with 16 GB RAM or more). Full steps in docs/BUILD_PLAN.md M1 → Provider switching.
   Until then dev uses the mock.
4. Install Claude Code and run `claude` in the repo root. Run `/hooks` once to confirm the two
   hooks are registered, and `/agents` to see the three reviewers.
5. Optional MCP: a browser/Playwright MCP so Claude can screenshot screens and compare with
   `design/mockups/` (add to `.mcp.json` once you pick one).

## Working solo
One team member builds everything, one milestone at a time in the order of docs/BUILD_PLAN.md:
backend + AI (gateway, mock, indexing), frontend (styleguide, map, building screens), product
(economy, prompts in 4 languages, seed material) and delivery (user test, report, demo video).
- One Claude Code session at a time; one branch per milestone, merged when `/verify` passes.
- Let Claude use subagents for independent pieces inside a milestone (e.g. a screen while you
  review the endpoint); keep the gateway and economy in the main session.
- The schedule was sized for three people: apply the scope guard in CLAUDE.md early, and keep
  in-slot time for the platform-only work (probe, evals, load test, demo recording).

## Session 1 — backend + AI (today)
```
Read CLAUDE.md and every file in docs/. Then run /slot.

We are starting milestone M0 and M1 together (see docs/BUILD_PLAN.md). Enter plan mode and
propose a plan for:
1. The backend skeleton (uv project, FastAPI app factory, pydantic-settings config reading every
   variable in .env.example, async SQLAlchemy + Alembic, health endpoint) and the models
   needed for jobs, ai_cache and ai_call_log.
2. mock-llm exactly as specified in mock-llm/README.md, with its Dockerfile.
3. The AI gateway in backend/app/gateway exactly as specified in docs/ARCHITECTURE.md
   (Task/Result models, router table, cache, global limiter, priority lanes, error contract,
   compact fallback with quick_mode, 400 shrink-once, JSON repair, call log), plus the job worker
   and GET /api/jobs/{id} with stages, queue position and ETA.
4. Tests first for every row of the error contract in docs/PLATFORM.md, run against mock-llm
   in-process.

Ask me about anything in docs/DECISIONS.md "Open" that blocks this; otherwise pick the default
the docs give and log it. Don't touch the frontend in this session.
```

## Session 2 — frontend (once the M0/M1 backend plan is approved)
```
Read CLAUDE.md, frontend/CLAUDE.md, docs/DESIGN.md and docs/PRODUCT.md, and look at every image
in design/mockups/. Use the ui-screen skill.

Milestone M0 frontend part: scaffold Vite + React + TS strict + Tailwind (theme from
design/tokens.json, including the AA-safe *-ink shades), Google Fonts, react-i18next with en, fr,
ar, ar-TN and RTL switching, React Router, TanStack Query, and a /styleguide route that
reproduces design/mockups/18-style-guide.png and 19-style-guide-world-pieces.png with real
components (PixelButton, PixelPanel, SoftCard, Banner, Chip, counters, ProgressBar,
SegmentedProgress, MasteryRing, Input, LoadingStages, Mascot placeholder). Placeholder sprites
behind a Sprite component so real pixel art can be dropped in later. Plan first.
```

## Daily rhythm
- Start: `/slot` — if live, do the in-slot backlog first (model names, quota headers, evals, load test).
- Each milestone: `/milestone` → plan → implement → `/verify` → ask the `constraint-auditor`
  (backend) or `design-reviewer` (frontend) subagent to review → fix → commit.
- After in-slot evals: ask the `prompt-evaluator` subagent to grade outputs.

## Before you start: things only you can do
- Ask on Discord: is the platform Qdrant reachable from our backend (URL/key)? embeddings model name; exact "quota exhausted" response; JSON mode support; weekend slots.
- Pick the app name and the cat's name.
- Decide whether to draw the final pixel sprites or use an openly licensed pack (the mockup PDF only contains flattened screenshots, no separate sprite files).
- Gather 2–3 openly licensed course PDFs for the seed world (e.g. OpenStax Calculus Vol. 1, an open data-structures text).
