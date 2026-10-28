"""jobs: payload, provider, started_at · ai_call_log: lane, request_hash

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.alter_column("jobs", "payload", server_default=None)
    op.add_column("jobs", sa.Column("provider", sa.String(8), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_call_log", sa.Column("lane", sa.String(16), nullable=True))
    op.add_column("ai_call_log", sa.Column("request_hash", sa.String(64), nullable=True))
    op.create_index("ix_ai_call_log_request_hash", "ai_call_log", ["request_hash"])


def downgrade() -> None:
    op.drop_index("ix_ai_call_log_request_hash", table_name="ai_call_log")
    op.drop_column("ai_call_log", "request_hash")
    op.drop_column("ai_call_log", "lane")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "provider")
    op.drop_column("jobs", "payload")
