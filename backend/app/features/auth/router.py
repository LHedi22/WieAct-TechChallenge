"""Sign up / sign in with a nickname and a password — nothing else (no e-mail, no real name)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import NICKNAME, CurrentUser, OptionalUser, Session
from app.core.config import get_settings
from app.core.security import (
    COOKIE_NAME,
    MIN_PASSWORD,
    SESSION_MAX_AGE_S,
    hash_password,
    sign_session,
    verify_password,
)
from app.models import Profile, User, WorldMember

router = APIRouter(prefix="/api/auth", tags=["auth"])

Language = Literal["en", "fr", "ar", "ar-TN"]


class SignupIn(BaseModel):
    nickname: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=200)
    ui_language: Language = "en"


class LoginIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


class MeIn(BaseModel):
    ui_language: Language


class Me(BaseModel):
    id: uuid.UUID
    nickname: str
    ui_language: str
    onboarded: bool
    avatar: dict | None
    has_worlds: bool


def _set_cookie(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        sign_session(user.id),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        secure=s.SESSION_COOKIE_SECURE,
        samesite=s.SESSION_COOKIE_SAMESITE,
        path="/",
    )


async def _me(s, user: User) -> Me:
    profile = await s.get(Profile, user.id)
    worlds = await s.scalar(
        select(func.count()).select_from(WorldMember).where(WorldMember.user_id == user.id)
    )
    return Me(
        id=user.id,
        nickname=user.nickname,
        ui_language=user.ui_language,
        onboarded=bool(profile and profile.onboarded_at),
        avatar=profile.avatar if profile else None,
        has_worlds=bool(worlds),
    )


@router.post("/signup", response_model=Me, status_code=201)
async def signup(body: SignupIn, response: Response, s: Session) -> Me:
    nickname = body.nickname.strip()
    if not NICKNAME.match(nickname):
        raise HTTPException(400, "errors.nickname_invalid")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(400, "errors.password_short")
    user = User(
        nickname=nickname,
        password_hash=hash_password(body.password),
        ui_language=body.ui_language,
    )
    s.add(user)
    try:
        await s.commit()
    except IntegrityError as e:
        raise HTTPException(409, "errors.nickname_taken") from e
    _set_cookie(response, user)
    return await _me(s, user)


@router.post("/login", response_model=Me)
async def login(body: LoginIn, response: Response, s: Session) -> Me:
    user = await s.scalar(select(User).where(User.nickname == body.nickname.strip()))
    # Same answer for an unknown nickname and a wrong password (no account probing).
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "errors.login_failed")
    _set_cookie(response, user)
    return await _me(s, user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> Response:
    s = get_settings()
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=s.SESSION_COOKIE_SECURE, samesite=s.SESSION_COOKIE_SAMESITE
    )
    response.status_code = 204
    return response


@router.get("/me", response_model=Me)
async def me(s: Session, user: OptionalUser) -> Me:
    if user is None:
        raise HTTPException(401, "errors.sign_in_required")
    return await _me(s, user)


@router.patch("/me", response_model=Me)
async def update_me(body: MeIn, s: Session, user: CurrentUser) -> Me:
    user.ui_language = body.ui_language
    await s.commit()
    return await _me(s, user)
