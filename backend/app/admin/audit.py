"""admin_actions writer: one row per admin mutation, added to the caller's session so it commits
(or rolls back) with the change itself."""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.auth import Admin
from app.models import AdminAction


def record(
    s: AsyncSession,
    admin: Admin,
    action: str,
    *,
    target_kind: str | None = None,
    target_id: object | None = None,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
) -> AdminAction:
    row = AdminAction(
        actor=admin.actor,
        action=action,
        target_kind=target_kind,
        target_id=None if target_id is None else str(target_id),
        before=jsonable_encoder(before),
        after=jsonable_encoder(after),
        reason=(reason or "").strip() or None,
    )
    s.add(row)
    return row
