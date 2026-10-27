# Claude Code prompts, one per phase (solo)

Paste one prompt per session, in order. Each prompt starts in plan mode and ends with `/verify`.
Work on one branch per milestone (`m0-foundations`, `m1-gateway`, …) and merge when `/verify` passes.

**Solo timeline** (planned for three people, now one person: the scope guard applies from M5 on)

| Dates | Phase | In-slot work (Group A, Tunis time) |
| --- | --- | --- |
| Tue 27 eve – Wed 28 | M0 Foundations | **Wed 28, 12:00–24:00**: probe the models (prompt S1) |
| Wed 28 – Fri 30 | M1 Gateway + providers | **Thu 29, 00:00–12:00**: real smoke test of the gateway |
| Fri 30 – Sat 31 | M2 Upload & indexing | **Fri 30, 12:00–24:00**: index the seed world on cloud + quiz eval (S2) |
| Sun 1 – Mon 2 | M3 Onboarding + map | **Mon 2, 00:00–12:00**: (optional) placement-quiz eval |
| Mon 2 – Wed 4 | M4 Quiz Hall + Socratic Tutor | **Tue 3, 12:00–24:00**: prompt evals in 3 languages (S2) |
| Wed 4 – Thu 5 | M5 Economy + Teach-Back | **Thu 5, 12:00–24:00**: load test + first user test (S3) |
| Fri 6 – Sat 7 | M6 Challenges + Class Wisdom | **Fri 6, 00:00–12:00**: generate wisdom tips + daily plans on cloud |
| Sat 7 | M7 Study Studio (Audio cut) | — |
| Sun 8 – Mon 9 | M8 Ship | **Mon 9, 12:00–24:00**: user test with ~10 students, record the demo, export stats (S3/S4) |
| Tue 10 | Submit by 12:00 | **Tue 10, 00:00–12:00**: last fixes only |

Weekend slots are unconfirmed. Treat Saturday and Sunday as local-models-only days.

---

## Every session: start
```
Read CLAUDE.md. Run /slot and `python scripts/llm.py status` (if it exists yet).
Read docs/BUILD_PLAN.md and tell me in 5 lines: which milestone we're on, what's ticked, what's
left, and which OPEN items in docs/DECISIONS.md block today's work. Don't start coding yet.
```

## Every milestone: close
```
Run /verify. Then ask the constraint-auditor agent to review the backend changes on this branch
and the design-reviewer agent to review the frontend changes (skip whichever has no changes). Fix
every blocker and should-fix item, re-run /verify, tick the boxes in docs/BUILD_PLAN.md that are
truly done, add any decisions to docs/DECISIONS.md, and commit. Then give me a 5-line summary
plus the 3 strongest points this milestone gives the technical report.
```

---

## M0 · Foundations
```
/milestone M0

Build M0 from docs/BUILD_PLAN.md for both backend and frontend, as one person, in this order:

BACKEND
1. backend/ as a uv project (Python 3.12): FastAPI app factory, /api/health, pydantic-settings
   config that resolves settings.llm from LLM_PROVIDER + CLOUD_/LOCAL_/MOCK_ profiles exactly as
   .env.example defines them (no other module reads those variables), async SQLAlchemy 2 + asyncpg,
   Alembic with an initial migration for users, worlds, world_members, jobs, ai_cache, ai_call_log
   (ai_cache and ai_call_log include provider and model columns).
2. In production, the app refuses to start unless LLM_PROVIDER is cloud. Test this.
3. Dockerfile for backend; docker-compose services db, qdrant, mock-llm (Dockerfile stub only;
   the mock itself is M1), backend, worker.
4. ruff + pytest configured; one test for settings resolution per provider.

FRONTEND
5. frontend/ with Vite + React + TypeScript strict + Tailwind (theme generated from
   design/tokens.json, including the AA-safe *-ink shades), Google Fonts (Baloo Bhaijaan 2, IBM
   Plex Sans Arabic), react-i18next with en, fr, ar, ar-TN (RTL for ar and ar-TN, dir/lang on
   <html>), React Router, TanStack Query, Zustand for UI state, Vitest, ESLint, `pnpm i18n:check`.
6. A /styleguide route that reproduces design/mockups/18-style-guide.png and
   19-style-guide-world-pieces.png with real components: PixelButton (4 variants + pressed/focus/
   disabled), PixelPanel, SoftCard, Banner (queue, offline, quick mode, placement), Chip, coin/
   points/streak/refill counters, ProgressBar, SegmentedProgress, MasteryRing, Input (default/
   focus/error), LoadingStages, Mascot placeholder, Bidi, and a Sprite component that takes
   placeholder sprites so real pixel art can be dropped in later. Follow the ui-screen skill.
7. A language switcher on /styleguide to check EN and AR side by side.

Done when: the M0 "Done when" line in BUILD_PLAN passes from a fresh clone on Windows.
Plan first; keep commits small.
```

