import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import config, db

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "mock-llm" / "src"))  # the mock runs in-process (ASGI transport)

from mock_llm.app import create_app as create_mock_app  # noqa: E402
from mock_llm.config import MockConfig  # noqa: E402

from tests.db import prepare, test_url  # noqa: E402

_PREFIXES = ("LLM_", "CLOUD_", "LOCAL_", "MOCK_", "QDRANT_", "APP_ENV", "SECRET_KEY", "ADMIN_")

# Module-level too: test modules that import app.main build the app at import time, before any
# fixture runs, and must not see the developer's .env or shell.
config.Settings.model_config["env_file"] = None
for _name in list(os.environ):
    if _name.startswith(_PREFIXES):
        del os.environ[_name]
os.environ["LLM_PROVIDER"] = "mock"

DEV_DB_URL = os.environ.get("DATABASE_URL", config.Settings().DATABASE_URL)
TABLES = (
    "coin_ledger, points_ledger, peer_votes, peer_answers, peer_questions, "
    "ai_call_log, ai_cache, jobs, mistakes, quiz_attempts, tutor_sessions, presence, "
    "placement_sets, chapter_mastery, course_levels, "
    "profiles, quiz_sets, chunks, documents, chapters, courses, "
    "world_members, worlds, users"
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests never read the developer's .env or shell env, and always default to the mock."""
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith(_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_BASE_URL", "http://mock/v1")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = test_url(DEV_DB_URL)
    if not prepare(url):
        pytest.skip("Postgres not reachable at DATABASE_URL (docker compose up -d db)")
    return url


@pytest.fixture
async def sm(pg_url, monkeypatch):
    """Session factory on a clean test database."""
    monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = create_async_engine(pg_url)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # Code that opens its own sessions (job handlers, rag) calls db.get_sessionmaker() at run
    # time: point it at this test's engine (the cached app engine belongs to another loop).
    monkeypatch.setattr(db, "get_sessionmaker", lambda: factory)
    yield factory
    await engine.dispose()


FAST_MOCK = dict(latency_compact_ms=(0, 0), latency_mid_ms=(0, 0), p_503_mid=0, p_bad_json=0)


@pytest.fixture
def mock_llm():
    """In-process mock platform; tweak `mock_llm.state.cfg` per test."""
    return create_mock_app(MockConfig(**FAST_MOCK), seed=7)


def mock_transport(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
