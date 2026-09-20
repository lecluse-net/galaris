"""Persistent occurrences, traces, and grouped failure patterns."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class FailurePattern(Base):
    """Reviewable aggregate for occurrences sharing a stable fingerprint."""

    __tablename__ = "failure_patterns"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    fingerprint_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="new", server_default="new", index=True
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    remediation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    fixed_by_commit: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=""
    )
    regression_test: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_failure_patterns_review_queue", "status", "last_seen_at"),
    )


class FailureIncident(Base):
    """Immutable identity and queryable summary of one failed attempt."""

    __tablename__ = "failure_incidents"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    pattern_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("failure_patterns.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    causal_incident_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("failure_incidents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(300), nullable=False, unique=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    phase: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    error_type: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    will_retry: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    llm_call_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("llm_calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_round_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    process_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_uuid: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    driver_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    provider_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    model_code: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    tool_call_external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_failure_incidents_queue", "kind", "occurred_at"),
        Index("ix_failure_incidents_component", "tool_name", "provider_code"),
    )


class FailureIncidentTrace(Base):
    """Large sanitized trace kept separately from the review queue."""

    __tablename__ = "failure_incident_traces"
    __table_args__ = (
        UniqueConstraint("incident_id", name="uq_failure_incident_trace"),
    )

    incident_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("failure_incidents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default="galaris.failure-trace/v1"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    redacted_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    truncated_fields: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["FailureIncident", "FailureIncidentTrace", "FailurePattern"]
