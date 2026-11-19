"""Job priority inside a lane (Group E, prefetch): `jobs.priority`, lower runs first. A student's
job is P_DEFAULT (100); prefetch of the next chapter is P_NEXT_CHAPTER (50) in the background
lane; a queued prefetch a student joins becomes interactive with P_NEEDED_NOW (10). The queue
index gains the column so the worker's claim stays an index scan.

Existing rows get the default; nothing else changes.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.create_index("ix_jobs_queue_priority", "jobs", ["status", "lane", "priority", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_queue_priority", table_name="jobs")
    op.drop_column("jobs", "priority")
