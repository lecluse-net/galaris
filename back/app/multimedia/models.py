"""Provider output receipts awaiting transfer to their canonical file provider."""

from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MediaOutputReceipt(Base):
    __tablename__ = "multimedia_output_receipts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("process_runs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int]
    external_id: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    # Private, bounded delivery outbox, never advertised as a file or logged.
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    delivery_started: Mapped[bool] = mapped_column(default=False)
    uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    delivery_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)


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
