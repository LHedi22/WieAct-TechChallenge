"""First-payer refund: `asset_opens` counts the distinct classmates served a class asset a student
paid for (one row per job and student); at FIRST_PAYER_REFUND_OPENS the payer gets one
`share_back` ledger row (unique per job id). `ix_jobs_paid_share` finds the paying job from the
serve paths without scanning every job of the share key.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAID = "status = 'done' AND cost > 0 AND user_id IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "asset_opens",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "uq_coin_ledger_share_back",
        "coin_ledger",
        ["ref"],
        unique=True,
        postgresql_where=sa.text("kind = 'share_back'"),
    )
    op.create_index("ix_jobs_paid_share", "jobs", ["share_key"], postgresql_where=sa.text(PAID))


def downgrade() -> None:
    op.drop_index("ix_jobs_paid_share", table_name="jobs")
    op.drop_index("uq_coin_ledger_share_back", table_name="coin_ledger")
    op.drop_table("asset_opens")
