"""Debugger, phase A: link every call to its job, keep short-lived prompt traces, the worker's
status heartbeat and a timeline of each job's life.

- ai_call_log: job_id + attempt (set by the gateway from the running job), `debug` (replays from
  /admin/debug, kept out of every metric) and `single_flight` (a cache read after waiting on an
  identical request in flight).
- ai_call_trace: messages and reply of one call, written only while the `trace_prompts_until`
  runtime switch is on; capped, redacted, deleted after 24 h by the worker.
- worker_status: one row per worker process, rewritten every ~2 s; worker_heartbeats keeps a
  snapshot every 30 s for 24 h (debug bundles show the worker around the time of a bug).
- jobs.events: append-only list of {t, type, …} written by the worker (claimed, stage, deferred,
  done, failed …). No backfill.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_call_log", sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_call_log", sa.Column("attempt", sa.Integer(), nullable=True))
    op.add_column(
        "ai_call_log",
        sa.Column("debug", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "ai_call_log",
        sa.Column("single_flight", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(op.f("ix_ai_call_log_job_id"), "ai_call_log", ["job_id"])

    op.create_table(
        "ai_call_trace",
        sa.Column("call_log_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("messages", postgresql.JSONB(), nullable=True),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("parsed", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_log_id"],
            ["ai_call_log.id"],
            name=op.f("fk_ai_call_trace_call_log_id_ai_call_log"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("call_log_id", name=op.f("pk_ai_call_trace")),
    )
    op.create_index(op.f("ix_ai_call_trace_created_at"), "ai_call_trace", ["created_at"])

    op.create_table(
        "worker_status",
        sa.Column("worker_id", sa.String(64), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_status")),
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("worker_id", sa.String(64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_index(op.f("ix_worker_heartbeats_ts"), "worker_heartbeats", ["ts"])

    op.add_column(
        "jobs",
        sa.Column(
            "events",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "events")
    op.drop_index(op.f("ix_worker_heartbeats_ts"), table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_table("worker_status")
    op.drop_index(op.f("ix_ai_call_trace_created_at"), table_name="ai_call_trace")
    op.drop_table("ai_call_trace")
    op.drop_index(op.f("ix_ai_call_log_job_id"), table_name="ai_call_log")
    for col in ("single_flight", "debug", "attempt", "job_id"):
        op.drop_column("ai_call_log", col)
