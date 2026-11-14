"""Audit CA-2: settings nobody reads (LOG_PROMPTS, LLM_MAX_TOKENS_DEFAULT, APP_TIMEZONE) suggested
switches that do nothing. Every setting is read outside its definition; the provider profiles
(CLOUD_/LOCAL_/MOCK_*) are read through `getattr` in Settings.llm."""

import re
from pathlib import Path

from app.core.config import Settings

APP = Path(__file__).resolve().parents[1] / "app"
PROFILE = re.compile(r"^(CLOUD|LOCAL|MOCK)_")


def test_every_setting_is_read_somewhere():
    config = APP / "core" / "config.py"
    rest = "".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py") if p != config)
    defined = re.compile(r"^    [A-Z][A-Z0-9_]*: .*$", re.MULTILINE)  # the field lines
    body = defined.sub("", config.read_text(encoding="utf-8"))
    dead = [
        name
        for name in Settings.model_fields
        if not PROFILE.match(name) and name not in rest and name not in body
    ]
    assert dead == []
