import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class CoinLedger(Base):
    """Every coin change is a row (docs/ECONOMY.md); balances are sums, never a mutable column.
    bucket: free | earned | purchased | pass.
    kind: daily | earned | purchased | spend | refund | pass.
    `day` is the Tunis day the row counts for: free coins only count on their own day, and a refund
    keeps the day of the spend it reverses."""

    __tablename__ = "coin_ledger"
    __table_args__ = (
        Index("ix_coin_ledger_user_day", "user_id", "day"),
        Index(
            "uq_coin_ledger_daily",
            "user_id",
            "day",
            unique=True,
            postgresql_where=text("kind = 'daily'"),
        ),
        Index(
            "uq_coin_ledger_refund",
            "ref",
            "bucket",
            unique=True,
            postgresql_where=text("kind = 'refund'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    bucket: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10))
    delta: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(64), index=True)  # job id, answer id, product
    created_at: Mapped[datetime] = created_at()


class PointsLedger(Base):
    """Points earned for learning (never bought). One row per reason + ref, so awards are
    idempotent; leaderboards and streaks are computed from here."""

    __tablename__ = "points_ledger"
    __table_args__ = (
        Index("uq_points_ledger_award", "user_id", "reason", "ref", unique=True),
        Index("ix_points_ledger_world_ts", "world_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    world_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()
