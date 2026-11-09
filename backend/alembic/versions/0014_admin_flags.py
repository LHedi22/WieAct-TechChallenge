"""Admin side, phase A: runtime_flags (switches read by the API and the worker without a restart),
admin_actions (one row per admin mutation) and ai_call_log.forced (Quick mode switched on by an
admin, counted apart from real fallbacks so the report stays honest).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_runtime_flags")),
    )
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_actions")),
    )
    op.create_index(op.f("ix_admin_actions_ts"), "admin_actions", ["ts"])
    op.create_index(op.f("ix_admin_actions_action"), "admin_actions", ["action"])
    op.add_column(
        "ai_call_log",
        sa.Column("forced", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("ai_call_log", "forced")
    op.drop_index(op.f("ix_admin_actions_action"), table_name="admin_actions")
    op.drop_index(op.f("ix_admin_actions_ts"), table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_table("runtime_flags")
