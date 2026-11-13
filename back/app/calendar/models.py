"""Local calendar aggregates, indexed projections and durable delivery journals."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base, HistoryMixin


class CalendarFeed(HistoryMixin, Base):
    __tablename__ = "calendar_feeds"
    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    owner_label: Mapped[str | None] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(16), default="ical", server_default="ical")
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Paris", server_default="Europe/Paris")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    writable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    actions_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    url_encrypted: Mapped[str | None] = mapped_column(Text)
    source_root_encrypted: Mapped[str | None] = mapped_column(Text)
    username_encrypted: Mapped[str | None] = mapped_column(Text)
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    sync_token_encrypted: Mapped[str | None] = mapped_column(Text)
    remote_etag: Mapped[str | None] = mapped_column(String(500))
    source_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    initialized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sync_requested: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        CheckConstraint("source_kind IN ('internal', 'ical', 'caldav')", name="ck_calendar_feed_source_kind"),
        Index("uq_calendar_default_connection", "connection_id", unique=True,
              postgresql_where=text("is_default AND deleted_at IS NULL")),
        Index("ix_calendar_feeds_due", "active", "sync_requested", "last_synced_at"),
    )


class CalendarEvent(HistoryMixin, Base):
    """Master VEVENT; sensitive text and provider paths remain encrypted."""
    __tablename__ = "calendar_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("calendar_feeds.id"), index=True)
    uid: Mapped[str] = mapped_column(String(255))
    content_encrypted: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_actions: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    actions_planned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    remote_href_encrypted: Mapped[str | None] = mapped_column(Text)
    remote_href_hash: Mapped[str | None] = mapped_column(String(64))
    remote_etag: Mapped[str | None] = mapped_column(String(500))
    synced_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    remote_content_encrypted: Mapped[str | None] = mapped_column(Text)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    parent_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    __table_args__ = (
        UniqueConstraint("calendar_id", "uid", name="uq_calendar_event_uid"),
        UniqueConstraint("calendar_id", "remote_href_hash", name="uq_calendar_event_remote_href"),
        CheckConstraint("revision > 0 AND synced_revision >= 0", name="ck_calendar_event_revision"),
        Index("ix_calendar_events_recurring", "calendar_id",
              postgresql_where=text("recurring AND deleted_at IS NULL")),
    )


class CalendarEventException(Base):
    __tablename__ = "calendar_event_exceptions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    recurrence_key: Mapped[str] = mapped_column(String(100))
    content_encrypted: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("event_id", "recurrence_key", name="uq_calendar_exception"),)


class CalendarOccurrence(Base):
    """Disposable SQL projection. Single appointments have one permanent row."""
    __tablename__ = "calendar_occurrences"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("calendar_feeds.id"), index=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    recurrence_key: Mapped[str] = mapped_column(String(100))
    event_revision: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    transparent: Mapped[bool] = mapped_column(Boolean)
    cancelled: Mapped[bool] = mapped_column(Boolean)
    payload_encrypted: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("event_id", "recurrence_key", name="uq_calendar_occurrence"),
        Index("ix_calendar_occurrences_window", "calendar_id", "start_at", "end_at"),
    )


class CalendarProjectionWindow(Base):
    """Coverage of disposable recurrence projections, independent of execution."""
    __tablename__ = "calendar_projection_windows"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    event_revision: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("event_id", "event_revision", "start_at", "end_at", name="uq_calendar_projection_window"),
                     Index("ix_calendar_projection_expiry", "built_at", "event_id"))


class CalendarAction(HistoryMixin, Base):
    __tablename__ = "calendar_actions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    recurrence_key: Mapped[str | None] = mapped_column(String(100))
    anchor: Mapped[str] = mapped_column(String(8), default="start", server_default="start")
    offset_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    instructions_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_lateness_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    __table_args__ = (
        CheckConstraint("anchor IN ('start', 'end')", name="ck_calendar_action_anchor"),
        CheckConstraint("max_lateness_minutes >= 0", name="ck_calendar_action_lateness"),
    )


class CalendarSyncOperation(Base):
    """Transactional outbox. UUID identifies an operation across retries."""
    __tablename__ = "calendar_sync_operations"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("calendar_feeds.id"), index=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    deleting: Mapped[bool] = mapped_column(Boolean)
    content_encrypted: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("event_id", "revision", name="uq_calendar_sync_revision"),
        CheckConstraint("state IN ('pending', 'success', 'conflict', 'error')", name="ck_calendar_sync_state"),
        Index("ix_calendar_sync_pending", "calendar_id", "created_at",
              postgresql_where=text("(state)::text = ANY ((ARRAY['pending'::character varying, 'error'::character varying])::text[])")),
    )


class CalendarSyncRun(Base):
    """Durable evidence for reads and writes, including interrupted sync attempts."""
    __tablename__ = "calendar_sync_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("calendar_feeds.id"), index=True)
    source_revision: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(40), default="claim")
    state: Mapped[str] = mapped_column(String(16), default="running")
    error_category: Mapped[str | None] = mapped_column(String(100))
    operation_id: Mapped[UUID | None] = mapped_column(ForeignKey("calendar_sync_operations.id"))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_location: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_calendar_sync_runs_recent", "calendar_id", "started_at"),)


class CalendarEventRevision(Base):
    __tablename__ = "calendar_event_revisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content_encrypted: Mapped[str] = mapped_column(Text)
    deleting: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("event_id", "revision", name="uq_calendar_event_revision"),)


class CalendarTrigger(Base):
    """One durable launch of an action for one original occurrence identity."""
    __tablename__ = "calendar_triggers"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("calendar_feeds.id"), index=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_events.id"), index=True)
    recurrence_key: Mapped[str] = mapped_column(String(100))
    action_key: Mapped[str] = mapped_column(String(100))
    action_revision: Mapped[int | None] = mapped_column(Integer)
    launch_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    event_revision: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    trigger_kind: Mapped[str] = mapped_column(String(16), default="alarm", server_default="alarm")
    event_uid: Mapped[str] = mapped_column(String(255))
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_lateness_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="scheduled", server_default="scheduled")
    error_message: Mapped[str | None] = mapped_column(String(500))
    dispatch_encrypted: Mapped[str] = mapped_column(Text)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("calendar_id", "fingerprint", name="uq_calendar_trigger_fingerprint"),
        UniqueConstraint("event_id", "recurrence_key", "action_key", "launch_number", name="uq_calendar_action_launch"),
        CheckConstraint("status IN ('scheduled', 'pending', 'submitted', 'error', 'cancelled', 'skipped')", name="ck_calendar_trigger_status"),
        Index("ix_calendar_triggers_due", "occurrence_at",
              postgresql_where=text("(status)::text = ANY ((ARRAY['scheduled'::character varying, 'pending'::character varying, 'error'::character varying])::text[])")),
        Index("ix_calendar_triggers_calendar_created", "calendar_id", "created_at"),
    )
