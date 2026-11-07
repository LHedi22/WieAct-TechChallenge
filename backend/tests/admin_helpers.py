"""Shared bits for admin tests: a test-only token and the headers scripts and the UI send."""

from app.core.config import get_settings

TOKEN = "test-only-admin-token-0123456789-abcdef"  # 39 chars, long enough for production
READ = {"X-Admin-Token": TOKEN}
ACT = {**READ, "X-Admin-Action": "1"}


def enable_admin(monkeypatch, token: str = TOKEN) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()

