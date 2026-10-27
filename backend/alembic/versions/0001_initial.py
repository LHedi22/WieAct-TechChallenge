"""initial: users, worlds, world_members, jobs, ai_cache, ai_call_log

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("ui_language", sa.String(8), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("nickname", name="uq_users_nickname"),
    )
    op.create_table(
        "worlds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("join_code", sa.String(16), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["users.id"], name="fk_worlds_creator_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_worlds"),
        sa.UniqueConstraint("join_code", name="uq_worlds_join_code"),
    )
    op.create_table(
        "world_members",
        sa.Column("world_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("joined_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["world_id"], ["worlds.id"], name="fk_world_members_world_id_worlds", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_world_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("world_id", "user_id", name="pk_world_members"),
    )
    op.create_index("ix_world_members_user_id", "world_members", ["user_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("world_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(48), nullable=True),
        sa.Column("stages", postgresql.JSONB(), nullable=False),
        sa.Column("not_before", TS, nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("quick_mode", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TS, nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_jobs_user_id_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["world_id"], ["worlds.id"], name="fk_jobs_world_id_worlds", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index("ix_jobs_queue", "jobs", ["status", "lane", "not_before"])
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_world_id", "jobs", ["world_id"])

    op.create_table(
        "ai_cache",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("task_kind", sa.String(32), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("model_tier", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(8), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_ai_cache"),
    )
    op.create_index("ix_ai_cache_task_kind", "ai_cache", ["task_kind"])
    op.create_index("ix_ai_cache_provider", "ai_cache", ["provider"])

    op.create_table(
        "ai_call_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ts", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("task_kind", sa.String(32), nullable=False),
        sa.Column("model_tier", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(8), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("pattern", sa.String(32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("refusal_reason", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ai_call_log"),
    )
    op.create_index("ix_ai_call_log_ts", "ai_call_log", ["ts"])
    op.create_index("ix_ai_call_log_provider", "ai_call_log", ["provider"])


def downgrade() -> None:
    op.drop_table("ai_call_log")
    op.drop_table("ai_cache")
    op.drop_table("jobs")
    op.drop_table("world_members")
    op.drop_table("worlds")
    op.drop_table("users")
