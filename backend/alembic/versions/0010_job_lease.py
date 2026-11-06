"""jobs.lease_until + jobs.worker_id: a running job's lease, renewed by the worker that runs it;
expired leases are failed and refunded by the sweep (audit F-RES-1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("worker_id", sa.String(64), nullable=True))
    op.create_index("ix_jobs_lease", "jobs", ["status", "lease_until"])


def downgrade() -> None:
    op.drop_index("ix_jobs_lease", table_name="jobs")
    op.drop_column("jobs", "worker_id")
    op.drop_column("jobs", "lease_until")
