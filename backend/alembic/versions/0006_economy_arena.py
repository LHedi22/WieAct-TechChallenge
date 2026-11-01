"""coin_ledger · points_ledger · peer_questions · peer_answers · peer_votes

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(col: str, table: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        col, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=nullable
    )


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "coin_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("user_id", "users"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("bucket", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(64)),
        _created(),
    )
    op.create_index("ix_coin_ledger_ref", "coin_ledger", ["ref"])
    op.create_index("ix_coin_ledger_user_day", "coin_ledger", ["user_id", "day"])
    op.create_index(
        "uq_coin_ledger_daily",
        "coin_ledger",
        ["user_id", "day"],
        unique=True,
        postgresql_where=sa.text("kind = 'daily'"),
    )
    op.create_index(
        "uq_coin_ledger_refund",
        "coin_ledger",
        ["ref", "bucket"],
        unique=True,
        postgresql_where=sa.text("kind = 'refund'"),
    )

    op.create_table(
        "points_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("user_id", "users"),
        _fk("world_id", "worlds", nullable=True),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        _created(),
    )
    op.create_index("ix_points_ledger_world_ts", "points_ledger", ["world_id", "created_at"])
    op.create_index(
        "uq_points_ledger_award", "points_ledger", ["user_id", "reason", "ref"], unique=True
    )

    op.create_table(
        "peer_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("world_id", "worlds"),
        _fk("chapter_id", "chapters"),
        _fk("author_id", "users"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reject_reason", sa.String(16)),
        # FK added below: the two tables reference each other
        sa.Column("pinned_answer_id", sa.Uuid()),
        _created(),
    )
    op.create_index("ix_peer_questions_chapter_id", "peer_questions", ["chapter_id"])

    op.create_table(
        "peer_answers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("question_id", "peer_questions"),
        _fk("author_id", "users"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("ai_score", sa.Integer()),
        sa.Column("ai_confidence", sa.String(8)),
        sa.Column("ai_feedback", postgresql.JSONB()),
        sa.Column("reviewed_by_mid", sa.Boolean(), nullable=False),
        sa.Column("rewarded", sa.Boolean(), nullable=False),
        _created(),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("question_id", "author_id", name="uq_peer_answers_question_id"),
    )
    op.create_index("ix_peer_answers_question_id", "peer_answers", ["question_id"])
    op.create_foreign_key(
        "fk_peer_questions_pinned_answer_id_peer_answers",
        "peer_questions",
        "peer_answers",
        ["pinned_answer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "peer_votes",
        sa.Column("answer_id", sa.Uuid(), sa.ForeignKey("peer_answers.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.PrimaryKeyConstraint("answer_id", "user_id", name="pk_peer_votes"),
    )


def downgrade() -> None:
    op.drop_table("peer_votes")
    op.drop_constraint(
        "fk_peer_questions_pinned_answer_id_peer_answers", "peer_questions", type_="foreignkey"
    )
    op.drop_table("peer_answers")
    op.drop_table("peer_questions")
    op.drop_table("points_ledger")
    op.drop_table("coin_ledger")
