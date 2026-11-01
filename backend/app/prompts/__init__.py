"""Versioned prompt templates (one .md file per task). Format:

<!-- version: 1 · tier: mid · pattern: narrow-before-generating · output: {...} -->
## system
... {placeholders} ...
## user
... {placeholders} ...
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DIR = Path(__file__).parent
_VERSION = re.compile(r"version:\s*([\w.]+)")
_SECTION = re.compile(r"^##\s+(system|user)\s*$", re.MULTILINE)

# How each UI language is named to the model. Darija is written in Arabic script.
LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "ar": "Modern Standard Arabic",
    "ar-TN": "Tunisian Darija written in Arabic script",
}


@lru_cache
def voice_rules() -> str:
    """Shared rules for student-facing prompts (_voice_rules.md), without its header comment."""
    text = (DIR / "_voice_rules.md").read_text(encoding="utf-8")
    body = re.sub(r"^<!--.*?-->\s*", "", text, flags=re.DOTALL)
    return "\n".join(line.strip() for line in body.strip().splitlines())


def voice_rules_version() -> int:
    m = _VERSION.search((DIR / "_voice_rules.md").read_text(encoding="utf-8"))
    return int(m.group(1)) if m else 0


@lru_cache
def _load(name: str) -> tuple[str, dict[str, str]]:
    text = (DIR / f"{name}.md").read_text(encoding="utf-8")
    m = _VERSION.search(text)
    version = m.group(1) if m else "0"
    parts = _SECTION.split(text)
    sections = {
        parts[i]: "\n".join(line.strip() for line in parts[i + 1].strip().splitlines())
        for i in range(1, len(parts) - 1, 2)
    }
    return version, sections


def render(name: str, **values: Any) -> tuple[str, list[dict[str, str]]]:
    """(version, messages) with {placeholders} filled. `language` gets its full name."""
    version, sections = _load(name)
    if "language" in values:
        values.setdefault("language_name", LANGUAGE_NAMES.get(values["language"], "English"))
    values.setdefault("voice_rules", voice_rules())
    messages = [
        {"role": role, "content": sections[role].format(**values)}
        for role in ("system", "user")
        if role in sections
    ]
    return version, messages
