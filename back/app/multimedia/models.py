"""Provider output receipts awaiting transfer to their canonical file provider."""

from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func, text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MediaGeneration(Base):
    """Private durable media generation."""

    __tablename__ = "multimedia_generations"
    __table_args__ = (UniqueConstraint("agent_id", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(320))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sql_text("'{}'::jsonb"))
    dispatch: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sql_text("'{}'::jsonb"))
    authority: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sql_text("'{}'::jsonb"))
    authorization_settled: Mapped[bool] = mapped_column(default=False, server_default=sql_text("false"))
    callback_token: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MediaOutputReceipt(Base):
    __tablename__ = "multimedia_output_receipts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(ForeignKey("multimedia_generations.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int]
    external_id: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    # Private, bounded delivery outbox, never advertised as a file or logged.
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    delivery_started: Mapped[bool] = mapped_column(default=False)
    uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    delivery_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("generation_id", "ordinal"),)


class MediaDeliveryResolution(Base):
    """Operator evidence for one uncertain file delivery, never for regeneration."""

    __tablename__ = "multimedia_delivery_resolutions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("multimedia_output_receipts.id", ondelete="CASCADE"))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attempt_number: Mapped[int]
    decision: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str] = mapped_column(String(4000))
    uri: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("receipt_id", "attempt_number"),)
