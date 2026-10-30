# Architecture

## Repo layout
```
learning-world/
├── CLAUDE.md                  # Claude Code entry point (keep short)
├── docs/                      # source of truth for product, platform, design, plan
│   └── reference/             # official PDFs + mockup PDF (read-only)
├── design/
│   ├── mockups/               # PNG export of each mockup screen (01-landing.png …)
│   ├── tokens.json            # colors, type, radii, shadows — mirrored in tailwind config
│   └── assets/                # pixel sprites (islands, buildings, cat, avatars, icons)
├── frontend/                  # React + Vite + TS + Tailwind + Framer Motion + react-i18next
│   └── src/
│       ├── app/               # router, providers, layout shell (top bar, side panel)
│       ├── api/               # typed client generated from FastAPI OpenAPI (openapi-typescript)
│       ├── features/          # onboarding/, worlds/, map/, quiz/, tutor/, studio/, audio/, arena/, challenges/, wallet/
│       ├── components/        # design-system primitives (PixelButton, PixelPanel, SoftCard, Chip, CoinCounter …)
│       ├── hooks/useJob.ts    # polls GET /api/jobs/{id}; exposes stage, queuePosition, quickMode
│       ├── i18n/{en,fr,ar,ar-TN}.json
│       └── styles/
├── backend/                   # FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2, managed by uv
│   └── app/
│       ├── main.py            # app factory, routers, CORS
│       ├── worker.py          # job runner (python -m app.worker)
│       ├── core/              # config.py (pydantic-settings), economy.py, security.py, db.py
│       ├── gateway/           # THE ONLY place that talks to the LLM / embeddings
│       │   ├── client.py      # OpenAI SDK, base_url + key from settings, timeout, no streaming
│       │   ├── router.py      # Task → tier (compact/mid) + pattern name
│       │   ├── limiter.py     # RPM token bucket + concurrency semaphore (2)
│       │   ├── queue.py       # priority lanes: interactive > background
│       │   ├── cache.py       # ai_cache lookup/store
│       │   ├── errors.py      # contract handling: quota / 503 / 400 / network
│       │   ├── quota.py       # parse quota headers → QuotaState
│       │   └── log.py         # ai_call_log writer
│       ├── rag/               # parsing (PyMuPDF, python-pptx, python-docx, Tesseract), chunking, VectorStore (Qdrant)
│       ├── features/          # quiz/, tutor/, studio/, audio/, arena/, challenges/, wisdom/, onboarding/, worlds/
│       ├── prompts/           # *.md templates with {placeholders}; one file per task
│       └── models/            # SQLAlchemy models
│   └── tests/
├── mock-llm/                  # FastAPI fake of the platform (chat, embeddings, models) with fault injection
├── scripts/slot.py            # is our key live now? next slot?
├── docker-compose.yml         # db (postgres), qdrant, mock-llm, backend, worker, frontend
├── .env.example
└── .github/workflows/ci.yml
```

## Request flow for any AI action
```
UI ── POST /api/<feature>/… ──▶ API: validate, check & reserve coins, create Job(status=queued)
                                 │      returns {job_id, cost, cached:bool}
UI ◀── poll GET /api/jobs/{id} ──┤  {status, stage, stages[], queue_position, eta_s, quick_mode, result}
                                 ▼
                   Worker picks job by lane priority (interactive first, not_before respected)
                                 ▼
          feature handler → gateway.run(Task) → cache? → limiter → client → errors → log
                                 ▼
          result stored on job (+ shared tables: quiz_sets, study_assets, wisdom_tips …)
          coins: reservation committed on success, refunded on failure
```
- Postgres-backed queue: `SELECT … FOR UPDATE SKIP LOCKED`. No Redis, no Celery.
- Job stages are human-readable keys (`reading_chapter`, `matching_level`, `writing_questions`,
  `writing_hints`) so the loading screen shows real progress from the backend.
