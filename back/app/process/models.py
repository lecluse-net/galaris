"""Persistent models for business processes and their runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    CheckConstraint,
    BigInteger,
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

from core.database import Base, HistoryMixin
from app.share import Shareable


class ProcessDefinition(Shareable, HistoryMixin, Base):
    __share_kind__ = "process"
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
    code: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    # The old Document FK is a migration source only; native definitions own BPMN.
    bpmn_xml: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    legacy_global_access: Mapped[int] = mapped_column("global_access", Integer, default=0, server_default="0")
    legacy_group_access: Mapped[int] = mapped_column("group_access", Integer, default=0, server_default="0")
    archived: Mapped[bool] = mapped_column(default=False, server_default="false")

    __table_args__ = (
        *Shareable.share_constraints("process_definitions", "process"),
        CheckConstraint("bpmn_xml IS NULL OR (code IS NOT NULL AND document_id IS NULL)", name="ck_process_definition_native_storage"),
        CheckConstraint("agent_id IS NULL OR owner_user_id IS NULL", name="ck_process_definition_exclusive_owner"),
        CheckConstraint("revision > 0 AND lock_version > 0", name="ck_process_definition_versions"),
        CheckConstraint("global_access IN (0,1,2) AND group_access IN (0,1,2)", name="ck_process_definition_access"),
        Index(
            "uq_process_definitions_active_engine_process",
            "tool_id",
            "engine_process_id",
            unique=True,
            postgresql_where=sql_text("deleted_at IS NULL"),
        ),
    )


class ProcessDefinitionGrant(Base):
    __tablename__ = "process_definition_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True)
    can_write: Mapped[bool] = mapped_column(default=False, server_default="false")
    __table_args__ = (
        CheckConstraint("num_nonnulls(agent_id, user_id, team_id) = 1", name="ck_process_definition_grant_principal"),
        UniqueConstraint("process_id", "agent_id"), UniqueConstraint("process_id", "user_id"),
        UniqueConstraint("process_id", "team_id"),
    )


class ProcessDefinitionRevision(Base):
    __tablename__ = "process_definition_revisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id: Mapped[int] = mapped_column(ForeignKey("process_definitions.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    bpmn_xml: Mapped[str] = mapped_column(Text, deferred=True)
    author_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("process_id", "revision"),)


class ProcessRun(HistoryMixin, Base):
    __tablename__ = "process_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("process_definitions.id"), nullable=False, index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    data_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    parent_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    root_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    caller_node_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("process_node_attempts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    launcher_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), nullable=False, index=True
    )
    requester_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
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
    execution_state: Mapped[dict[str, Any]] = mapped_column(
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
        CheckConstraint("jsonb_typeof(data) = 'object' AND data_revision > 0", name="ck_process_run_data"),
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


class ProcessRunFile(HistoryMixin, Base):
    """Run-owned manifest; managed bytes remain in core.storage, external URIs stay external."""

    __tablename__ = "process_run_files"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("process_runs.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    uri: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    origin_uri: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (Index("uq_process_run_files_uri", "run_id", "uri", unique=True,
        postgresql_where=sql_text("deleted_at IS NULL")),)


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


class ProcessNodeRun(Base):
    """One durable occurrence, including branches and loop iterations."""

    __tablename__ = "process_node_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("process_runs.id", ondelete="CASCADE"), index=True)
    node_key: Mapped[str] = mapped_column(String(255))
    occurrence: Mapped[str] = mapped_column(Text)
    admission_order: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(30), default="ready", server_default="ready", index=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sql_text("'{}'::jsonb"))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("uq_process_node_occurrence", "run_id", "occurrence", unique=True),)


class ProcessNodeAttempt(Base):
    __tablename__ = "process_node_attempts"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    node_run_id: Mapped[UUID] = mapped_column(ForeignKey("process_node_runs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="intent", server_default="intent")
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True)
    child_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("process_runs.id", ondelete="RESTRICT"), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sql_text("'{}'::jsonb"))
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("uq_process_node_attempt_number", "node_run_id", "number", unique=True),)
