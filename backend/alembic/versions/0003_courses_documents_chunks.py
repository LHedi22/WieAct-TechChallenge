"""courses, chapters, documents, chunks, quiz_sets

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(col: str, table: str) -> sa.Column:
    return sa.Column(
        col, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=False
    )


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("world_id", "worlds"),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("color_key", sa.String(24), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_courses_world_id", "courses", ["world_id"])

    op.create_table(
        "chapters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("course_id", "courses"),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
    )
    op.create_index("ix_chapters_course_id", "chapters", ["course_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("chapter_id", "chapters"),
        _fk("world_id", "worlds"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(64), nullable=True),
        _created(),
    )
    for col in ("chapter_id", "world_id", "sha256"):
        op.create_index(f"ix_documents_{col}", "documents", [col])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("document_id", "documents"),
        _fk("chapter_id", "chapters"),
        _fk("course_id", "courses"),
        _fk("world_id", "worlds"),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_ref", sa.String(32), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("level", sa.String(12), nullable=True),
        sa.Column("lang", sa.String(8), nullable=True),
        _created(),
    )
    for col in ("document_id", "chapter_id", "world_id"):
        op.create_index(f"ix_chunks_{col}", "chunks", [col])

    op.create_table(
        "quiz_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _fk("world_id", "worlds"),
        _fk("chapter_id", "chapters"),
        sa.Column("level", sa.String(12), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False),
        _created(),
        sa.UniqueConstraint("chapter_id", "level", "language", name="uq_quiz_sets_chapter_id"),
    )


def downgrade() -> None:
    for table in ("quiz_sets", "chunks", "documents", "chapters", "courses"):
        op.drop_table(table)
