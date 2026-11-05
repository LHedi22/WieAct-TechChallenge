# Requirements map (audit, 3 Nov 2026)

Status: **works** (run and seen in this audit) · **works (code)** (verified in code/tests only) ·
**partial** · **missing** · **docs wrong** · **not tested**. Evidence IDs point to `docs/report/AUDIT.md`.
Sources: Spec = `EdNova_Challenge_Specification.pdf`, Guide = `EdNova_Guide.pdf` (as summarised in
`docs/PLATFORM.md`; the scanned PDFs were not re-read page by page in this audit), then repo docs.

## Challenge rules, deliverables, platform contract
| Requirement | Source | Code | Proof | Status |
| --- | --- | --- | --- | --- |
| Working end-to-end app, no mockups | Spec | whole repo | Phase 2: 16/16 main journeys, 16/16 sweeps (errata 2026-11-05: 16, not 20) | works |
| Key never in code/repo/logs | Spec | `config.py` SecretStr, `.gitignore` | gitleaks full history (119 commits): 0 leaks; bundle scan clean | works |
| Base URL configurable | Spec | `CLOUD_BASE_URL` | constraint-auditor; prodlike points it at the mock | works |
| No streaming; jobs + polling | Guide | `jobs/`, `useJob` | every journey | works |
| Error contract: quota + delay | Guide | `gateway/service.py:237`, worker requeue | contract probe row 1 | works |
| Error contract: 503 → retry or compact | Guide | `service.py:222-236` | contract probe row 2 (quick mode) | works; F-QUICK-1 |
| Error contract: 400 ceiling → fix | Guide | `service.py:239-251` | contract probe row 3 | works |
| Identical request must not regenerate | Guide | `ai_cache`, single-flight | studio second student `cached:true` | **partial** — F-CACHE-1 (DAILY_PLAN) |
| Timeouts handled for interactive | Guide (latency budget) | worker `transient` | contract probe row 6: 5 min wait | partial — F-RES-2 |
| ≤ 2 concurrent, RPM | email | `gateway/limiter.py` | logger max in-flight 2; 20/60 s window | works; F-RPM-1 note |
| Metrics mirrored (calls, split, tokens, repeats, refusals) | Guide | `api/admin.py` | stats read in Phase 5 | works; open without token F-SEC-2 |
| Compact/mid split, patterns named | Guide | `gateway/router.py` | constraint-auditor | works (code); real split in-slot only |
| Multilingual EN/FR/AR/Darija | Spec bonus | i18n 808 keys × 4 | sweeps in 4 languages, RTL | works (Darija text needs native review) |
| No identity data; anonymity | Spec | `models/`, nickname regex | DB columns checked; constraint-auditor | works |
| AI supports, doesn't replace teachers; hints before answers | Spec | quiz reveal rules, tutor guard | arena_quiz_probe (hint → 2nd try → answer) | works (tutor leak not tested on real models) |
| Only synthetic data | Spec | `app/seed` | seed material synthetic | works |
| No replacement API in demo; declared services | Spec | DECISIONS, README | README lists Ollama/Qdrant/Tesseract | works |
| Repo: README, setup, screenshots, GenAI explanation, config template | Spec | README, `.env.example` | screenshots missing (176 now in `audit/artifacts/screenshots`) | partial |
| Report ≤ 6 pages, 8 sections | Spec | `docs/report/REPORT.md` | sections present; [in-slot] gaps; F-DOC-1/2 | partial |
| Video ≤ 1:30 showing waiting/fallback | Spec | `docs/report/VIDEO.md` | F-VID-1 (queue + quick-mode shots not producible as planned) | partial |
| Offline demo mode serves only platform output | PLATFORM/ARCH | `providers.py`, offline checks | prodlike: refuses new AI ✓, serves mock-made quiz set ✗ | partial — F-OFF-1, F-OFF-2 |
| Production guard (cloud only, real secret) | ARCH | `config.py:117-130` | prodlike 8/8 refusals | works |

