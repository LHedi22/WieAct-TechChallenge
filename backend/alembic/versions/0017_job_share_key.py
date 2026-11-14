"""Shared class jobs (audit OPT-01): `jobs.share_key` names the class asset a job makes
(study pack, audio episode, quiz set, placement set). A partial unique index allows only one
queued or running job per key, so classmates who start the same asset at the same moment join
one job instead of each creating (and paying for) their own, even across API processes.

No backfill: older jobs keep a NULL key and never conflict.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("share_key", sa.String(200), nullable=True))
    op.create_index(
        "uq_jobs_share_key_active",
        "jobs",
        ["share_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running') AND share_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_share_key_active", table_name="jobs")
    op.drop_column("jobs", "share_key")
