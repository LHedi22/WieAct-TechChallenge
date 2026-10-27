import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class User(Base):
    """Anonymous by design: a nickname and a password hash, nothing else identifying."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    nickname: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    ui_language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = created_at()
