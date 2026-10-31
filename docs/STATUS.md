# What's still missing — as of 31 Oct 2026, 01:00 Tunis

Deadline **Tue 10 Nov** (report + repo + 90 s video); record the demo by **Mon 9 Nov**. M0–M7 are
built and pass their Done-when checks on the mock. Remaining work, most urgent first. Details
are in `docs/BUILD_PLAN.md` (status lines) and `docs/DECISIONS.md` (OPEN items). Update this file
whenever an item closes.

## 1. Blockers
- [x] ~~Cloud embeddings model~~ → **decided 31/10: our own Ollama with `bge-m3`**
      (`EMBED_PROVIDER=local`; DECISIONS.md). Dev: `ollama pull bge-m3` on the Mac (done) and
      `EMBED_PROVIDER=local` in `.env`. Production: the Railway `ollama` service (DEPLOY.md).
      Still worth telling the organisers we self-host embeddings (declared service).
- [x] `.env` lines added (31/10): cloud models, thinking off, `EMBED_PROVIDER=local`. Dev data
      re-indexed with `bge-m3` (4 files, 47 chunks → `hack-04-chunks-local-bge-m3`); EN/FR/AR
      queries find the right chapter (EN↔AR similarity 0.77 vs 0.38 unrelated).

## 2. In-slot work (needs the live key; Group A: Mon 02/11 00–12, Tue 03/11 12–24, …)
Check with `python3 scripts/slot.py`. On macOS, prefix the stdlib scripts with
`SSL_CERT_FILE=/etc/ssl/cert.pem`.
- [ ] **First thing in the slot:** `docker compose exec backend uv run python -m app.evals slot --cloud`
      (with `LLM_PROVIDER=cloud` in `.env`, then `docker compose restart backend worker`). It runs
      study pack, audio, daily plan, Teach-Back (solid + partial answer) in EN, FR, AR and Darija
      plus one Class Wisdom tip: about 30 calls, 17 mid, ~10–20 min. Outputs go to
      `backend/tests/evals/slot/outputs/cloud-*.json`; then `python3 scripts/export_stats.py`
      on the host. Tested on the mock only (31/10). Afterwards switch back with
      `python3 scripts/llm.py use mock` (or `auto`).
- [ ] Placement, quiz and Tutor on the real models by hand in the browser (the slot run doesn't
      cover them; the quiz eval below does the questions).
- [ ] **Prompt eval (M4 box):** `uv run python -m app.evals quiz --langs en,fr,ar,ar-TN` in-slot
      (20 questions per language), then the `prompt-evaluator` agent over
      `backend/tests/evals/*/outputs/cloud-*` (quiz + the slot run), results stored for the report.
      Also review `scripts/out/probe-cloud-20261030-1806.json`; check Darija by hand.
- [ ] Watch for prompts that small models break (JSON validity on `llama3.2-3b`; the probe said
      `qwen2.5-3b` failed quiz JSON, ours passed).
- [ ] Load test against cloud once: `scripts/load.py --jobs 10 --faults ""` with the backend on
      `LLM_PROVIDER=cloud`, then `scripts/export_stats.py --load <saved output>`.
- [ ] Record the real quota signal: the status code for "team quota exhausted" and any quota
      headers (none on 200 so far) → DECISIONS.md, `quota.py` if needed.
- [ ] Warm up the deployed class cache (DEPLOY.md §4) so offline demo mode has real content.
- [ ] User test with ~10 students at once; export stats for the report.
- [ ] Record the demo video (`docs/report/VIDEO.md` shot list).

## 3. Deploy (config is in the repo; the rest is a human with accounts)
- [x] Qdrant Cloud cluster created (31/10). Check it with `scripts/check_qdrant.py` (URL + key
      from your own terminal). Its URL and key go **only** into Railway's variables, not `.env`:
      dev keeps the compose Qdrant so mock/local collections never land in the cloud cluster.
- [ ] Railway project (service root `backend`, `railway.toml`, Postgres, volume at `/data`),
      Vercel (root `frontend`; replace `REPLACE-WITH-RAILWAY-DOMAIN` in `frontend/vercel.json`).
      Steps and variable names: `docs/DEPLOY.md`.
- [ ] Seed the demo world in-slot, check `/api/health` and the offline banner after the slot.
- [ ] Check that a multi-MB upload works through the Vercel rewrite (fallback in DEPLOY.md).

## 4. Deliverables still to write or finish
- [ ] **Screenshots** for the README (EN + AR, desktop + phone) → `docs/screenshots/`, linked
      from README. The Docker MCP browser can't save into the repo; use a desktop browser or a
      Playwright installed in the frontend container.
- [ ] **Report** (≤ 6 pages): fill the **[in-slot]** gaps in `docs/report/REPORT.md` and export
      it to PDF.
- [ ] **Video** ≤ 1:30.
- [ ] **Darija review** by native speakers: every string in `frontend/src/i18n/ar-TN.json`
      (drafted by Claude, flagged `_review`), plus real-model Darija outputs.

## 5. Code still to do (small)
- [x] Dev-only Local/Cloud/Mock badge in the top bar (31/10). M1 "Providers kept apart" is
      complete: per-provider collections, provider in cache keys and the call log, stats default
      to cloud, offline serves cloud cache only.
- [x] Ending a Tutor session while offline saves it without the summary (31/10).
- [x] Teach-Back: Arabic and Darija graded by mid; unsure grades wait (`pending_review`); shared
      prompt voice rules (31/10, DECISIONS.md).
- [x] `ai_cache` race fixed (31/10): two packs in different languages embedding the same query at
      once crashed one job. Found by the mock slot run.
- [ ] **Avatar step redesign** (onboarding step 4, user feedback 31/10: "make it smoother and more
      fun to build").
- [ ] Optional: the KaTeX swap for `MathText` if the npm registry allows it.
- [ ] Optional: "ask the AI after 10 min without a peer answer" (deferred, DECISIONS.md).

## 6. Not yet seen in a real browser (covered by tests only)
- Quiz Hall results Class Wisdom card · "Turn these into flashcards" · Audio playback with real
  voices (headless Chromium has none) · Arabic OCR on a real Arabic scan · real embeddings (only
  the mock's bag-of-words vectors so far) · the BuildingDialog "paused" note while offline.

## 7. Dev-only leftovers (not needed for the demo)
- [ ] `scripts/setup_ollama.ps1/.sh` written but never run; Docker → host Ollama untested
      (Ollama is dev only and never used in the demo).

## 8. Open decisions for humans (DECISIONS.md)
Embeddings model / fallback · platform Qdrant reachable? (default: our own, declared) ·
quota signal · slot alternation continuing to 10/11 · final app and mascot name · pixel art
source (sprites are placeholders) · Darija TTS (default: transcript only).

## Scope guard (CLAUDE.md)
If time runs short, cut in this order: Audio Studio → mind maps → Class Pool → global leaderboard
→ cosmetics. Never cut: gateway resilience, Quiz Hall, Socratic Tutor, Teach-Back, Class Wisdom,
multilingual UI.