## Product screens (PRODUCT.md 1–13) and buildings
| Item | Status | Evidence |
| --- | --- | --- |
| Landing + language picker | works | sweeps, journeys |
| Sign up / sign in / sign out / session after reload | works; sign-out doesn't revoke (F-SEC-4) | journeys, prodlike |
| Style test, result, avatar | works (Continue path; Skip/Back/refresh not individually tested) | journeys |
| Create world wizard, uploads, indexing screen | works (API); UI wizard not driven in this audit | upload probe |
| Join by code / invite link | works (`olive 7q2` via UI; `/join/:code` route exists, not clicked) | journeys |
| Empty world / locked island | not tested in browser | — |
| Placement quiz unlocks island | works | journeys |
| Map + list view, zoom | works (both views); 1–8 islands not tested | sweeps |
| Quiz Hall (hint, 2nd try, skip, results) | works | journeys |
| Socratic Tutor | screen works; escalation/3-hint limit not driven in browser | sweeps, contract row 3 |
| Study Studio, Class Pool | works; quick-mode pack stored for class (F-QUICK-1) | contract probe, money probe |
| Audio Studio | screen opens (no-voice path not checked) | sweeps |
| Teach-Back (ask, answer, score, improve, pin, votes, solo) | works (API, 2–3 users) | arena probe |
| Daily return, challenges | screen works; rollover not tested | sweeps |
| Wallet, out-of-coins, demo purchase, Exam Pass | works (API + dialog shows "not enough coins") | money probe, sweep |
| Leaderboards | screen works; opt-out not tested | sweeps |
| Loading screen: stages, queue, ETA, cancel | works (API job view); cancel tested via API | contract probe |
| Class Wisdom tip | not seen in this audit (seed reported 0 tip jobs) | — |

## Economy (ECONOMY.md)
| Rule | Status | Evidence |
| --- | --- | --- |
| 20 free coins/day | works | wallets start at 20 |
| No overspend, ledger == balance, never negative | works | money probe (concurrent) |
| Refund on failure | works | contract rows 401, money probe global check |
| Cached = 0 coins | works | studio second student, quiz `cost 0 cached` |
| Exam Pass 15/day | works (counter) | money probe; 16th activity not driven |
| Peer threshold 70 / +3 coins | works | arena probe (+3 coins, +30 points) |
| Wisdom threshold 3 distinct students | works (code/tests) | not observed live |
| Earn cap 10/day, carry-over, Tunis rollover | not tested | no clock control without code change |
| **Creator reward +5** | **missing** | `economy.py` constant never used |
| UI never hard-codes a price | partial | `en.json:149` "1 and 50 coins" (constraint-auditor S3-4) |

## Routing table (ARCHITECTURE.md)
All rows routed in `gateway/router.py`. Used live in this audit: QUIZ_GENERATE, PLACEMENT_QUIZ, TUTOR_TURN,
NOTES_WRITE/FLASHCARDS/MAP_WRITE, TEACHBACK_GRADE, MODERATE_POST, DAILY_PLAN, CHUNK_TAG, EMBED, JSON_REPAIR.
**Never called:** INTENT_LANG, TRANSLATE_SHORT, CHALLENGE_ITEMS (documented unused), DEMO_SUMMARY (dev).
Docs list INTENT_LANG/TRANSLATE_SHORT as live → **docs wrong**.

## API routes (69) and access control
Every route with an ID checked for non-members (30/30 correct 404) and cross-user objects; failures:
F-ACL-1 (course/chapter/upload/delete by any member), F-ACL-2 (jobs without auth).

## DESIGN.md mockup fixes (14)
Not walked one by one: the `design-reviewer` agent was not run (time and memory). Axe found contrast
issues on 14 screens (F-A11Y-1). Calm-screen rule: building screenshots show no mascot or animated water (visual check of sweep screenshots). **Status: not tested** beyond that.

## Missing or partial features (summary)
Creator reward · badges (chapter mastery, Mentor) · admin "force quick mode" switch · "Notify me" on the
empty world (no string found) · INTENT_LANG / TRANSLATE_SHORT · provider tagging of class tables.
