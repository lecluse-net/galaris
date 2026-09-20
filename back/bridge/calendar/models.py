"""Durable configuration and idempotency receipts for iCalendar feeds."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class CalendarFeed(HistoryMixin, Base):
    __tablename__ = "calendar_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    access_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="read", server_default="read"
    )
    url_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    username_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    trigger_on_start: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    trigger_on_alarm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    action_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="task", server_default="task"
    )
    process_workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    cached_ical_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        CheckConstraint("access_mode IN ('read', 'write')", name="ck_calendar_feed_access_mode"),
        CheckConstraint("action_kind IN ('task', 'process')", name="ck_calendar_feed_action_kind"),
        CheckConstraint(
            "action_kind != 'process' OR process_workflow_id IS NOT NULL",
            name="ck_calendar_feed_process_target",
        ),
        Index("ix_calendar_feeds_due", "active", "last_checked_at"),
    )


class CalendarTrigger(Base):
    __tablename__ = "calendar_triggers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_feeds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    event_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    process_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dispatch_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("calendar_id", "fingerprint", name="uq_calendar_trigger_fingerprint"),
        CheckConstraint("trigger_kind IN ('start', 'alarm')", name="ck_calendar_trigger_kind"),
        CheckConstraint("status IN ('pending', 'success', 'error')", name="ck_calendar_trigger_status"),
        Index("ix_calendar_triggers_calendar_created", "calendar_id", "created_at"),
    )


__all__ = ["CalendarFeed", "CalendarTrigger"]
