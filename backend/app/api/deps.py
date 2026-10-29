"""Who is calling: the signed session cookie (sign-up / sign-in, app/features/auth).

Outside production only, tests and dev scripts may instead send `X-Dev-User: <nickname>` (created
on first sight, nickname only). `X-UI-Language` updates the user's UI language."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import COOKIE_NAME, read_session
from app.models import User

NICKNAME = re.compile(r"^[A-Za-z0-9_\-]{3,32}$")
UI_LANGUAGES = ("en", "fr", "ar", "ar-TN")
UNUSABLE_PASSWORD = "!"  # dev users cannot sign in with a password


async def _dev_user(s: AsyncSession, nickname: str) -> User:
    nickname = nickname.strip()
    if not NICKNAME.match(nickname):
        raise HTTPException(400, "errors.nickname_invalid")
    user = await s.scalar(select(User).where(User.nickname == nickname))
    if user is None:
        user = User(nickname=nickname, password_hash=UNUSABLE_PASSWORD, ui_language="en")
        s.add(user)
        try:
            await s.commit()
        except IntegrityError:  # created by a parallel request
            await s.rollback()
            user = await s.scalar(select(User).where(User.nickname == nickname))
    return user


async def optional_user(
    s: Annotated[AsyncSession, Depends(get_session)],
    lw_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
    x_ui_language: Annotated[str | None, Header()] = None,
) -> User | None:
    user: User | None = None
    if (user_id := read_session(lw_session)) is not None:
        user = await s.get(User, user_id)
    elif x_dev_user and get_settings().APP_ENV != "production":
        user = await _dev_user(s, x_dev_user)
    if user is not None and x_ui_language in UI_LANGUAGES and user.ui_language != x_ui_language:
        user.ui_language = x_ui_language
        await s.commit()
    return user


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(401, "errors.sign_in_required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
