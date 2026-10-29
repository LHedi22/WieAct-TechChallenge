"""Passwords (argon2) and the session cookie (user id + issued-at, HMAC-SHA256 with SECRET_KEY).

No sessions table: the cookie is self-contained and expires after SESSION_MAX_AGE_S. Signing out
deletes the cookie on the client."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

COOKIE_NAME = "lw_session"
SESSION_MAX_AGE_S = 30 * 24 * 3600
MIN_PASSWORD = 8

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False  # includes dev users, whose stored hash is unusable on purpose


def _sig(payload: str) -> str:
    key = get_settings().SECRET_KEY.get_secret_value().encode("utf-8")
    mac = hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def sign_session(user_id: uuid.UUID, now: float | None = None) -> str:
    payload = f"{user_id.hex}.{int(now if now is not None else time.time())}"
    return f"{payload}.{_sig(payload)}"


def read_session(token: str | None, now: float | None = None) -> uuid.UUID | None:
    """The user id if the cookie is authentic and not expired, else None."""
    if not token or token.count(".") != 2:
        return None
    uid, issued, sig = token.split(".")
    if not hmac.compare_digest(sig, _sig(f"{uid}.{issued}")):
        return None
    try:
        age = (now if now is not None else time.time()) - int(issued)
        user_id = uuid.UUID(hex=uid)
    except ValueError:
        return None
    return user_id if 0 <= age <= SESSION_MAX_AGE_S else None
