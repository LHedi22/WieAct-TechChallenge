# mock-llm — fake EdNova platform for development outside time slots

A tiny FastAPI app, OpenAI-compatible, that reproduces the platform's behaviour (PLATFORM.md) so the
gateway can be built and tested any time. Claude Code builds it in milestone M1.

## Endpoints
- `GET /v1/models` → two models: `mock-compact` and `mock-mid`
- `POST /v1/chat/completions` → whole response, no streaming (reject `stream: true` with 400)
- `POST /v1/embeddings` → deterministic vectors of size `MOCK_EMBEDDING_DIM` (default 384) from a hash of the text (separate quota); the mock gets its own Qdrant collection (`{prefix}-mock-…`, ARCHITECTURE.md §Providers)

## Behaviour (configurable via env and per-request header `X-Mock-Fault`)
| Setting | Default | Effect |
| --- | --- | --- |
| `MOCK_LATENCY_COMPACT_MS` | 1500–3000 | random sleep |
| `MOCK_LATENCY_MID_MS` | 5000–12000 | random sleep |
| `MOCK_MAX_CONCURRENCY` | 2 | extra concurrent requests get quota-style rejection |
| `MOCK_RPM` / `MOCK_BURST` | 20 / 10 | token bucket, one unit per request, continuous refill |
| `MOCK_P_503_MID` | 0.15 | mid-size returns `503` + `Retry-After: 3` |
| `MOCK_QUOTA_STATUS` | 429 | status used for "team quota exhausted" (unknown on real platform — keep configurable) |
| `MOCK_MAX_TOKENS_CEILING` | 1024 | `max_tokens` above → `400` with message naming the ceiling |
| `MOCK_P_BAD_JSON` | 0.05 | returns almost-JSON to exercise the repair path |
| `MOCK_BLOCKED` | false | every request → `401 {"error": "Key is blocked"}`, like the platform outside our slot (tests `LLM_PROVIDER=auto`) |
| Quota headers | `x-ratelimit-remaining`, `x-ratelimit-reset-ms` (names configurable) | on every 200 |

`X-Mock-Fault: 503 | quota | 400 | badjson | slow | blocked` forces a fault for one request (tests).

## Content
Responses must be **schema-valid** for each TaskKind so the UI works end to end: detect the task
from a marker in the system prompt (`<!-- task: QUIZ_GENERATE -->`) and return fixtures from
`mock-llm/fixtures/<task>.<lang>.json`, filled with words from the user content where possible.
Fixtures exist in en, fr, ar.

Run: `docker compose up -d mock-llm` → `http://localhost:9000/v1`.
