import os

import pytest

from app.core import config

_PREFIXES = ("LLM_", "CLOUD_", "LOCAL_", "MOCK_", "QDRANT_", "APP_ENV", "SECRET_KEY")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests never read the developer's .env or shell env, and always default to the mock."""
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith(_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
