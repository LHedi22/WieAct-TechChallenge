"""Admin side, phase C: economy_overrides (live values merged over app/core/economy.py) and
`edited_by_admin` on every table of generated content an admin can edit.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EDITABLE = ("quiz_sets", "study_assets", "wisdom_tips", "placement_sets", "flashcards")


def upgrade() -> None:
    op.create_table(
        "economy_overrides",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_economy_overrides")),
    )
    for table in EDITABLE:
        op.add_column(
            table,
            sa.Column("edited_by_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        )


def downgrade() -> None:
    for table in EDITABLE:
        op.drop_column(table, "edited_by_admin")
    op.drop_table("economy_overrides")
