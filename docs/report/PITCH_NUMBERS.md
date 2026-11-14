# Numbers for the pitch (Phase 2)

Every number says where it comes from:
- `mock`: our fake platform (`mock-llm/`), on the audit stack. Good for **behaviour**: limits held,
  faults handled, calls per action. Not for latency or quality on the real CPU models.
- `code`: counted from the code (routing table, one call per step).
- `platform`: our key on the real service. **None exists yet.** The jury slot fills these rows
  (`JURY_SLOT_RUNBOOK.md`, step 2g writes `docs/report/stats-cloud-<date>.md`).

Never present a `mock` number as a platform number. If a juror asks, "measured on our fault-injecting
mock; the platform numbers come from the jury slot" is the honest answer.

## Safe to say now

| Claim | Number | Source |
| --- | --- | --- |
| Concurrency on the key | never more than 2 calls in flight, 30 jobs at once with 503 and quota faults | `mock` (audit §7) |
| Faults handled | 30/30 jobs done; 16 × 503 and 7 quota refusals, all retried or requeued; no error reached a student | `mock` (audit §7) |
| Interactive work first | interactive p50 25.6 s vs background 106.3 s with faults; 9.5 s vs 62.4 s without | `mock` (audit §7; the final re-measure in audit §12 replaces these) |
| Mid busy → still an answer | the forced-503 job always finishes in Quick mode (compact) | `mock` (`scripts/load.py`) |
| One call for a whole quiz | 12 questions in one compact call, checked by one mid call; 10 kept | `code` (`quiz/pool.py`) |
| A class shares its material | study pack 1 mid + 2 compact, then free for every classmate in that language | `code` + `mock` |
| Compact/mid split by design | ≈ 92/8 on a class's first day, ≈ 87/13 steady state (class of 30) | `code` (audit §6, after OPT-09) |
| Indexing cost | ~5 requests for a 30-page PDF (8 chunks per tag call); embeddings on our own `bge-m3` | `code` + `mock` (M2) |
| Worker crash mid pack | job failed cleanly, coins refunded, worker back | `mock` (audit §7) |
| Malicious upload | 1 MB DOCX bomb rejected in < 7 s; a classmate's Tutor start unaffected (4 s) | `mock` (audit §7) |
| Next chapter ready before they get there | prefetch on: chapter 2 opens in 0.0–0.2 s for 0 coins (10 and 30 students), against 6.6–17.6 s and 20 coins off, no more calls (made earlier, while the class works on chapter 1) | `mock` (audit §12 Group E) |
| 30 students polling | 20 req/s, p95 143 ms on the dev server | `mock` (audit §7) |
| Languages | 4 UI languages (EN, FR, AR, Darija), RTL, every key present in all 4 | `code` (`pnpm i18n:check`) |
| Tests | backend, frontend and mock-llm suites, one test per row of the platform's error contract | `code` (counts: REPORT.md §6) |

## Say only after the jury slot

| Claim | Fill from | Runbook step |
| --- | --- | --- |
| Compact/mid split on our key | stats export, "calls per tier" | 2g |
| Repeated identical requests (aim: 0) | stats export, "repeated identical" | 2g |
| Quota refusals and how they were handled | stats export, refusals by kind | 2g |
| First study pack latency on the CPU platform (budget 45 s) | `/admin/debug` Live or the call log | 1c |
| 10 real students at once: waits, fallbacks | `scripts/out/load-cloud.txt` | 2f |
| Teach-Back grading in Arabic and Darija ranks good above weak answers | `tests/evals/teachback/outputs/cloud-*.json` | 2b |
| The answer check keeps right keys and drops wrong ones | `tests/evals/quiz/outputs/cloud-keys-*.json` | 2c |
| Moderation per language | `audit/artifacts/phase6/adversarial-*moderation*.json` | 2e |

## Don't say
- "A study pack costs three requests whatever the class size". This holds one click at a time.
  Ten simultaneous clicks used to cost 7 mid + 12 compact (OPT-01, fixed on
  `fix/opt-audit-prefetch`; re-measured in audit §12).
- "Repeated identical requests cut from 37 to 0". That was one mock setup; a later same-chapter
  run found 19 before the OPT-01 fix.
- Any quality claim ("none of eight attempts…") without saying it was measured on **local**
  substitute models.
