"""Durable per-coordinate work; a reply never waits for identity inference."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.database import Base, HistoryMixin


class ContactDiscoveryJob(HistoryMixin, Base):
    __tablename__ = "contact_discovery_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    observation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    coordinate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prepared: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    contact_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("memory_items.id"), nullable=True, index=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("agent_id", "observation_key", name="uq_contact_discovery_observation"),
        CheckConstraint("status IN ('pending','running','retry','success','ignored','unresolved','error')",
                        name="ck_contact_discovery_status"),
        CheckConstraint("attempts >= 0", name="ck_contact_discovery_attempts"),
        Index("ix_contact_discovery_queue", "status", "available_at"),
    )
