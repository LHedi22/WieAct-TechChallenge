"""Mock behaviour, from MOCK_* env vars at start-up and changeable live via PATCH /_mock/config."""

from __future__ import annotations

import os

from pydantic import BaseModel


def _range(name: str, default: str) -> tuple[int, int]:
    lo, _, hi = os.environ.get(name, default).partition("-")
    return int(lo), int(hi or lo)


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class MockConfig(BaseModel):
    latency_compact_ms: tuple[int, int] = (1500, 3000)
    latency_mid_ms: tuple[int, int] = (5000, 12000)
    max_concurrency: int = 2
    rpm: float = 20  # token bucket: one unit per request, continuous refill
    burst: int = 10
    p_503_mid: float = 0.15
    p_503_compact: float = 0.0
    retry_after_503_s: int = 3
    p_quota: float = 0.0  # random "team quota exhausted" on top of the bucket
    quota_status: int = 429  # unknown on the real platform: keep configurable
    quota_delay_s: float = 5
    max_tokens_ceiling: int = 1024
    p_bad_json: float = 0.05
    blocked: bool = False  # 401 "Key is blocked", like the platform outside our slot
    header_remaining: str = "x-ratelimit-remaining"
    header_reset_ms: str = "x-ratelimit-reset-ms"
    model_compact: str = "mock-compact"
    model_mid: str = "mock-mid"
    model_embedding: str = "mock-embed"
    embedding_dim: int = 384
    embedding_rpm: float = 60  # embeddings have their own quota
    embedding_max_inputs: int = 64  # more inputs per call → 400 naming the limit
    p_503_embed: float = 0.0

    @classmethod
    def from_env(cls) -> MockConfig:
        return cls(
            latency_compact_ms=_range("MOCK_LATENCY_COMPACT_MS", "1500-3000"),
            latency_mid_ms=_range("MOCK_LATENCY_MID_MS", "5000-12000"),
            max_concurrency=int(_f("MOCK_MAX_CONCURRENCY", 2)),
            rpm=_f("MOCK_RPM", 20),
            burst=int(_f("MOCK_BURST", 10)),
            p_503_mid=_f("MOCK_P_503_MID", 0.15),
            p_503_compact=_f("MOCK_P_503_COMPACT", 0.0),
            p_quota=_f("MOCK_P_QUOTA", 0.0),
            quota_status=int(_f("MOCK_QUOTA_STATUS", 429)),
            quota_delay_s=_f("MOCK_QUOTA_DELAY_S", 5),
            max_tokens_ceiling=int(_f("MOCK_MAX_TOKENS_CEILING", 1024)),
            p_bad_json=_f("MOCK_P_BAD_JSON", 0.05),
            blocked=_b("MOCK_BLOCKED", False),
            header_remaining=os.environ.get("MOCK_HEADER_REMAINING", "x-ratelimit-remaining"),
            header_reset_ms=os.environ.get("MOCK_HEADER_RESET_MS", "x-ratelimit-reset-ms"),
            model_compact=os.environ.get("MOCK_MODEL_COMPACT", "mock-compact"),
            model_mid=os.environ.get("MOCK_MODEL_MID", "mock-mid"),
            model_embedding=os.environ.get("MOCK_EMBEDDING_MODEL", "mock-embed"),
            embedding_dim=int(_f("MOCK_EMBEDDING_DIM", 384)),
            embedding_rpm=_f("MOCK_EMBEDDING_RPM", 60),
            embedding_max_inputs=int(_f("MOCK_EMBEDDING_MAX_INPUTS", 64)),
            p_503_embed=_f("MOCK_P_503_EMBED", 0.0),
        )
