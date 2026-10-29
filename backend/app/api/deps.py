"""Who is calling. The single seam M3 replaces with cookie sessions (nickname + password).

Until then, outside production: the `X-Dev-User` header names the user (created on first sight,
nickname only), defaulting to `demo`; `X-UI-Language` sets their UI language. Production refuses
every user-bound route until real sign-in exists."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import User

NICKNAME = re.compile(r"^[A-Za-z0-9_\-]{3,32}$")
UI_LANGUAGES = ("en", "fr", "ar", "ar-TN")
UNUSABLE_PASSWORD = "!"  # dev users cannot sign in with a password


async def current_user(
    s: Annotated[AsyncSession, Depends(get_session)],
    x_dev_user: Annotated[str | None, Header()] = None,
    x_ui_language: Annotated[str | None, Header()] = None,
) -> User:
    if get_settings().APP_ENV == "production":
        raise HTTPException(401, "errors.sign_in_required")
    nickname = (x_dev_user or "demo").strip()
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
    if x_ui_language in UI_LANGUAGES and user.ui_language != x_ui_language:
        user.ui_language = x_ui_language
        await s.commit()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
