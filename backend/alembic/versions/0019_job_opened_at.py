"""Prefetch step 8: `jobs.opened_at`, the first time a student was served what a prefetch job
made (or joined it while it was being made). The stats turn it into a hit rate and a time to
content. The serve paths run `UPDATE jobs SET opened_at = now() WHERE share_key = :k AND
opened_at IS NULL AND payload->>'prefetch' = 'true'` on every open; the partial index covers
exactly that predicate, so after the first open the UPDATE finds no row and writes nothing.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNOPENED = "opened_at IS NULL AND (payload ->> 'prefetch') = 'true'"


def upgrade() -> None:
    op.add_column("jobs", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_jobs_prefetch_unopened",
        "jobs",
        ["share_key"],
        postgresql_where=sa.text(UNOPENED),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_prefetch_unopened", table_name="jobs")
    op.drop_column("jobs", "opened_at")
