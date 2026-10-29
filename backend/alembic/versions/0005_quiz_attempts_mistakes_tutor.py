"""quiz_sets.seed · quiz_attempts · mistakes · tutor_sessions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(col: str, table: str, *, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column(
        col,
        sa.Uuid(),
        sa.ForeignKey(f"{table}.id", ondelete=ondelete),
        nullable=ondelete == "SET NULL",
    )


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.add_column("quiz_sets", sa.Column("seed", sa.Integer(), server_default="1", nullable=False))
    op.drop_constraint("uq_quiz_sets_chapter_id", "quiz_sets", type_="unique")
    op.create_unique_constraint(
        "uq_quiz_sets_chapter_id", "quiz_sets", ["chapter_id", "level", "language", "seed"]
    )

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("user_id", "users"),
        _fk("quiz_set_id", "quiz_sets"),
        _fk("world_id", "worlds"),
        _fk("course_id", "courses"),
        _fk("chapter_id", "chapters"),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("current", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("second_tries", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        _created(),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_quiz_attempts_user_id", "quiz_attempts", ["user_id"])
    op.create_index("ix_quiz_attempts_quiz_set_id", "quiz_attempts", ["quiz_set_id"])

    op.create_table(
        "mistakes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("user_id", "users"),
        _fk("world_id", "worlds"),
        _fk("chapter_id", "chapters"),
        _fk("attempt_id", "quiz_attempts", ondelete="SET NULL"),
        sa.Column("question_idx", sa.Integer(), nullable=True),
        sa.Column("concept", sa.String(80), nullable=False),
        sa.Column("mistake_type", sa.String(16), nullable=False),
        _created(),
    )
    op.create_index("ix_mistakes_user_id", "mistakes", ["user_id"])
    op.create_index("ix_mistakes_pattern", "mistakes", ["world_id", "concept", "mistake_type"])

    op.create_table(
        "tutor_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("user_id", "users"),
        _fk("world_id", "worlds"),
        _fk("course_id", "courses"),
        _fk("chapter_id", "chapters"),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("ideas", postgresql.JSONB(), nullable=False),
        sa.Column("hints_used", sa.Integer(), nullable=False),
        sa.Column("stuck_count", sa.Integer(), nullable=False),
        sa.Column("escalate_next", sa.Boolean(), nullable=False),
        sa.Column("turns", postgresql.JSONB(), nullable=False),
        sa.Column("pending_job_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        _created(),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tutor_sessions_user_id", "tutor_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_table("tutor_sessions")
    op.drop_table("mistakes")
    op.drop_table("quiz_attempts")
    op.drop_constraint("uq_quiz_sets_chapter_id", "quiz_sets", type_="unique")
    op.create_unique_constraint(
        "uq_quiz_sets_chapter_id", "quiz_sets", ["chapter_id", "level", "language"]
    )
    op.drop_column("quiz_sets", "seed")
