"""Admin-only "force Quick mode" switch for the demo video (audit F-VID-1, PROMPTS.md M8 item 6).

While on, interactive mid-size tasks are answered by the compact model as Quick mode: a real call,
logged with pattern `forced-fallback`, and (like every Quick-mode answer) never cached as the
class's copy. It lets the fallback be shown on camera without editing code.

- Off by default. `FORCE_QUICK_MODE=on` (development only; production refuses to start with it)
  keeps it on for a whole dev session.
- At runtime an admin switches it on for 1–30 minutes (POST /api/admin/force-quick with the admin
  token) and it turns itself off. The state is an expiry time in a file in UPLOAD_DIR, which the
  API and the worker share (one container in production, one volume in docker-compose)."""

from __future__ import annotations

import time
from pathlib import Path

from app.core.config import get_settings

MAX_MINUTES = 30
FILE = ".force_quick_until"


def _path() -> Path:
    return Path(get_settings().UPLOAD_DIR) / FILE


def until() -> float | None:
    try:
        return float(_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def active(now: float | None = None) -> bool:
    settings = get_settings()
    if settings.FORCE_QUICK_MODE == "on" and settings.APP_ENV != "production":
        return True
    end = until()
    return end is not None and (now if now is not None else time.time()) < end


def switch_on(minutes: int, now: float | None = None) -> float:
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    end = (now if now is not None else time.time()) + minutes * 60
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(end), encoding="utf-8")
    return end


def switch_off() -> None:
    _path().unlink(missing_ok=True)
