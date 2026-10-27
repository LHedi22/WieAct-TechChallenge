import httpx
import pytest
from pydantic import ValidationError

from app.api.health import check_qdrant
from app.core.db import get_session
from app.main import create_app


class FakeSession:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    async def execute(self, _stmt):
        if not self.ok:
            raise ConnectionError("db down")


def client_for(db_ok: bool, qdrant: str = "ok") -> httpx.AsyncClient:
    app = create_app()

    async def session():
        yield FakeSession(db_ok)

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[check_qdrant] = lambda: qdrant
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_green():
    async with client_for(db_ok=True) as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "db": "ok",
        "qdrant": "ok",
        "provider": "mock",
        "app_env": "development",
    }


async def test_health_qdrant_down_is_reported_not_fatal():
    async with client_for(db_ok=True, qdrant="error") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["qdrant"] == "error"


async def test_health_db_down_is_503():
    async with client_for(db_ok=False) as c:
        r = await c.get("/api/health")
    assert r.status_code == 503
    assert r.json()["status"] == "error"


@pytest.mark.parametrize("provider", ["mock", "local", "auto"])
def test_app_refuses_to_start_in_production_without_cloud(monkeypatch, provider):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("SECRET_KEY", "s3cr3t-prod")
    with pytest.raises(ValidationError, match="requires LLM_PROVIDER=cloud"):
        create_app()


def test_app_starts_in_production_with_cloud(monkeypatch):
    for k, v in {
        "APP_ENV": "production",
        "LLM_PROVIDER": "cloud",
        "SECRET_KEY": "s3cr3t-prod",
        "CLOUD_BASE_URL": "https://platform.example/v1",
        "CLOUD_API_KEY": "test-key",
    }.items():
        monkeypatch.setenv(k, v)
    app = create_app()
    assert app.docs_url is None
