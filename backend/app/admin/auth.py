"""Who may use the admin side (/admin, /api/admin/*).

- `ADMIN_TOKEN` blank → every admin route answers 404, in every environment.
- `POST /api/admin/session {token, label}` compares the token in constant time and sets the
  `lw_admin` cookie: signed with SECRET_KEY, HttpOnly, SameSite=strict, Secure in production, 8 h.
  The token itself never reaches browser storage. The cookie carries a fingerprint of the token,
  so rotating ADMIN_TOKEN signs every admin out.
- Scripts (export_stats.py, load.py) send `X-Admin-Token` instead.
- Every mutating admin route also needs `X-Admin-Action: 1` (CSRF defence: a cross-site form
  can't set a custom header).
- Sign-in attempts are limited to 5 per minute per IP (in process: one API process in production).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request

from app.core.config import Settings, get_settings

ADMIN_COOKIE = "lw_admin"
ADMIN_MAX_AGE_S = 8 * 3600
SESSION_ATTEMPTS_PER_MIN = 5


@dataclass(frozen=True)
class Admin:
    actor: str  # the label typed at sign-in ("admin" by default), or "script" for the header
    via: str  # cookie | token


def _token(settings: Settings) -> str:
    return settings.ADMIN_TOKEN.get_secret_value()


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _sig(payload: str) -> str:
    key = get_settings().SECRET_KEY.get_secret_value().encode("utf-8")
    mac = hmac.new(key, f"admin|{payload}".encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> str:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8")


def sign_admin(label: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = f"a1.{issued}.{_b64(label)}.{_fingerprint(_token(get_settings()))}"
    return f"{payload}.{_sig(payload)}"


def read_admin(cookie: str | None, now: float | None = None) -> str | None:
    """The admin's label if the cookie is authentic, unexpired and for the current token."""
    token = _token(get_settings())
    if not cookie or not token or cookie.count(".") != 4:
        return None
    *fields, sig = cookie.split(".")
    if not hmac.compare_digest(sig, _sig(".".join(fields))):
        return None
    version, issued, label, fp = fields
    if version != "a1" or not hmac.compare_digest(fp, _fingerprint(token)):
        return None
    try:
        age = (now if now is not None else time.time()) - int(issued)
        name = _unb64(label)
    except (ValueError, UnicodeDecodeError):
        return None
    return name if 0 <= age <= ADMIN_MAX_AGE_S else None


def token_matches(given: str, settings: Settings) -> bool:
    token = _token(settings)
    return bool(token) and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))


class AttemptLimiter:
    """At most SESSION_ATTEMPTS_PER_MIN sign-in attempts per IP in any 60 s window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.seen: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, ip: str) -> int:
        """Record an attempt; returns seconds to wait (0 = allowed)."""
        now = self.clock()
        q = self.seen[ip]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= SESSION_ATTEMPTS_PER_MIN:
            return max(1, int(60 - (now - q[0])) + 1)
        q.append(now)
        return 0


attempts = AttemptLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def require_enabled() -> Settings:
    settings = get_settings()
    if not _token(settings):
        raise HTTPException(404, "Not Found")  # the admin side doesn't exist without a token
    return settings


async def current_admin(
    settings: Annotated[Settings, Depends(require_enabled)],
    lw_admin: Annotated[str | None, Cookie(alias=ADMIN_COOKIE)] = None,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> Admin:
    if x_admin_token is not None:
        if token_matches(x_admin_token, settings):
            return Admin(actor="script", via="token")
        raise HTTPException(401, "errors.admin_required")
    if (label := read_admin(lw_admin)) is not None:
        return Admin(actor=label, via="cookie")
    raise HTTPException(401, "errors.admin_required")


async def admin_action(
    admin: Annotated[Admin, Depends(current_admin)],
    x_admin_action: Annotated[str | None, Header()] = None,
) -> Admin:
    if x_admin_action != "1":
        raise HTTPException(403, "errors.admin_action_header")
    return admin


AdminDep = Annotated[Admin, Depends(current_admin)]
AdminActionDep = Annotated[Admin, Depends(admin_action)]
