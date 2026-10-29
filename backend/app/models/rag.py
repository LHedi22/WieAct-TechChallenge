import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Document(Base):
    """An uploaded file. `progress` / `detail` drive the indexing screen ("slide 18 of 42")."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(8))  # pdf | pptx | docx | txt | image
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    # uploaded | parsing | tagging | embedding | ready | failed
    status: Mapped[str] = mapped_column(String(12), default="uploaded")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"key", "n", "of"}
    page_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(64))  # i18n key
    created_at: Mapped[datetime] = created_at()


class Chunk(Base):
    """Chunk text lives here; Qdrant holds only the vector + filter payload (same UUID)."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_ref: Mapped[str] = mapped_column(String(32))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    level: Mapped[str | None] = mapped_column(String(12))
    lang: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = created_at()


class QuizSet(Base):
    """A shared quiz set: generated once, then free for the whole class. Several sets (seeds) per
    chapter + level + language, so a student who has done one gets a new one."""

    __tablename__ = "quiz_sets"
    __table_args__ = (UniqueConstraint("chapter_id", "level", "language", "seed"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12))
    language: Mapped[str] = mapped_column(String(8))
    seed: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
