---
name: verify
description: Run before declaring any milestone or feature done (/verify). Runs linters, type checks, tests, secret and constraint checks, then checks the milestone's acceptance criteria in docs/BUILD_PLAN.md.
---

# Verify

Run each step; stop and fix on the first failure. Report a short table: step → pass/fail.

1. Backend: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
2. Frontend: `cd frontend && pnpm lint && pnpm typecheck && pnpm test --run`
3. Secrets & constraints (from the repo root):
   - `git ls-files | grep -E '(^|/)\.env$'` must print nothing
   - `grep -rn "felcloud" --include='*.py' --include='*.ts' --include='*.tsx' backend frontend mock-llm` must print nothing
   - `grep -rln "import openai\|from openai" backend/app | grep -v gateway/` must print nothing
   - `grep -rnE "chat/completions|(CLOUD|LOCAL|MOCK)_API_KEY" frontend/src` must print nothing
   - every key in `en.json` exists in `fr.json`, `ar.json`, `ar-TN.json` (`pnpm i18n:check`)
4. Resilience smoke (when M1 is done): `docker compose up -d db mock-llm` then
   `uv run python ../scripts/load.py --students 10 --faults 503,quota` — all jobs finish, max
   concurrency ≤ 2, fallbacks > 0, no 5xx surfaced to the client.
5. Open `docs/BUILD_PLAN.md`, re-read the current milestone's **Done when** line, and check it
   by actually running it. Tick the boxes that are truly done; leave the rest unticked and say why.
