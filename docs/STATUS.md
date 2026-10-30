# What's still missing — as of 30 Oct 2026, 21:30 Tunis

Deadline **Tue 10 Nov** (report + repo + 90 s video); record the demo by **Mon 9 Nov**. M0–M7 are
built and pass their Done-when checks on the mock. Remaining work, most urgent first. Details
are in `docs/BUILD_PLAN.md` (status lines) and `docs/DECISIONS.md` (OPEN items). Update this file
whenever an item closes.

## 1. Blockers
- [ ] **Cloud embeddings model.** Our key (hack-04) lists no embeddings model. `/v1/embeddings`
      rejects every name we tried with 400 "Invalid model name". Without one, nothing can be
      indexed on the cloud (uploads, the seeded demo world, then quiz pools, notes and audio).
      → A human emails wie.act@ieee.tn: "hack-04: `/v1/models` lists only chat models and
      `/v1/embeddings` answers 400 'Invalid model name' for every name; which embeddings model
      should our key use?" Fallback, a human decision:
      an embedder inside our backend, declared as an external service. When the answer comes, run
      `python3 scripts/probe_embeddings.py <name>`, put `CLOUD_EMBEDDING_MODEL/DIM` in `.env`, and
      run `uv run python -m app.rag.reindex --provider cloud` in our slot.
- [ ] **`.env` cloud lines** (a human pastes them; Claude never opens `.env`):
      `CLOUD_MODEL_COMPACT=llama3.2-3b`, `CLOUD_MODEL_MID=llama3.1-8b`, `LLM_DISABLE_THINKING=false`.

## 2. In-slot work (needs the live key; Group A: Mon 02/11 00–12, Tue 03/11 12–24, …)
Check with `python3 scripts/slot.py`. On macOS, prefix the stdlib scripts with
`SSL_CERT_FILE=/etc/ssl/cert.pem`.
- [ ] Real-model end-to-end run in EN, FR, AR (and Darija): placement, quiz, tutor, study pack,
      audio, Teach-Back, wisdom tip, daily plan. Nothing has run on the cloud yet except the probe.
- [ ] **Prompt eval (M4 box):** 20 generated questions per language from real outputs → the
      `prompt-evaluator` agent over `backend/tests/evals/*/outputs/`, results stored for the report.
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
- [ ] Dev-only Local/Cloud/Mock badge in the top bar (it's only on `/dev/jobs`). The rest of
      M1 "Providers kept apart" is built: per-provider collections, provider in cache keys and
      the call log, stats default to cloud, offline serves cloud cache only.
- [ ] Ending a Tutor session while offline answers 503 (the summary needs AI). Option: end
      without a summary when paused.
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