- If the answer is already cached, the API returns the result directly with `cached=true` and
  charges 0 coins.

## The gateway contract
```python
class Task(BaseModel):
    kind: TaskKind            # e.g. QUIZ_GENERATE, MISTAKE_TAG, TUTOR_TURN, NOTES_WRITE …
    lane: Literal["interactive", "background"]
    messages: list[dict]
    language: str
    cache_key: str | None      # None = never cache (e.g. tutor turns)
    response_format: Literal["json", "text"] = "json"
    max_tokens: int
    allow_fallback: bool = True

class Result(BaseModel):
    content: str | dict
    model_tier: Literal["compact", "mid"]
    pattern: str               # escalation / draft-then-revise / plan-once / narrow-before-generating / triage / fallback
    quick_mode: bool           # fell back from mid → compact
    cached: bool
    tokens_in: int; tokens_out: int; latency_ms: int
```
`router.py` holds the single table mapping `TaskKind` → default tier + pattern (below). Features
never pick a model name.

Thinking models: when `LLM_DISABLE_THINKING=true` the client adds
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (drop it if the server answers 400)
and always strips `<think>…</think>` before parsing. Per-task `max_tokens` budgets: docs/MODELS.md.

JSON outputs: request `response_format={"type":"json_object"}` only if `/v1/models` or a test call
shows support; otherwise prompt for JSON, parse with a tolerant extractor, validate with Pydantic,
and on failure do ONE compact "fix this JSON" repair call. Small models break JSON — test it.