## M1 · Mock LLM, AI gateway, jobs, providers
```
/milestone M1

Build M1 from docs/BUILD_PLAN.md, including the "Provider switching" block. Follow the ai-feature
skill and docs/PLATFORM.md exactly. Write the tests first for every row of the error contract.

1. mock-llm/ as specified in mock-llm/README.md: models, chat, embeddings (dim = MOCK embedding
   dim), latency per tier, token bucket, max 2 concurrent, 503 + Retry-After, quota exhaustion
   (configurable status), 400 ceiling, bad JSON, MOCK_BLOCKED / X-Mock-Fault: blocked → 401
   "Key is blocked", schema-valid fixtures per TaskKind in en/fr/ar.
2. backend/app/gateway/: Task/Result models, router table (TaskKind → tier + official pattern
   name), ai_cache (key includes provider + model + prompt version), global limiter (2 concurrent,
   LLM_MAX_RPM, same for every provider), priority lanes, error contract (quota delay → requeue;
   503 → one retry then compact fallback with quick_mode; 400 → shrink once; 401 Key is blocked →
   offline: no retry, refund, park background jobs until next slot), Qwen3 thinking off
   (/no_think + chat_template_kwargs for cloud, dropped on 400; always strip <think>), tolerant JSON
   extraction + one compact repair call, quota header parsing, ai_call_log.
3. app/core/slot.py (move the logic from scripts/slot.py, which then imports it) and provider
   resolution: auto = cloud when the slot is live and no 401 has been seen since the slot started,
   else local; evaluated per job.
4. Jobs: Postgres queue (SELECT … FOR UPDATE SKIP LOCKED), single worker process, stages,
   not_before, queue position + ETA, coin reserve/commit/refund hooks (stub economy for now),
   GET /api/jobs/{id}, GET /api/system/status (provider, live, offline demo mode).
5. /api/admin/stats (default provider=cloud): calls per tier, split %, tokens in/out, cache hits,
   refusals, fallbacks, p50/p95 latency.
6. scripts/llm.py (use/status/check, Windows-safe, never touches the key value),
   scripts/setup_ollama.ps1 and .sh, scripts/load.py (N simulated students, fault flags).
7. Frontend: useJob hook + LoadingStages + queue / quick-mode / offline banners wired to a demo
   job on /styleguide, plus a dev-only Local/Cloud/Mock badge.

Check against local Ollama too: `python scripts/llm.py use local`, `check`, then run one demo job
end to end with qwen3:1.7b and show me the stats page numbers.
Done when: the M1 "Done when" line passes (30 jobs under faults, ≤ 2 concurrent, fallbacks
visible, queue position shown) and `llm.py use auto` switches at slot boundaries without a
restart (tested with MOCK_BLOCKED).
```

## M2 · Upload & indexing (Qdrant)
```
/milestone M2

Build M2 from docs/BUILD_PLAN.md.
1. Parsers in backend/app/rag: PDF (PyMuPDF), PPTX (python-pptx), DOCX (python-docx), TXT,
   images and scanned PDF pages via Tesseract (ara+fra+eng; skip OCR gracefully if Tesseract is
   missing and log it). Normalise text, keep page/slide refs, detect language per chunk.
2. Chunking (~500 tokens, 60 overlap) → Postgres chunks table; batched CHUNK_TAG on the compact
   model (background lane, many chunks per call); batched embeddings through the gateway.
3. QdrantVectorStore (qdrant-client async): collection {prefix}-{provider}-{embedding slug} with
   that provider's dim, cosine, keyword payload indexes on world_id, course_id, chapter_id,
   document_id; idempotent upsert by chunk UUID; delete by document; search with filters.
   Tests use QdrantClient(":memory:"). Add `python -m app.rag.reindex --provider cloud`.
4. narrow-before-generating helper: vector top-8 → compact filter keeps 3–4 → returns context
   with refs. Used by every content feature later.
5. API + UI: create-world wizard (name → courses → chapters → upload per chapter, 50 MB limit,
   file list with per-file status), join by code (format like OLIVE-7Q2) and invite link,
   staged indexing screen with real per-document progress and the class code card
   (design/mockups/04-create-join-upload.png and 05-indexing-invite.png, with the DESIGN.md fixes).
6. Background precompute after upload: one quiz pool per chapter at intermediate level in the
   creator's language.
7. scripts/seed.py: a demo world "Engineering 2B" with 2 courses from openly licensed material
   (Calculus I: limits, derivatives; Data Structures: stacks and queues). Put the source PDFs in
   seed/ with their licence noted in seed/SOURCES.md. Keep the number of courses consistent with
   the map (mockup fix 10).

Test on local models (bge-m3 → 1024 dims). Done when: the M2 "Done when" line passes on local,
and the same search works after `reindex --provider mock`.
```

