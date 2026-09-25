"""Disposable, content-addressed index; source files remain authoritative."""

from datetime import datetime

from sqlalchemy import BigInteger, Computed, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, Vector


class DocumentationPassage(Base):
    __tablename__ = "documentation_passages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("setweight(to_tsvector('simple'::regconfig, title), 'A') || "
                 "setweight(to_tsvector('simple'::regconfig, content), 'B') || "
                 "to_tsvector('french'::regconfig, title || ' ' || content) || "
                 "to_tsvector('english'::regconfig, title || ' ' || content)", persisted=True),
    )
    model_key: Mapped[str | None] = mapped_column(String(64))
    dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_documentation_passages_search", "search_vector", postgresql_using="gin"),
        Index("ix_documentation_passages_model", "model_key", "dimensions"),
    )
