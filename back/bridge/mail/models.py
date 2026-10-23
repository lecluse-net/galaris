"""Durable reception and delivery journals with their Mail authorization state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MailOutboundDelivery(Base):
    __tablename__ = "mail_outbound_deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_label: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    sender_address: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", server_default=""
    )
    delivery_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="send", server_default="send"
    )
    to_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    cc_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    bcc_addresses: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    subject: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    body: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    html_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_metadata: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    raw_message: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rfc_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ai_disclosure_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="claimed")
    approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_action_authorizations.id", ondelete="RESTRICT"), nullable=True, index=True,
    )
    approver_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Retry deadline; retained after notification until prompt withdrawal completes.
    approval_notification_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
            "connection_id",
            "idempotency_key",
            name="uq_mail_delivery_connection_idempotency",
        ),
        CheckConstraint(
            "status IN ('pending_approval', 'claimed', 'submitting', 'sent', "
            "'rejected', 'uncertain', 'error')",
            name="ck_mail_delivery_status",
        ),
        CheckConstraint(
            "delivery_kind IN ('send', 'reply', 'forward')",
            name="ck_mail_delivery_kind",
        ),
        CheckConstraint(
            "accepted_recipients >= 0 AND rejected_recipients >= 0",
            name="ck_mail_delivery_recipient_counts",
        ),
        Index("ix_mail_delivery_status_updated", "status", "updated_at"),
        Index(
            "ix_mail_delivery_approver_pending",
            "approver_user_id",
            "status",
            "created_at",
        ),
        Index("ix_mail_delivery_agent_created", "agent_id", "created_at"),
    )


class MailInboundReceipt(Base):
    """Header-only receipt; no body is fetched before processing is authorized."""

    __tablename__ = "mail_inbound_receipts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL"), index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    agent_label: Mapped[str] = mapped_column(String(255), default="")
    message_ref: Mapped[str] = mapped_column(String(2048))
    sender_address: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    content: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    known_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatch_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="received")
    authorization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_action_authorizations.id", ondelete="RESTRICT"), index=True
    )
    configuration_fingerprint: Mapped[str | None] = mapped_column(String(64))
    waiting_contexts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("connection_id", "message_ref", name="uq_mail_inbound_connection_ref"),
        CheckConstraint(
            "status IN ('received', 'pending_approval', 'authorized', 'admitted', 'rejected', 'blocked', 'error')",
            name="ck_mail_inbound_status",
        ),
        Index("ix_mail_inbound_agent_created", "agent_id", "created_at"),
    )


__all__ = ["MailOutboundDelivery", "MailInboundReceipt"]
