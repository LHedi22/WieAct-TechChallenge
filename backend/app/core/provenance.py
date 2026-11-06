"""Who made a piece of shared class content (audit F-OFF-1).

quiz_sets, placement_sets, study_assets and wisdom_tips record the provider whose model wrote them.
Providers rank cloud > local > mock > unknown (NULL), and the active one
(`provider_choice.target()`) decides what is served:

- production: only platform-made (`cloud`) rows, online or offline: content from the mock or local
  Ollama must never pass for platform output;
- development: rows from the active provider or a better one. Picking Local or Cloud in the UI
  hides the mock's placeholder quizzes, notes and tips, and the next request writes them again
  with the picked models. With the mock active (tests), everything is served.

A row is replaced under its unique key only by a better-ranked provider, so a real model's copy
replaces a test one and test content never overwrites platform content. The API reports `made_by`
so the UI can label test data."""

from __future__ import annotations

from sqlalchemy import ColumnElement, case, or_, true

from app.core import provider_choice
from app.core.provider_choice import RANK

PLATFORM = "cloud"


def _rank(column) -> ColumnElement[int]:
    return case(
        *((column == name, rank) for name, rank in RANK.items() if name is not None),
        else_=RANK[None],
    )


def servable(column) -> ColumnElement[bool]:
    """WHERE clause for reads of shared content."""
    floor = RANK.get(provider_choice.target(), RANK[None])
    if floor <= RANK["mock"]:
        return true()
    names = [name for name, rank in RANK.items() if name is not None and rank >= floor]
    return or_(*(column == name for name in names))


def replaces(existing_provider, new_provider) -> ColumnElement[bool]:
    """ON CONFLICT … WHERE: a better-ranked provider's row replaces the stored one."""
    return _rank(new_provider) > _rank(existing_provider)
