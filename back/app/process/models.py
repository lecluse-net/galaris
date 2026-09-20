"""Persistent models for business processes and their runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class ProcessDefinition(HistoryMixin, Base):
    __tablename__ = "process_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_process_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_process_definitions_active_engine_process",
            "tool_id",
            "engine_process_id",
            unique=True,
            postgresql_where=sql_text("deleted_at IS NULL"),
        ),
    )


class ProcessRun(HistoryMixin, Base):
    __tablename__ = "process_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("process_definitions.id"), nullable=False, index=True
    )
    launcher_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    await_task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    launch_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    engine_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    engine_run_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    callback_token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued", index=True
    )
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    output: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    engine_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    raw_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    analysis: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    await_resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_process_runs_engine_execution",
            "engine_code",
            "engine_run_id",
            unique=True,
            postgresql_where=sql_text("engine_run_id IS NOT NULL"),
        ),
        Index(
            "uq_process_runs_explicit_idempotency",
            "launcher_agent_id",
            "process_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sql_text("idempotency_key IS NOT NULL"),
        ),
    )


class ProcessRunEvent(Base):
    __tablename__ = "process_run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("uq_process_run_events_event", "run_id", "event_id", unique=True),
    )


class ProcessStartJob(Base):
    __tablename__ = "process_start_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_runs.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
