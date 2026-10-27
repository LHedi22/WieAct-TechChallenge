import pytest
from pydantic import ValidationError

from app.core.config import Settings

CLOUD_ENV = {
    "CLOUD_BASE_URL": "https://platform.example/v1",
    "CLOUD_API_KEY": "test-key",
    "CLOUD_MODEL_COMPACT": "c-small",
    "CLOUD_MODEL_MID": "c-mid",
    "CLOUD_EMBEDDING_MODEL": "C/Embed-v1",
    "CLOUD_EMBEDDING_DIM": "768",
}


def make(monkeypatch, **env: str) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_mock_profile(monkeypatch):
    s = make(monkeypatch, LLM_PROVIDER="mock", MOCK_BASE_URL="http://mock:9000/v1")
    assert s.llm.provider == "mock"
    assert s.llm.base_url == "http://mock:9000/v1"
    assert (s.llm.model_compact, s.llm.model_mid) == ("mock-compact", "mock-mid")
    assert s.llm.embedding_dim == 384
    assert s.qdrant_collection == "hack-04-chunks-mock-mock-embed"


def test_local_profile(monkeypatch):
    s = make(monkeypatch, LLM_PROVIDER="local", LOCAL_MODEL_MID="qwen3:14b")
    assert s.llm.provider == "local"
    assert s.llm.base_url == "http://localhost:11434/v1"
    assert s.llm.model_compact == "qwen3:1.7b"
    assert s.llm.model_mid == "qwen3:14b"
    assert s.llm.embedding_model == "bge-m3"
    assert s.llm.embedding_dim == 1024


def test_cloud_profile(monkeypatch):
    s = make(monkeypatch, LLM_PROVIDER="cloud", **CLOUD_ENV)
    assert s.llm.provider == "cloud"
    assert s.llm.base_url == "https://platform.example/v1"
    assert s.llm.api_key.get_secret_value() == "test-key"
    assert (s.llm.model_compact, s.llm.model_mid) == ("c-small", "c-mid")
    assert s.llm.embedding_dim == 768
    assert s.qdrant_collection == "hack-04-chunks-cloud-c-embed-v1"


def test_auto_resolves_to_local_in_m0(monkeypatch):
    s = make(monkeypatch, LLM_PROVIDER="auto")
    assert s.llm.provider == "local"


def test_cloud_without_key_refuses(monkeypatch):
    env = CLOUD_ENV | {"CLOUD_API_KEY": ""}
    with pytest.raises(ValidationError, match="CLOUD_API_KEY is empty"):
        make(monkeypatch, LLM_PROVIDER="cloud", **env)


@pytest.mark.parametrize("provider", ["mock", "local"])
def test_missing_cloud_key_is_fine_for_other_providers(monkeypatch, provider):
    assert make(monkeypatch, LLM_PROVIDER=provider).llm.provider == provider


def test_key_never_in_repr(monkeypatch):
    s = make(monkeypatch, LLM_PROVIDER="cloud", **CLOUD_ENV)
    assert "test-key" not in repr(s)
    assert "test-key" not in repr(s.llm)


def test_cors_origins_split(monkeypatch):
    s = make(monkeypatch, CORS_ORIGINS="http://a, http://b")
    assert s.cors_origins == ["http://a", "http://b"]


@pytest.mark.parametrize("provider", ["mock", "local", "auto"])
def test_production_refuses_non_cloud(monkeypatch, provider):
    with pytest.raises(ValidationError, match="requires LLM_PROVIDER=cloud"):
        make(monkeypatch, APP_ENV="production", LLM_PROVIDER=provider, SECRET_KEY="s3cr3t-prod")


def test_production_refuses_default_secret(monkeypatch):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make(monkeypatch, APP_ENV="production", LLM_PROVIDER="cloud", **CLOUD_ENV)


def test_production_cloud_starts(monkeypatch):
    s = make(
        monkeypatch,
        APP_ENV="production",
        LLM_PROVIDER="cloud",
        SECRET_KEY="s3cr3t-prod",
        **CLOUD_ENV,
    )
    assert s.llm.provider == "cloud"
