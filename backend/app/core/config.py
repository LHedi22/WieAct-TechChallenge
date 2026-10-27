"""Application settings.

The CLOUD_/LOCAL_/MOCK_ profile variables are read here and nowhere else: `_resolve_llm()` turns
LLM_PROVIDER + the matching profile into one `settings.llm` object (ARCHITECTURE.md §Providers).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

Provider = Literal["cloud", "local", "mock"]
ProviderSetting = Literal["cloud", "local", "mock", "auto"]


class LLMProfile(BaseModel):
    """The provider profile every LLM / embeddings call uses."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    base_url: str
    api_key: SecretStr
    model_compact: str
    model_mid: str
    embedding_model: str
    embedding_dim: int

    @property
    def embedding_slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.embedding_model.lower()).strip("-")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM provider ---
    LLM_PROVIDER: ProviderSetting = "mock"

    CLOUD_BASE_URL: str = ""
    CLOUD_API_KEY: SecretStr = SecretStr("")
    CLOUD_MODEL_COMPACT: str = "pending-probe"
    CLOUD_MODEL_MID: str = "pending-probe"
    CLOUD_EMBEDDING_MODEL: str = "pending-probe"
    CLOUD_EMBEDDING_DIM: int = 1024

    LOCAL_BASE_URL: str = "http://localhost:11434/v1"
    LOCAL_API_KEY: SecretStr = SecretStr("ollama")
    LOCAL_MODEL_COMPACT: str = "qwen3:1.7b"
    LOCAL_MODEL_MID: str = "qwen3:8b"
    LOCAL_EMBEDDING_MODEL: str = "bge-m3"
    LOCAL_EMBEDDING_DIM: int = 1024

    MOCK_BASE_URL: str = "http://localhost:9000/v1"
    MOCK_API_KEY: SecretStr = SecretStr("mock")
    MOCK_MODEL_COMPACT: str = "mock-compact"
    MOCK_MODEL_MID: str = "mock-mid"
    MOCK_EMBEDDING_MODEL: str = "mock-embed"
    MOCK_EMBEDDING_DIM: int = 384

    # --- shared by every provider ---
    LLM_DISABLE_THINKING: bool = True
    LLM_TIMEOUT_S: float = 90
    LLM_MAX_RPM: int = 18
    LLM_MAX_CONCURRENCY: int = 2
    LLM_MAX_TOKENS_DEFAULT: int = 700
    LLM_SLOT_GROUP: Literal["A", "B"] = "A"

    # --- vector store ---
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: SecretStr = SecretStr("")
    QDRANT_COLLECTION_PREFIX: str = "hack-04-chunks"

    # --- app ---
    APP_ENV: Literal["development", "production"] = "development"
    DATABASE_URL: str = "postgresql+asyncpg://lw:lw@localhost:5432/learningworld"
    SECRET_KEY: SecretStr = SecretStr("change-me-in-.env")
    APP_TIMEZONE: str = "Africa/Tunis"
    CORS_ORIGINS: str = "http://localhost:5173"
    OFFLINE_DEMO_MODE: Literal["auto", "on", "off"] = "auto"
    LOG_PROMPTS: bool = False
    UPLOAD_MAX_MB: int = 50
    TESSERACT_LANGS: str = "ara+fra+eng"

    _llm: LLMProfile = PrivateAttr()

    @model_validator(mode="after")
    def _check_and_resolve(self) -> Settings:
        if self.APP_ENV == "production":
            if self.LLM_PROVIDER != "cloud":
                raise ValueError(
                    f"APP_ENV=production requires LLM_PROVIDER=cloud (got {self.LLM_PROVIDER}); "
                    "local and mock providers are dev-only"
                )
            if self.SECRET_KEY.get_secret_value() in ("", "change-me-in-.env"):
                raise ValueError("APP_ENV=production requires a real SECRET_KEY")
        self._llm = self._resolve_llm()
        if self._llm.provider == "cloud":
            if not self.CLOUD_API_KEY.get_secret_value():
                raise ValueError(
                    "LLM provider is cloud but CLOUD_API_KEY is empty (set it in .env)"
                )
            if not self.CLOUD_BASE_URL:
                raise ValueError("LLM provider is cloud but CLOUD_BASE_URL is empty")
        return self

    def _resolve_llm(self) -> LLMProfile:
        # M0: auto -> local. Slot-aware per-job resolution (cloud while our slot is live) is M1.
        provider: Provider = "local" if self.LLM_PROVIDER == "auto" else self.LLM_PROVIDER
        p = provider.upper()
        return LLMProfile(
            provider=provider,
            base_url=getattr(self, f"{p}_BASE_URL"),
            api_key=getattr(self, f"{p}_API_KEY"),
            model_compact=getattr(self, f"{p}_MODEL_COMPACT"),
            model_mid=getattr(self, f"{p}_MODEL_MID"),
            embedding_model=getattr(self, f"{p}_EMBEDDING_MODEL"),
            embedding_dim=getattr(self, f"{p}_EMBEDDING_DIM"),
        )

    @property
    def llm(self) -> LLMProfile:
        return self._llm

    @property
    def qdrant_collection(self) -> str:
        return f"{self.QDRANT_COLLECTION_PREFIX}-{self.llm.provider}-{self.llm.embedding_slug}"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
