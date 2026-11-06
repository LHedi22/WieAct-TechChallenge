"""provider on shared class content (quiz_sets, placement_sets, study_assets, wisdom_tips): who made
it, so production serves platform-made content only (audit F-OFF-1). Existing rows stay NULL
(unknown) and are not served in production.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("quiz_sets", "placement_sets", "study_assets", "wisdom_tips")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("provider", sa.String(8), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "provider")
