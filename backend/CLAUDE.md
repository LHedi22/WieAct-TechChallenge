# Backend (FastAPI) — local rules

- Python 3.12, managed by **uv** (`uv add <pkg>`, never pip). Async everywhere (SQLAlchemy 2 async + asyncpg, httpx).
- Layout: `app/core` (config, db, economy, security) · `app/gateway` · `app/rag` · `app/features/<name>/{router,service,jobs,schemas}.py` · `app/prompts/*.md` · `app/models`.
- Only `app/gateway/` imports `openai`. Features call `await gateway.run(Task(...))`.
- Client settings: `AsyncOpenAI(base_url=settings.llm.base_url, api_key=settings.llm.api_key, timeout=settings.LLM_TIMEOUT_S, max_retries=0)` — `settings.llm` is the profile resolved from `LLM_PROVIDER` (ARCHITECTURE.md §Providers); nothing else reads `CLOUD_*`/`LOCAL_*`/`MOCK_*` — retries are ours (the SDK's own retries would break the contract handling and RPM accounting). Read raw headers with `.with_raw_response`.
- The limiter must be **global across worker processes** (Postgres advisory locks or a single worker process with asyncio) — 2 concurrent per key total, not per process. Default: one worker process.
- Every schema change → Alembic migration (`uv run alembic revision --autogenerate -m "..."`).
- Money-like values (coins, points) are integers; every change is a ledger row in one transaction.
- Dates: store UTC; "today" for daily refill/challenges/streaks is computed in `Africa/Tunis`.
- Errors to clients are i18n message keys (`errors.quota_queue`, …), never raw exceptions or model text.
- Logs: never log headers, prompts with user text in production (`LOG_PROMPTS=false` default), or the key.
- Tests: pytest + pytest-asyncio; `tests/conftest.py` sets `LLM_PROVIDER=mock` and points `MOCK_BASE_URL` at the mock app in-process (ASGI transport) so tests never touch the network.
