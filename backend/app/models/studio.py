import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class StudyAsset(Base):
    """Shared study material for one chapter + level + language, generated once for the class:
    kind notes | map | audio_script (the study pack's flashcards are rows in `flashcards`)."""

    __tablename__ = "study_assets"
    __table_args__ = (UniqueConstraint("chapter_id", "level", "language", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12))
    language: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class Flashcard(Base):
    """A card. Deck cards come with a study pack and are shared (user_id NULL, asset_id = the
    pack's notes); quiz cards are personal, made from a student's missed questions."""

    __tablename__ = "flashcards"
    __table_args__ = (Index("ix_flashcards_chapter_user", "chapter_id", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("study_assets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    concept: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(8))  # deck | quiz
    ref: Mapped[str | None] = mapped_column(String(64))  # quiz: "{attempt}:{question}"
    created_at: Mapped[datetime] = created_at()


class FlashcardReview(Base):
    """One student's spaced-repetition state for one card (see features/studio/srs.py)."""

    __tablename__ = "flashcard_reviews"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flashcards.id", ondelete="CASCADE"), primary_key=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_s: Mapped[int] = mapped_column(Integer, default=0)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassPoolLedger(Base):
    """The Class Pool: coins members gave so shared study material can be generated for everyone.
    kind contribute | spend | refund; the balance is the sum of a world's rows."""

    __tablename__ = "class_pool_ledger"
    __table_args__ = (
        Index(
            "uq_class_pool_refund",
            "ref",
            unique=True,
            postgresql_where=text("kind = 'refund'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10))
    delta: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(64), index=True)  # job id for spend/refund
    created_at: Mapped[datetime] = created_at()
