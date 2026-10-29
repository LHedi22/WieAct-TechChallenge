"""profiles, course_levels, chapter_mastery, placement_sets, presence

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(col: str, table: str, *, pk: bool = False, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column(
        col,
        sa.Uuid(),
        sa.ForeignKey(f"{table}.id", ondelete=ondelete),
        primary_key=pk,
        nullable=ondelete == "SET NULL",
    )


def upgrade() -> None:
    op.create_table(
        "profiles",
        _fk("user_id", "users", pk=True),
        sa.Column("university", sa.String(80), nullable=True),
        sa.Column("field", sa.String(80), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("style_visual", sa.Integer(), nullable=False),
        sa.Column("style_practice", sa.Integer(), nullable=False),
        sa.Column("style_listening", sa.Integer(), nullable=False),
        sa.Column("style_teaching", sa.Integer(), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String(8)), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=True),
        sa.Column("reminder_time", sa.Time(), nullable=True),
        sa.Column("goal", sa.String(16), nullable=True),
        sa.Column("leaderboard_opt_in", sa.Boolean(), nullable=False),
        sa.Column("avatar", postgresql.JSONB(), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "course_levels",
        _fk("user_id", "users", pk=True),
        _fk("course_id", "courses", pk=True),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("goal", sa.String(16), nullable=True),
    )
    op.create_table(
        "chapter_mastery",
        _fk("user_id", "users", pk=True),
        _fk("chapter_id", "chapters", pk=True),
        sa.Column("mastery", sa.Integer(), nullable=False),
        sa.Column("weak", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "placement_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("course_id", "courses"),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("course_id", "language", name="uq_placement_sets_course_id"),
    )
    op.create_table(
        "presence",
        _fk("user_id", "users", pk=True),
        _fk("course_id", "courses", pk=True),
        _fk("chapter_id", "chapters", ondelete="SET NULL"),
        sa.Column(
            "seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_presence_seen_at", "presence", ["seen_at"])


def downgrade() -> None:
    op.drop_index("ix_presence_seen_at", table_name="presence")
    for table in ("presence", "placement_sets", "chapter_mastery", "course_levels", "profiles"):
        op.drop_table(table)