## M3 · Onboarding + world map
```
/milestone M3

Build M3 from docs/BUILD_PLAN.md following the ui-screen skill, docs/PRODUCT.md (screens 1–8,
12–13) and docs/DESIGN.md (all Mockup fixes apply).
1. Auth: nickname + password (argon2), cookie session. No email, no real name, no Google.
2. Landing (01-landing.png) with the language picker; sign-up form; style test with progress bar
   (02-style-test.png): profile, 4–6 scenario cards, goals, study time, languages, leaderboard
   opt-in, "Skip for now"; result card with style percentages + avatar builder (03-result-
   avatar.png); locked extras show point prices.
3. World map (06-world-map.png): pixel scene from a layout JSON (1–8 islands, labels in reserved
   slots that never overlap sprites in LTR or RTL), animated water that stops under reduced
   motion, mastery rings, top bar (coins/points/streak/refill from the API), side panel with
   challenges + class leaderboard placeholders, Map/List toggle, zoom, short sail animation then
   open island. RTL version must match 09-world-map-ar-rtl.png minus its label bugs.
4. Island view (07-island-placement.png): 5 buildings with live costs from /api/economy ("Free"
   when cached), chapters with mastery and weak-spot chips, "on this island now" (polling),
   placement banner. Copy says "Click a building to enter".
5. Building entry dialog (08-quiz-entry.png): chapter + level + cost + balance after.
6. Placement quiz: 8 questions, free, compact model, sets course level; locked island state.
7. Empty-world screen (10-empty-world.png) and the list view of the whole map (keyboard).
8. A Playwright smoke test: landing → sign up → style test → join seeded world → placement →
   island, in EN and AR, under 5 minutes of real time on local models.

Placeholder sprites are fine. Done when: the M3 "Done when" line passes.
```

## M4 · Quiz Hall + Socratic Tutor
```
/milestone M4

Build M4 from docs/BUILD_PLAN.md with the ai-feature skill for every TaskKind.
QUIZ HALL
1. QUIZ_GENERATE: 10 questions in ONE compact call from narrow-before-generating context, at
   the chosen level and language; strict JSON (q, 4 options, answer_index, hint, explanation,
   concept); validate, repair once, and if the max-tokens ceiling is too low, split into 2 × 5.
   Cache per world+chapter+level+language+prompt version; serve from the pool when present.
2. Screens (12-quiz-question-hint.png, 13-quiz-results-offline.png): one question per screen,
   KaTeX math, wrong → feedback + hint + second try (half points) → explanation; save and exit;
   results with score, each mistake explained, points (quizzes earn points, not coins), ONE next
   step deep link, "Turn these into flashcards". Loading screen 11-loading-queue-wisdom.png with
   real stages, queue position, "Cancel and keep my coins".
3. QUIZ_GRADE_TAG in background: each wrong answer → (concept, mistake_type) → mistakes table,
   chapter_mastery and weak spots.
SOCRATIC TUTOR
4. TUTOR_TURN on compact with a guard step that rewrites any reply that states the final answer;
   escalation to mid after 2 "I'm stuck" signals or a complex flag; hint counter (max 3), "Ideas
   you've found", buttons Give me a hint / Explain it another way / I'm stuck; language follows
   the student; low confidence → suggest asking the teacher. TUTOR_SUMMARY at the end.
   Screen 14-socratic-tutor.png ("Show me the graph" only if a function plot is easy, else drop it).
5. Prompts in backend/app/prompts/*.md with version headers; system prompts in a neutral tone that
   doesn't change with language or level (no discrimination rule).
6. Evals: backend/tests/evals/quiz_generate and tutor_turn with 5 inputs each in en, fr, ar
   (+2 Darija). `uv run python -m app.evals <task> --provider local` writes outputs; run it now on
   local and ask the prompt-evaluator agent to grade them; apply its prompt fixes.

Done when: the M4 "Done when" line passes on local, and on mock with 503/quota faults on.
```

