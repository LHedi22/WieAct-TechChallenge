"""Audit N-8 (5 Nov): /api/health said "status": "ok" while Qdrant was down, though every Tutor,
quiz and pack start failed meanwhile.

Now liveness and readiness are separate:
- /api/health (liveness: Railway's healthcheck, compose's backend healthcheck) stays 200 unless
  Postgres is down, but its body reports every dependency AI starts need (Qdrant, embeddings,
  worker) and says "degraded" when one is out;
- ?strict=1 (start-prod.sh's watchdog) still only looks at the worker, so a Qdrant or
  embeddings outage can never put the container into a restart loop;
- /api/health/ready (readiness) answers 503 while any of them is out."""

import httpx
import pytest

from app.api.health import check_embeddings, check_qdrant, check_worker, probe_embeddings
from app.core.config import get_settings
from app.core.db import get_session
from app.main import create_app
from tests.test_app import FakeSession


def client_for(qdrant="ok", embeddings="ok", worker=("ok", 3), db_ok=True) -> httpx.AsyncClient:
    app = create_app()

    async def session():
        yield FakeSession(db_ok)

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[check_qdrant] = lambda: qdrant
    app.dependency_overrides[check_embeddings] = lambda: embeddings
    app.dependency_overrides[check_worker] = lambda: worker
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def get_all(c):
    return (
        await c.get("/api/health"),
        await c.get("/api/health", params={"strict": 1}),
        await c.get("/api/health/ready"),
    )


@pytest.mark.parametrize("down", [{"qdrant": "error"}, {"embeddings": "error"}])
async def test_a_dependency_outage_is_degraded_and_not_ready_but_never_restarts(down):
    async with client_for(**down) as c:
        live, strict, ready = await get_all(c)
    assert live.status_code == 200 and live.json()["status"] == "degraded"  # before: "ok"
    assert strict.status_code == 200  # the watchdog only restarts a frozen worker
    assert ready.status_code == 503 and ready.json()["ready"] is False


async def test_all_green_is_ready():
    async with client_for() as c:
        live, strict, ready = await get_all(c)
    assert [r.status_code for r in (live, strict, ready)] == [200, 200, 200]
    assert live.json()["status"] == "ok" and ready.json()["ready"] is True


async def test_skipped_embeddings_check_does_not_block_readiness():
    """The platform's embeddings endpoint is metered: it is never probed by a health check."""
    async with client_for(embeddings="skipped") as c:
        live, _, ready = await get_all(c)
    assert live.json()["status"] == "ok" and ready.status_code == 200


async def test_a_dead_worker_is_not_ready_and_restarts():
    async with client_for(worker=("stale", 900)) as c:
        live, strict, ready = await get_all(c)
    assert live.status_code == 200 and strict.status_code == 503 and ready.status_code == 503


async def test_embeddings_check_probes_only_self_hosted_models(monkeypatch):
    for k, v in {"LLM_PROVIDER": "mock", "EMBED_PROVIDER": "same"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, json={"data": []})

        transport = httpx.MockTransport(handler)
        assert await probe_embeddings(get_settings(), transport=transport) == "ok"
        assert seen and seen[0].endswith("/models")
        monkeypatch.setenv("LLM_PROVIDER", "cloud")
        monkeypatch.setenv("CLOUD_API_KEY", "test-only-not-a-key")
        monkeypatch.setenv("CLOUD_BASE_URL", "http://cloud.invalid/v1")
        get_settings.cache_clear()
        assert await probe_embeddings(get_settings(), transport=transport) == "skipped"
        assert len(seen) == 1  # no request to the platform
    finally:
        get_settings.cache_clear()
