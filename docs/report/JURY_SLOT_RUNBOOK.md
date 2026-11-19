# Jury-slot runbook (audit OPT-03)

No platform number exists yet: no slot run happened before the deadline, so the compact/mid
split, the cache indicator and the refusal counts the organisers compute on our key are still
`[in-slot]` in REPORT.md. When the platform is live again (the jury demo slot, widened tier: no
team is quota limited), run the steps below **in order** and stop wherever the slot ends. Each
step is useful on its own.

Request counts are estimates from the code and from mock runs on `fix/opt-audit-prefetch`. They
include the branch's changes: daily plans on compact, 12-question generation, the moderation
pre-filter and the chapter glossary.

`scripts/jury_slot.py` prints this plan (dry run). It runs a step only with `--cloud` and
confirms each step before starting it.

## 0. Before the slot (humans, no platform call)
- [ ] `CLOUD_API_KEY` filled in `.env` (dev) or in Railway's variables (deployed) by a human.
      Never paste it into a chat, a log or a screenshot.
- [ ] `LLM_PROVIDER=cloud` → `docker compose restart backend worker` (or redeploy).
- [ ] `ADMIN_TOKEN` set (32+ characters), in the same shell for the scripts.
- [ ] `/admin` → Switches: **prompt traces off**, force Quick mode off, background lane running.
- [ ] One limiter per key: the in-process evals (`teachback`, `quiz-keys`, `quiz`) refuse to start
      next to a live worker (OPT-19), so step 2 stops the worker for them and starts it again
      afterwards. `evals slot` and the load test go through the worker.
- [ ] `/api/health` shows `"provider": "cloud"`.

## 1. Warm the demo world (offline-proof first)
Offline demo mode serves only results the platform already produced (DEPLOY.md §4).

| Step | Command / action | ≈ requests | ≈ mid |
| --- | --- | --- | --- |
| 1a | `uv run python -m app.seed`, wait for indexing, run it again (Class Wisdom tip) | ~8 tag + 3 pools × 2 + 1 tip ≈ 15 | ≈ 4 |
| 1b | Placement for both courses in **all 4 languages** (F-OFF-2): one demo student per language | 8 × (1 + 1) = 16 | 8 |
| 1c | One study pack + one audio episode per course in EN and AR (Data Structures › Stacks and queues) | 4 × 3 + 4 + 2 glossary = 18 | 8 |
| | **Subtotal** | **≈ 49** | **≈ 20** |

Check: sign out, switch Offline demo mode on in `/admin`, and open placement in each of the 4
languages. It must open from the cache.

Prefetch (`PREFETCH_ENABLED`, on by default) runs **only while the key is live**: outside the
slot it plans nothing. Run the planner once in the slot, before the demo, so the class finds
chapters 1–2 ready in every member language (quiz set, study pack, audio, placement):
`docker compose exec backend uv run python -m app.jobs.prefetch --world <join code>`. It only
queues jobs (no call itself) and prints the mid used today against the three caps. One set
(chapter × level × language) is ≈ 7 requests, 3 mid; placement 2 requests, 1 mid per language.
Set it to `false` before the slot if quota is tight.
The quality pass (`PREFETCH_QUALITY_PASS`, off by default) adds 1 mid + 1 compact per pack and a
placement regeneration when keys fail. Turn it on for the warm-up **only if the measured mid share
stays under 40 %** (`/admin` Stats, "calls per tier"); the jury counts the compact/mid split.

## 2. Evidence for the report and the pitch

| # | Finding | Command (backend container unless noted) | ≈ requests | ≈ mid |
| --- | --- | --- | --- | --- |
| 2a | every feature × 4 languages | `uv run python -m app.evals slot --cloud` | ≈ 35 | ≈ 13 |
| 2b0 | — | stop the worker for the in-process evals: `docker compose stop worker` (host) | 0 | 0 |
| 2b | N-1/N-2, OPT-16 | `uv run python -m app.evals teachback --cloud` | ≈ 33 | ≈ 22 |
| 2c | N-3, OPT-14/15 | `uv run python -m app.evals quiz-keys --cloud` | 4 | 4 |
| 2d | N-3 on generated items | `uv run python -m app.evals quiz --langs en,fr,ar,ar-TN --n 10 --fresh` | 8 | 4 |
| 2e0 | — | start the worker again: `docker compose start worker` (host) | 0 | 0 |
| 2e | N-4, OPT-07 (host) | `python audit/tools/adversarial_probe.py --api <api> --parts moderation` | ≈ 8 (the pre-filter settles the other 8) | 0 |
| 2f | concurrency on the key, OPT-30 (host) | `python scripts/load_class.py --api <api> --code OLIVE-7Q2 --chapter <id> --students 10 --cloud > scripts/out/load-cloud.txt` | ≈ 5–8 | ≈ 1 |
| 2g | the numbers (host) | `SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/export_stats.py --api <api> --load scripts/out/load-cloud.txt` | 0 | 0 |
| | **Subtotal** | | **≈ 95–100** | **≈ 44** |

**Whole runbook:** about 145–150 requests, about 64 mid. At 20 requests/min that is under 8
minutes of quota. The real limit is mid latency on the CPU platform, so plan about an hour for
steps 2a–2d.

## 3. What to read off, and where it goes

| Number | Source | Goes to |
| --- | --- | --- |
| compact/mid split, calls per pattern | `docs/report/stats-cloud-<date>.md` (step 2g) | REPORT.md §3 `[in-slot]`, PITCH_NUMBERS.md |
| repeated identical requests, cache hits | same | REPORT.md, PITCH_NUMBERS.md (expect 0 repeated) |
| refusals by kind; the status code for "team quota exhausted" if it appears | same, `ai_call_log.status_code` | DECISIONS.md (still unseen), PLATFORM.md |
| first mid pack latency vs the 45 s budget (OPT-13) | `/admin/debug` Live, or the call log for NOTES_WRITE | REPORT.md §9, DECISIONS.md |
| Teach-Back ranking in AR/Darija | `tests/evals/teachback/outputs/cloud-*.json` | REPORT.md testing section |
| verifier: right keys kept / wrong rejected | `tests/evals/quiz/outputs/cloud-keys-*.json` | REPORT.md testing section |
| moderation per language | `audit/artifacts/phase6/adversarial-*moderation*.json` | REPORT.md |

Then run the `prompt-evaluator` agent over `backend/tests/evals/*/outputs/cloud-*` and have a
native speaker read the Darija outputs.

Fill REPORT and pitch numbers **only** from the stats export, never from mock or local runs.

## 4. Stop conditions
- 401 "Key is blocked": the slot is over. Stop and keep what is saved.
- Many 503s on mid: normal on a busy CPU platform (Quick mode). Keep going; note it.
- A quota refusal with a delay: wait it out. That status code is still unrecorded, so note it in
  DECISIONS.md.

## 5. After the slot
- [ ] `python3 scripts/llm.py use mock` (dev) and `docker compose restart backend worker`.
- [ ] Prompt traces off (they turn themselves off after 120 min at most).
- [ ] Rotate `ADMIN_TOKEN` after the demo (DEPLOY.md §6).
- [ ] Tick STATUS.md §2 and commit the stats export, without the key.