## M5 · Economy, leaderboards, Teach-Back Arena
```
/milestone M5

Build M5 from docs/BUILD_PLAN.md. Numbers only from docs/ECONOMY.md via backend/app/core/
economy.py and GET /api/economy.
1. Wallet: coin_ledger with free/earned/purchased buckets, 20 free per day refilled at Tunis
   midnight (no carry-over), earned cap 10/day, spend order free→earned→purchased, reserve on job
   create, commit on success, refund on failure/cancel, cached results cost 0, Exam Pass = 15 AI
   activities/day, clearly labelled demo purchase, Class Pool transfers, creator reward. Pure-
   function tests for every rule first.
2. Points ledger, streaks (Tunis days), badges (chapter mastery, Mentor), class and global
   leaderboards weekly/all-time with opt-out. Out-of-coins screen (17-out-of-coins.png) with the
   DESIGN.md copy fixes (no "unlimited", correct rewards).
3. Teach-Back peer room (15-teachback-peer-room.png): questions per chapter (2 coins, MODERATE_POST
   on compact before publishing), answers, TEACHBACK_GRADE draft-then-revise (compact scores;
   mid reviews low-confidence or top answers), score/confidence/errors/"Good:" line, reward only
   above the threshold (3 coins + 30 points), pinned best answer, helpful votes, "Improve my
   answer", polling every 5 s, "ask the AI" after 10 min with no answer.
4. Solo mode: explain a concept → score, confidence, mistakes, what was missing (mid, 8 coins).

Scope guard check: if M5 runs past Thu 5 evening, drop the global leaderboard and Class Pool and
note it in DECISIONS.md. Done when: the M5 "Done when" line passes with two browsers.
```

## M6 · Daily challenges + Class Wisdom
```
/milestone M6

Build M6 from docs/BUILD_PLAN.md.
1. DAILY_PLAN: one mid call per student per day at first login (weak spots, style, goals, exam
   dates) → 3 challenges saved in daily_state; CHALLENGE_ITEMS on compact only when a challenge
   needs generated items. Progress tracked from real events (quiz answers, flashcard reviews,
   Teach-Back answers). All 3 → bonus. Rewards: 3 coins each (counts toward the cap) + points.
2. Daily return screen (refilled coins, streak, 3 challenges → map) and the map side panel
   wired to real data. In-app reminder at the chosen time.
3. Class Wisdom: count distinct students per (world, concept, mistake_type); at threshold 3,
   WISDOM_TIP on mid (trap, why it's wrong, correct reasoning; no names) in the world's
   languages; cached; shown on loading screens ("Show me another tip") and in Quiz Hall.
4. scripts/seed.py gains 3 synthetic students who make the same mistake, so the demo always has
   a tip ready.

Done when: the M6 "Done when" line passes on local.
```

## M7 · Study Studio (Audio Studio only if there's time)
```
/milestone M7

Build Study Studio from docs/BUILD_PLAN.md M7 (16-study-studio-flashcards.png):
1. NOTES_WRITE on mid (once per world+chapter+level+language, then free for the class; 15 coins
   or Class Pool for a new one), rendered with headings and KaTeX.
2. FLASHCARDS on compact from the notes; spaced repetition (Again <1 min, Good 10 min, Easy 3 days,
   keyboard 1/2/3 and Space); "Turn these into flashcards" from quiz results adds cards.
3. MAP_WRITE on mid → JSON tree → SVG mind map (cut first if time is short).
Only if all of that passes /verify before Sat 7 evening: Audio Studio with AUDIO_SCRIPT on mid +
Web Speech API player (transcript, speed). Otherwise mark Audio Studio as cut in DECISIONS.md and
hide its building behind a "coming soon" state.
```