## Model routing table
| TaskKind | Tier | Pattern | Lane | Cache key |
| --- | --- | --- | --- | --- |
| INTENT_LANG (detect intent + language) | compact | triage | interactive | text hash |
| CHUNK_TAG (batch of chunks → concepts, chapter) | compact | batch at upload (burst) | background | doc hash |
| QUIZ_GENERATE (10 Q, one call) | compact | narrow-before-generating | interactive / background pool | world+chapter+level+lang+seed |
| QUIZ_GRADE_TAG (wrong answers → concept + mistake type) | compact | extraction | background | lang + missed items hash |
| TUTOR_TURN | compact → mid when stuck ≥ 2 turns or "complex" flag | escalation | interactive | plan: chapter+level+lang+style; turns: none |
| TUTOR_GUARD (rewrite a reply that leaks the answer as a guiding question; only flagged replies) | compact | guard | interactive | none |
| TUTOR_SUMMARY | compact | summary | interactive | session id |
| NOTES_WRITE (STUDY_PACK job, step 1) | mid | plan-once + narrow-before-generating (quiz-pool narrowing, no filter call) | interactive | chapter+level+lang (+job; `study_assets` is the class cache) |
| FLASHCARDS / MAP_WRITE (STUDY_PACK steps 2–3, from the notes only) | compact | execute-compact | interactive | chapter+level+lang (+job) |
| AUDIO_SCRIPT (AUDIO_EPISODE job) | mid | narrow-before-generating, once then cached | interactive | chapter+level+lang (+job; `study_assets` is the class cache) |
| DAILY_PLAN (first `GET /api/daily` of a Tunis day; an instant rule plan shows meanwhile and stays if the job fails; applied only while nothing is done) | mid, once / student / day | plan-once | background | user+date |
| CHALLENGE_ITEMS (unused: flashcard challenges review existing cards) | compact | execute-compact | background | user+date |
| WISDOM_TIP (at `WISDOM_THRESHOLD` distinct students per world+concept+mistake type; ONE call writes the tip in every language of the world's members; later students only raise the count) | mid, once per pattern | generate-once | background | world+concept+type+langs+count |
| TEACHBACK_GRADE (ARENA_GRADE / ARENA_SOLO jobs; the same call moderates the answer via `flag`) | compact draft; mid reviews only when confidence is low or the score is within `TEACHBACK_REVIEW_BAND` of `PEER_ANSWER_THRESHOLD` (solo: low confidence only); mid busy → the draft stands (Quick mode) | draft-then-revise | interactive | none (personal) |
| MODERATE_POST (ARENA_ASK job: peer questions; rejected → coins refunded) | compact | classification | interactive | text hash |
| TRANSLATE_SHORT | compact | rewriting | background | text+lang |
| PLACEMENT_QUIZ (8 Q per course, 2 chunks per chapter, one call; graded server-side) | compact | narrow-before-generating | interactive | course+lang (shared by the class) |
| any mid task when saturated | compact | fallback (`quick_mode`) | — | — |
| JSON_REPAIR (internal: fix one broken JSON reply) | compact | repair | same as the task | none |
| DEMO_SUMMARY (dev-only M1 demo job) | mid | narrow-before-generating | interactive / background | optional |
| EMBED (embeddings endpoint, own quota; logged as tier `embed`) | — | batch (32 texts/call) | background (upload) / interactive (search query) | search query text |

Identical cacheable tasks in flight at the same time are single-flighted: one model call, the
others read the cache when it lands.

## RAG
- Parse → normalise text per page/slide → chunk (~500 tokens ≈ 2,000 characters, 240 characters
  of overlap, never across a page/slide, so each chunk keeps one ref: `page:12`, `slide:18`,
  `section:3`, `part:2`, `image:1`). PDF pages with < 25 characters of text and image files go
  through Tesseract (`ara+fra+eng`).
- `INDEX_DOCUMENT` job (background): parse → CHUNK_TAG (8 chunks per compact call, cached by file
  hash) → EMBED (32 per call) → Qdrant; ~5 calls for a 30-page PDF. Resumable after a Defer; the
  same file twice in a chapter is indexed once. `documents.progress/detail` drive the indexing screen.
- Embeddings via the platform endpoint (own quota) through the gateway, batched.
- `VectorStore` interface: `upsert(chunks)`, `search(query_vec, filters={world_id, course_id, chapter_id}, k)`,
  `delete(document_id)`. Implementation: **`QdrantVectorStore`** with `qdrant-client` (async).
  One collection per provider (`{QDRANT_COLLECTION_PREFIX}-{provider}-{embedding model slug}`, see
  §Providers), vector size = that profile's `*_EMBEDDING_DIM`, cosine distance.
  Point id = chunk UUID (same as Postgres `chunks.id`); payload = `{world_id, course_id, chapter_id,
  document_id, page_ref, tags, lang}` with keyword payload indexes on the filter fields.
  Text lives in Postgres; Qdrant holds vectors + payload only (keeps the collection small).
- Tests use an in-memory Qdrant (`QdrantClient(":memory:")`) — no network.
- narrow-before-generating: top-k=8 by vector → compact filter keeps the 3–4 most relevant → prompt.
- Precompute right after upload (background lane, burst reserve): chunk tags, quiz pool per level,
  notes for "intermediate" in the creator's language. M2 ships the quiz pool: when a chapter's
  last file is ready, `QUIZ_POOL` makes ONE compact QUIZ_GENERATE call (10 questions) from up to 8
  chunks picked round-robin across the chapter's concepts → `quiz_sets`.
- `python -m app.rag.reindex --provider cloud` rebuilds a provider's collection from Postgres.

## Data model (Postgres)
`users(id, nickname, password_hash, ui_language, created_at)` — nothing else identifying
`profiles(user_id, university, field, year, style_visual, style_practice, style_listening, style_teaching, languages[], daily_minutes, reminder_time, leaderboard_opt_in)`
`worlds(id, name, join_code, creator_id)` · `world_members(world_id, user_id, joined_at)`
`courses(id, world_id, name, color_key, exam_date)` · `chapters(id, course_id, idx, title)`
`documents(id, chapter_id, filename, kind, size, status, error)` · `chunks(id, document_id, chapter_id, text, page_ref, tags[], lang)` — vectors in Qdrant
`course_levels(user_id, course_id, level, placed_at, goal)` · `chapter_mastery(user_id, chapter_id, mastery, weak)`
`placement_sets(id, course_id, language, questions jsonb)` — answers never leave the server · `presence(user_id, course_id, chapter_id, seen_at)` — "on this island now", 2-minute window
`jobs(id, user_id, world_id, kind, lane, status, stage, stages, not_before, attempts, cost, result jsonb, error, quick_mode, created_at, finished_at)`
`ai_cache(key PK, task_kind, content jsonb, model_tier, created_at, hits)`
`ai_call_log(id, ts, task_kind, model_tier, pattern, status_code, tokens_in, tokens_out, latency_ms, cache_hit, fallback, refusal_reason)`
`quiz_sets(id, world_id, course_id, chapter_id, level, language, seed, questions jsonb)` · `quiz_attempts(id, user_id, quiz_set_id, world_id, course_id, chapter_id, level, language, answers jsonb, current, score, points, second_tries, status, finished_at)`
`mistakes(id, user_id, world_id, chapter_id, attempt_id, question_idx, concept, mistake_type, created_at)`
`wisdom_tips(id, world_id, course_id, chapter_id, concept, mistake_type, language, text jsonb{trap,why,right}, student_count)` — unique (world, concept, mistake_type, language); `mistakes.concept` is the shared quiz question's concept so classmates' mistakes match
`study_assets(id, world_id, chapter_id, level, language, kind[notes|map|audio_script], content jsonb)` — unique (chapter, level, language, kind)
`flashcards(id, chapter_id, asset_id, user_id, front, back, concept, source[deck|quiz], ref)` — deck cards are shared (user NULL, asset = the pack's notes), quiz cards personal
`flashcard_reviews(user_id, card_id, due_at, interval_s, ease, reps, updated_at)`
`tutor_sessions(id, user_id, world_id, course_id, chapter_id, level, language, goal, ideas jsonb, hints_used, stuck_count, escalate_next, turns jsonb, pending_job_id, status, summary jsonb, ended_at)`
`peer_questions(id, world_id, chapter_id, author_id, text, language, status[pending|open|rejected], reject_reason, pinned_answer_id)` · `peer_answers(id, question_id, author_id, text, status[grading|graded|rejected|failed], ai_score, ai_confidence, ai_feedback jsonb, reviewed_by_mid, rewarded)` — one per student per question · `peer_votes(answer_id, user_id)`
`coin_ledger(id, user_id, day, bucket[free|earned|purchased|pass], kind[daily|earned|purchased|spend|refund|pass], delta, ref, created_at)` — `day` = Tunis day; one `daily` row per user-day, one refund per (ref, bucket) · `points_ledger(id, user_id, world_id, delta, reason, ref, created_at)` — unique (user, reason, ref)
`daily_state(user_id, date, challenges jsonb, plan jsonb, planned_by[rule|ai], plan_job_id, seen_at)` — 3 challenges `{type[quiz_questions|quiz_score|teachback|tutor_session|flashcards], target, progress, done, why, world/course/chapter}`; free coins, earned-today and streak are derived from the ledgers
`class_pool_ledger(id, world_id, user_id, kind[contribute|spend|refund], delta, ref)` — balance = sum; one refund per ref · `cosmetics_owned(user_id, item_key)`

Balances are derived from ledgers (with a cached balance column if needed). Every coin change is
a ledger row — never mutate a balance without one.

## API surface (REST, JSON, cookie session)
`/api/auth/{signup,login,logout,me,session}` (signed HttpOnly cookie) · `/api/profile` · `/api/onboarding/style`
`/api/worlds/{id}/map` · `/api/courses/{id}` (island) · `/api/courses/{id}/presence` · `/api/placement/{course_id}`
`/api/worlds` (create) · `/api/worlds/join` · `/api/worlds/{id}` (map data) · `/api/worlds/{id}/courses|chapters|documents`
`/api/jobs/{id}` · `/api/economy` · `/api/wallet` (+ `/demo-purchase`) · `/api/daily` (+ `/seen`: the daily return screen, shown to returning students on their first open of the day) — any paid start without enough coins → `402 errors.insufficient_coins`
`/api/quiz/price` · `/api/quiz/start` · `/api/quiz/attempts/{id}` (+ `/answer`, `/skip`, `/finish`; `/api/quiz/attempts/from-job/{job}`) · `/api/placement/{start,finish}` · `/api/tutor/start` · `/api/tutor/{id}` (+ `/turn` with action message|hint|another_way|stuck, `/end`)
`/api/studio/{chapter}?level` (notes, map, card counts, missing parts, pending job, price, pool balance) · `/api/studio/{chapter}/price` · `/api/studio/{chapter}/generate {level, pay: me|pool}` · `/api/studio/{chapter}/cards?level` (due queue) · `/api/studio/cards/{id}/review {grade}` · `/api/quiz/attempts/{id}/flashcards` · `/api/worlds/{id}/pool` (GET/POST) · `/api/audio/{chapter}?level` (script, pending job, price, pool) · `/api/audio/{chapter}/price` · `/api/audio/{chapter}/generate {level, pay}`
`/api/arena/questions?chapter_id` (feed, polled) · `/api/arena/questions/{id}` (+ `/answers`) · `/api/arena/answers/{id}/pin` · `/api/arena/answers/{id}/helpful` (POST/DELETE) · `/api/arena/solo`
`/api/leaderboard?scope=world|global&period=week|all&world_id` · `/api/wisdom?world_id&course_id` (tips in the user's language, English fallback)
`/api/admin/stats` (call log aggregates; dev/demo only) · `/api/system/status` (slot live? offline demo mode?)

## Config (.env)
See `.env.example`. Backend reads via `pydantic-settings`; frontend only gets `VITE_API_URL`.

## Providers (local / cloud / mock)
- **Resolution:** `LLM_PROVIDER=local|cloud|mock|auto` selects one of the `CLOUD_*`, `LOCAL_*`, `MOCK_*`
  profiles (base URL, key, compact/mid/embedding model, embedding dim). `config.py` resolves them into a
  single `settings.llm`; nothing else reads the profile variables. Switch with `python scripts/llm.py use …`.
- **auto:** cloud when our slot is live (`app/core/slot.py`) and no 401 "Key is blocked" has been seen
  since the slot started; otherwise local. Evaluated per job, so slot boundaries need no restart.
- **Production guard:** `APP_ENV=production` allows only cloud and refuses to start with local or mock.
  Outside the slot or on 401 → Offline demo mode serving cached cloud results only.
- **Kept apart:** Qdrant collection `{prefix}-{provider}-{embedding model slug}` with that provider's dim
  (`python -m app.rag.reindex --provider cloud` rebuilds it); `ai_cache` keys and `ai_call_log` rows
  include provider and model; `/api/admin/stats` defaults to `provider=cloud`.
- Same limiter (2 concurrent, `LLM_MAX_RPM`) for every provider. Local = Ollama on the host
  (`host.docker.internal:11434/v1` from compose), dev only — see DECISIONS.md.

## Testing
- Gateway: unit tests against `mock-llm` fault modes (503+Retry-After, quota, 400 ceiling, slow,
  malformed JSON) — these are the resilience evidence for the report.
- Economy: pure-function tests for allowance, daily cap, refund on failure, purchase never expires.
- Load test: `scripts/load.py` simulates 10 students at once against mock (and once against the
  real platform in-slot) — record p50/p95 wait, fallback count, cache hit rate.
- Frontend: Vitest + Testing Library for components; Playwright smoke for landing → first quiz.
