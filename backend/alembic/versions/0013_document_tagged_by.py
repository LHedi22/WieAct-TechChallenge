"""documents.tagged_by: the provider whose model tagged the chunks (concepts, level, language), so
switching to a better provider re-tags documents the mock tagged (rag/refresh.py). Existing rows
stay NULL (unknown) and are re-tagged once a real provider is picked.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("tagged_by", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "tagged_by")
