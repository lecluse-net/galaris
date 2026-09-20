"""Private persistence models owned by Chat."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ChatEmojiUsage(Base):
    """Per-user frequency counter for one emoji selected in Chat."""

    __tablename__ = "chat_emoji_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    emoji: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "emoji",
            name="uq_chat_emoji_usage_user_emoji",
        ),
        CheckConstraint(
            "usage_count > 0",
            name="ck_chat_emoji_usage_positive_count",
        ),
    )


class ChatPushSubscription(Base):
    """One browser/PWA Web Push capability bound to a Galaris user."""

    __tablename__ = "chat_push_subscriptions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    endpoint_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    auth_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expiration_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ChatPushDelivery(Base):
    """Durable, idempotent delivery of one message to one Push subscription."""

    __tablename__ = "chat_push_deliveries"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_push_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "message_id",
            name="uq_chat_push_delivery_subscription_message",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'cancelled', 'failed')",
            name="ck_chat_push_delivery_status",
        ),
    )


__all__ = ["ChatEmojiUsage", "ChatPushDelivery", "ChatPushSubscription"]
