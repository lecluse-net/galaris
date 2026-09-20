"""Global thematic dossiers used to organize tasks and durable memory."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, String, Text, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class Topic(HistoryMixin, Base):
    """One public, instance-wide thematic dossier."""

    __tablename__ = "topics"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    memory_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    __mapper_args__ = {"version_id_col": revision}


__all__ = ["Topic"]
