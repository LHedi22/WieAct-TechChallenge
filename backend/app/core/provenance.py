"""Who made a piece of shared class content (audit F-OFF-1).

quiz_sets, placement_sets, study_assets and wisdom_tips record the provider whose model wrote them.
In production only platform-made (`cloud`) rows are served, online or offline: content from the
mock or local Ollama must never pass for platform output. Rows from before provenance existed
(NULL) are not served in production either. In development everything is served, and the API
reports `made_by` so the UI can label test data."""

from __future__ import annotations

from sqlalchemy import ColumnElement, true

from app.core.config import get_settings

PLATFORM = "cloud"


def servable(column) -> ColumnElement[bool]:
    """WHERE clause for reads of shared content."""
    return column == PLATFORM if get_settings().APP_ENV == "production" else true()


def replaces(existing_provider, new_provider) -> ColumnElement[bool]:
    """ON CONFLICT … WHERE: a platform-made row replaces a non-platform one under the same key;
    test content never overwrites platform content."""
    return existing_provider.is_distinct_from(PLATFORM) & (new_provider == PLATFORM)
