"""peer_answers.status widened for "pending_review" (low-confidence grades wait for a check)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("peer_answers", "status", type_=sa.String(16), existing_type=sa.String(10))


def downgrade() -> None:
    op.execute("UPDATE peer_answers SET status = 'graded' WHERE status = 'pending_review'")
    op.alter_column("peer_answers", "status", type_=sa.String(10), existing_type=sa.String(16))
