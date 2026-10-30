import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class PeerQuestion(Base):
    """A question asked in a chapter's Teach-Back peer room. status: pending (moderation job) |
    open | rejected."""

    __tablename__ = "peer_questions"

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    reject_reason: Mapped[str | None] = mapped_column(String(16))
    pinned_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("peer_answers.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = created_at()


class PeerAnswer(Base):
    """A classmate's explanation, AI-scored (draft-then-revise). One per student per question;
    "Improve my answer" rewrites it in place and grades it again. status: grading | graded |
    rejected."""

    __tablename__ = "peer_answers"
    __table_args__ = (UniqueConstraint("question_id", "author_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("peer_questions.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="grading")
    ai_score: Mapped[int | None] = mapped_column(Integer)
    ai_confidence: Mapped[str | None] = mapped_column(String(8))
    # {errors: [{quote, fix}], good, missing: [str], quick_mode}
    ai_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_by_mid: Mapped[bool] = mapped_column(Boolean, default=False)
    rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PeerVote(Base):
    """A "helpful" vote: one per student per answer."""

    __tablename__ = "peer_votes"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("peer_answers.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
