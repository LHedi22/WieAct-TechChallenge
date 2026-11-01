"""study_assets · flashcards · flashcard_reviews · class_pool_ledger

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(col: str, table: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column(
        col, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable
    )


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "study_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("world_id", "worlds"),
        _fk("chapter_id", "chapters"),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        _created(),
        sa.UniqueConstraint(
            "chapter_id", "level", "language", "kind", name="uq_study_assets_chapter_id"
        ),
    )
    op.create_table(
        "flashcards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("chapter_id", "chapters"),
        _fk("asset_id", "study_assets", nullable=True),
        _fk("user_id", "users", nullable=True),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("concept", sa.String(80)),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("ref", sa.String(64)),
        _created(),
    )
    op.create_index("ix_flashcards_asset_id", "flashcards", ["asset_id"])
    op.create_index("ix_flashcards_chapter_user", "flashcards", ["chapter_id", "user_id"])
    op.create_table(
        "flashcard_reviews",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "card_id",
            sa.Uuid(),
            sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "class_pool_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("world_id", "worlds"),
        _fk("user_id", "users", nullable=True, ondelete="SET NULL"),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(64)),
        _created(),
    )
    op.create_index("ix_class_pool_ledger_world_id", "class_pool_ledger", ["world_id"])
    op.create_index("ix_class_pool_ledger_ref", "class_pool_ledger", ["ref"])
    op.create_index(
        "uq_class_pool_refund",
        "class_pool_ledger",
        ["ref"],
        unique=True,
        postgresql_where=sa.text("kind = 'refund'"),
    )


def downgrade() -> None:
    op.drop_table("class_pool_ledger")
    op.drop_table("flashcard_reviews")
    op.drop_table("flashcards")
    op.drop_table("study_assets")
