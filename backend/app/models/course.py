import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class Course(Base):
    """One island on the world map."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = uuid_pk()
    world_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worlds.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    color_key: Mapped[str] = mapped_column(String(24))  # a design token name (accent colour)
    exam_date: Mapped[date | None] = mapped_column(Date)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[uuid.UUID] = uuid_pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
