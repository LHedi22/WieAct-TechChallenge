# LLM platform — constraints and error contract

Sources: `docs/reference/EdNova_Challenge_Specification.pdf` and `docs/reference/EdNova_Guide.pdf`
(official), plus the team's registration-email notes (marked *email*). Official PDFs win on conflict.

## The platform (official)
- OpenAI-compatible inference API, open-source models, **CPU only**. One dedicated,
  non-transferable key per team. Auth: `Authorization: Bearer <key>` on every request.
- **Responses arrive whole — no token streaming.** Several seconds is normal (more on mid-size).
  "This latency is a design budget to allocate, not an incident to report."
- Base URL is **configurable, never hard-coded** → `CLOUD_BASE_URL` (resolved into `settings.llm`).
- Endpoints: `GET /v1/models`, `POST /v1/chat/completions`, and a **separately metered** embeddings
  endpoint with its own quota.
- No fine-tuning. All intelligence comes from prompt design, supplied context, model choice per
  step, and architecture.
- A vector database is deployed by the platform, **one collection per team**. **We use Qdrant**
  (`QdrantVectorStore`, ARCHITECTURE.md): the platform's Qdrant if its endpoint is exposed to us,
  otherwise our own Qdrant (local in docker-compose, hosted for the demo — declared).
- Base URL: `https://llm.felcloud.io/v1`. Our key name: **hack-04** (the key itself only in `.env`).

## Model classes
| Class | Size | Capacity | Use for | Env var |
| --- | --- | --- | --- | --- |
| Compact | < 3B | ≈ 60% | classification, intent, extraction, formatting, rewriting, short summaries, **fallback** | `CLOUD_MODEL_COMPACT` |
| Mid-size | ≤ 16B | ≈ 40% | reasoning, multi-source synthesis, planning, final user-facing writing | `CLOUD_MODEL_MID` |

Exact model names: run `scripts/probe_models.py` in our slot (see docs/MODELS.md for the shortlist
and how the pick is made), put them in `.env`, record in DECISIONS.md.
Local models (Ollama) are **dev-only**, for work outside our slot: the rules forbid replacement services
during the demo, and live AI output must come from the platform (ARCHITECTURE.md §Providers).
**The scarce resource is mid-size compute time.** Sending everything to mid-size "to be safe" is
penalised; so is compact-only quality.

Official orchestration patterns — use these names in code comments, logs and the report:
- **escalation** — compact handles it; mid-size only when needed
- **draft-then-revise** — compact drafts, mid-size corrects
- **plan-once / execute-compact** — one mid-size plan, compact executes the steps
- **narrow-before-generating** — vector search + compact filter shrink context before a mid-size call

## Quota (official)
- **Token bucket where each request consumes one unit** (not tokens). Continuous refill at a
  sustained rate up to a ceiling — **no reset at a clock boundary**.
- **Burst reserve** for occasional salvos (e.g. indexing a batch of documents).
- Additional ceilings: **max response length per request** and **max concurrent requests per key**.
- *email*: 20 requests/min sustained, 2 concurrent. Gateway defaults `LLM_MAX_RPM=18`,
  `LLM_MAX_CONCURRENCY=2`; adjust from the real quota headers once observed.
- Tiers over the lifecycle: **Reduced** (integration, pre-event) → **Baseline** (challenge) →
  **Widened** (jury demo slot — no team is quota limited).

Implication: the economy of *requests* matters more than tokens. One call for 10 quiz questions,
never 10 calls. Batch chunk-tagging several chunks per call.

## Response & error contract (official, stable for the whole challenge)
| Situation | Service response | Required handling | Our gateway | User sees |
| --- | --- | --- | --- | --- |
| Normal | `200` + quota headers | read remaining quota, pace requests | parse headers → `QuotaState`; when low, pause background lane | nothing |
| Team quota exhausted | "team quota exhausted" + delay | wait the stated delay, retry | requeue with `not_before = now + delay`; expose queue position/ETA | "High demand, your quiz is in line (about N s)" + cached content |
| Model class saturated | `503` + `Retry-After` | retry at intervals **or** fall back to compact | interactive: one retry then compact fallback (`quick_mode=true`); background: retry later | "Quick mode" badge |
| Request beyond a ceiling | `400`, message names the ceiling | fix the request | parse message → reduce `max_tokens` / chunks / history, or split; resend once | nothing, or shorter answer |
| Identical request | — | must not regenerate | `ai_cache` hit, no call | instant |

The exact status code and header names for "quota exhausted" and for quota headers are not
documented — the parser must be tolerant (log unknown `x-*`/`ratelimit-*` headers on first sight)
and the mock must make them configurable. Record real values in DECISIONS.md.

"Normal latency and occasional queueing are expected, not a malfunction." Persistent errors →
organisers' support channel (wie.act@ieee.tn).

## Metrics the organisers compute on our key (mirror them in `ai_call_log`)
Calls total and per model · compact/mid split (the orchestration indicator) · tokens in/out ·
repeated identical requests (the cache indicator — keep this near zero) · quota refusals and how
they were handled. Logged centrally: timestamp, model, token volume, return code.
Our `/admin/stats` page shows the same numbers for the report and demo.

## Time slots (*email*; Tunis time, 20/10 → 10/11)
Group A 12:00–24:00 / Group B 00:00–12:00, alternating by weekday
(Tue 20/10 12–24, Wed 21/10 00–12, Thu 22/10 12–24, Fri 23/10 00–12, …).
Our group is `LLM_SLOT_GROUP` in `.env`; `scripts/slot.py` prints whether the key is live now.
Deadline Tue 10/11 is a 00:00–12:00 slot if the pattern holds → **record the demo by Mon 9/11.**

Outside the slot: dev and tests use `mock-llm/`; the deployed site runs **"Offline demo mode"**
(only real cached results, new AI actions disabled with a banner). Never fake AI output live.

## Rules (official)
- Credentials never in code, repos, logs, screenshots or videos. Repo ships a config template.
- No bypassing quota via extra keys, accounts or a replacement API during the demo.
  **Additional external services are allowed if clearly declared** (DECISIONS.md → Declared services).
- Only public, fictional, synthetic or anonymised data may be sent to the service.
- Don't store sensitive personal data; don't collect names, photos, voices, addresses.
- The AI must not discriminate by gender, region, **language level** or background — adapting
  difficulty is fine; tone and respect must not change with level or language.
- The AI supports learning; it does not replace teachers or mentors.

## Deliverables (Phase 1, deadline 10 Nov)
Repo must contain: source code · setup instructions · README · prototype screenshots ·
**technical explanation of the GenAI module** · credential-free config template.
Report ≤ 6 pages: objective, architecture, models/API, RAG workflow, privacy & ethics, testing
strategy & results, limited-capacity handling, business-model note (target users, value
proposition, adoption path, sustainability). Demo video ≤ 1 min 30 s showing the waiting/fallback
behaviour. Phase 2: 4-min pitch by two members, 2-min Q&A.

## Scoring
Platform part: orchestration 25 · constraints 25 · relevance & usefulness 20 · resilience under
load 15 · originality 10 · presentation 5. General grid: innovation, technical feasibility (incl.
how thoughtfully the models are combined and the service is used), relevance, impact,
entrepreneurship, pitch & demo. Bonus: real user testing, multilingual (Arabic, Darija, French, English).