## M8 · Ship
```
/milestone M8

Prepare the submission. Deadline: Tue 10 Nov; demo recorded by Mon 9.
1. Offline demo mode end to end: /api/system/status drives a banner; new AI actions disabled with
   a clear message; only cloud-generated cache served; nothing can be earned or spent.
2. Deploy: frontend on Vercel, backend + worker + Postgres on Render or Railway, Qdrant hosted
   (or the platform's if reachable). APP_ENV=production, LLM_PROVIDER=cloud, secrets only in the
   host's env settings. Seed the demo world, reindex on cloud during a slot.
3. README: what it does, setup (Windows + Linux), architecture diagram, "GenAI module" section
   (routing table, patterns, constraint handling, provider switching and why local is dev-only),
   declared services, privacy, screenshots from design/screenshots/ (take them with a browser
   tool at 1440×900 in EN and AR).
4. docs/REPORT_DRAFT.md (≤ 6 pages when exported): objective, architecture, models/API, RAG,
   privacy & ethics, testing strategy & results (evals, load test, user test numbers from
   /api/admin/stats provider=cloud), limited-capacity handling, business-model note (target users,
   value proposition, adoption path, sustainability, prices from ECONOMY.md).
5. docs/DEMO_SCRIPT.md: a 90-second shot list that shows the shared world, a quiz with a hint, the
   queue/quick-mode fallback with a Class Wisdom tip, the Teach-Back peer room, Arabic RTL, and the
   stats split. Mark which shots need the live slot.
6. Admin-only demo switch (not in production UI): a "force quick mode" toggle on /admin that makes the gateway answer the next mid-size task with the compact fallback path, so the fallback can be shown on camera without editing code. Logged in ai_call_log as forced.
7. Final /verify, the constraint-auditor on the whole repo, a gitleaks scan of the full history,
   and a check that no .env, key or platform URL appears in code, logs, screenshots or the video.
```

---

## In-slot prompts

### S1 · First slot: probe the models (Wed 28, from 12:00)
```
We are in our slot. Run /slot. Then `python scripts/llm.py use cloud` and `python scripts/llm.py
check`. If check passes, run `python scripts/probe_models.py --provider cloud` (I've put the key in
.env; don't open it). Read the results in docs/MODELS.md, tell me the picks and why, list the
CLOUD_* lines I should paste into .env, and close the matching OPEN items in docs/DECISIONS.md
(model names, quota headers, JSON mode, max-tokens ceiling, our group). If the cloud embedding dim
differs from local, note that the cloud Qdrant collection needs `reindex --provider cloud`.
Finally `python scripts/llm.py use auto`.
```

### S2 · Eval slot (prompt quality on the real models)
```
We are in our slot. `python scripts/llm.py use cloud`, then run the evals for every TaskKind built
so far: `uv run python -m app.evals all --provider cloud`. Ask the prompt-evaluator agent to grade
the outputs, compare with the latest local results, and propose prompt changes where cloud is
worse. Apply them, re-run only the failing tasks, and save the before/after scores in
docs/REPORT_DRAFT.md "Testing". Keep total calls under 120 and watch /api/admin/stats for refusals.
Switch back with `llm.py use auto` before the slot ends.
```

### S3 · Load test + user test slot
```
We are in our slot. `python scripts/llm.py use cloud`. First a 3-minute dry run:
`python scripts/load.py --students 10 --minutes 3`. Report p50/p95 wait, fallbacks, cache hit rate,
refusals and max concurrency from /api/admin/stats (provider=cloud). If anything surfaces a raw
error to the client or exceeds 2 concurrent, stop and fix it before real students arrive. Then
prepare the user test: create one world per test group, print the class codes, and open
/admin/stats on a second screen. After the test, export the stats and the anonymous feedback
into docs/REPORT_DRAFT.md "User testing".
```

### S4 · Demo recording slot (Mon 9, 12:00–24:00)
```
We are in our slot and recording the demo. `python scripts/llm.py use cloud`, then walk through
docs/DEMO_SCRIPT.md shot by shot on the deployed site. Before each shot that needs AI, warm the
cache or confirm the job runs in under 20 s. Force one quick-mode fallback for the fallback shot
(use the admin "force quick mode" toggle from M8, never edit code).
Check every frame for the key, the .env file or the platform URL in the address bar or dev tools.
After recording, reset any admin setting you changed.
```
