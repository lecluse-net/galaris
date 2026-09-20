"""Durable receipts for crash-safe Dream maintenance."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.database import Base


class DreamReceipt(Base):
    """Witness that one mechanism considered one durable subject."""

    __tablename__ = "dream_receipts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    mechanism_key: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", server_default="running"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, unique=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prepared_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    result_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "mechanism_key",
            "subject_kind",
            "subject_id",
            name="uq_dream_receipt_subject",
        ),
        CheckConstraint(
            "status IN ('running', 'retry', 'success', 'error')",
            name="ck_dream_receipt_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND result_count >= 0",
            name="ck_dream_receipt_counts",
        ),
        Index(
            "ix_dream_receipt_claim",
            "mechanism_key",
            "status",
            "available_at",
        ),
    )


__all__ = ["DreamReceipt"]
