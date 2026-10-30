"""daily_state · wisdom_tips

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "daily_state",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("challenges", postgresql.JSONB(), nullable=False),
        sa.Column("plan", postgresql.JSONB()),
        sa.Column("planned_by", sa.String(8), nullable=False),
        sa.Column("plan_job_id", sa.Uuid()),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        _created(),
    )
    op.create_table(
        "wisdom_tips",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "world_id", sa.Uuid(), sa.ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "course_id", sa.Uuid(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chapter_id", sa.Uuid(), sa.ForeignKey("chapters.id", ondelete="SET NULL")),
        sa.Column("concept", sa.String(80), nullable=False),
        sa.Column("mistake_type", sa.String(16), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("text", postgresql.JSONB(), nullable=False),
        sa.Column("student_count", sa.Integer(), nullable=False),
        _created(),
        sa.UniqueConstraint(
            "world_id", "concept", "mistake_type", "language", name="uq_wisdom_tips_world_id"
        ),
    )
    op.create_index("ix_wisdom_tips_world_id", "wisdom_tips", ["world_id"])


def downgrade() -> None:
    op.drop_table("wisdom_tips")
    op.drop_table("daily_state")
