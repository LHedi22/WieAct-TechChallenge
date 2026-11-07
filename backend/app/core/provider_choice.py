"""The AI provider picked in the UI (development only): "cloud" = the competition platform's models,
"local" = our own Ollama. It overrides LLM_PROVIDER at runtime, with no restart.

The choice is a one-word file in UPLOAD_DIR, which the API and the worker share (one volume in
docker-compose), next to the upload files. No file = LLM_PROVIDER from
.env decides. Production always runs on the platform and ignores the file.

With a choice set, embeddings come from our own Ollama (bge-m3) unless EMBED_PROVIDER names a real
provider: the platform key has no embeddings model (DECISIONS.md 2026-10-31) and the mock's vectors
are word counts, not meaning."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from app.core.config import Provider, get_settings

Choice = Literal["cloud", "local"]
CHOICES: tuple[str, ...] = get_args(Choice)
FILE = ".llm_provider"

# Who made a piece of content, best first: content from a weaker provider is never served while a
# better one is active, and is replaced when the active one writes it again (core/provenance.py).
RANK: dict[str | None, int] = {"cloud": 3, "local": 2, "mock": 1, None: 0}


def _path() -> Path:
    return Path(get_settings().UPLOAD_DIR) / FILE


def get() -> Choice | None:
    if get_settings().APP_ENV == "production":
        return None
    try:
        value = _path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if value in CHOICES else None  # type: ignore[return-value]


def set_choice(choice: Choice) -> None:
    if choice not in CHOICES:
        raise ValueError(choice)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(choice, encoding="utf-8")


def clear() -> None:
    _path().unlink(missing_ok=True)


def target() -> str:
    """The provider new content should come from: the UI choice, else LLM_PROVIDER (auto counts as
    local, the provider it uses outside our slot)."""
    s = get_settings()
    if s.APP_ENV == "production":
        return "cloud"
    chosen = get() or s.LLM_PROVIDER
    return "local" if chosen == "auto" else chosen


def embed_provider() -> Provider | None:
    """The fixed embeddings provider, or None when embeddings follow the chat provider."""
    s = get_settings()
    if s.EMBED_PROVIDER in ("cloud", "local"):
        return s.EMBED_PROVIDER
    if get() is not None:
        return "local"
    return None if s.EMBED_PROVIDER == "same" else s.EMBED_PROVIDER
