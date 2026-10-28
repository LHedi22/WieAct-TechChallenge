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
