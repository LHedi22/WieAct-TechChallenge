"""Admin sign-in: the token is exchanged once for the `lw_admin` cookie (see admin/auth.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.admin import audit
from app.admin.auth import (
    ADMIN_COOKIE,
    ADMIN_MAX_AGE_S,
    Admin,
    AdminDep,
    attempts,
    client_ip,
    require_enabled,
    sign_admin,
    token_matches,
)
from app.api.deps import Session

router = APIRouter()


class SessionIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    # Who is signing in, for the admin log ("Hedi", "S."); free text, never shown to students
    label: str = Field("admin", min_length=1, max_length=32)


class AdminMe(BaseModel):
    actor: str
    via: str  # cookie | token
    expires_at: datetime | None


@router.post("/session", response_model=AdminMe)
async def sign_in(body: SessionIn, request: Request, response: Response, s: Session) -> AdminMe:
    settings = require_enabled()
    if wait := attempts.hit(client_ip(request)):
        raise HTTPException(429, "errors.too_many_attempts", headers={"Retry-After": str(wait)})
    if not token_matches(body.token, settings):
        raise HTTPException(401, "errors.admin_required")
    label = body.label.strip() or "admin"
    response.set_cookie(
        ADMIN_COOKIE,
        sign_admin(label),
        max_age=ADMIN_MAX_AGE_S,
        httponly=True,
        samesite=_samesite(settings),
        secure=settings.session_cookie_secure,
        path="/",
    )
    audit.record(s, Admin(actor=label, via="cookie"), "admin.sign_in")
    await s.commit()
    return AdminMe(
        actor=label,
        via="cookie",
        expires_at=datetime.now(UTC) + timedelta(seconds=ADMIN_MAX_AGE_S),
    )


def _samesite(settings) -> str:
    """strict, except in the cross-site fallback deploy (frontend calling the API's own domain,
    SESSION_COOKIE_SAMESITE=none, DEPLOY.md §5), where a strict cookie would never be sent; there
    CORS_ORIGINS and the X-Admin-Action header still stop cross-site requests."""
    return "none" if settings.SESSION_COOKIE_SAMESITE == "none" else "strict"


@router.delete("/session", status_code=204)
async def sign_out(response: Response, x_admin_action: Annotated[str | None, Header()] = None):
    settings = require_enabled()
    if x_admin_action != "1":  # like every other admin mutation (no cross-site sign-out)
        raise HTTPException(403, "errors.admin_action_header")
    response.delete_cookie(
        ADMIN_COOKIE,
        path="/",
        samesite=_samesite(settings),
        secure=settings.session_cookie_secure,
        httponly=True,
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=AdminMe)
async def me(admin: AdminDep) -> AdminMe:
    return AdminMe(actor=admin.actor, via=admin.via, expires_at=None)
