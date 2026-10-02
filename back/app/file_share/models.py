"""Private resource identities, retained independently of source availability."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class FileCatalogEntry(Base):
    __tablename__ = "file_catalog_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"), index=True)
    binding_stamp: Mapped[str] = mapped_column(String(64))
    runtime: Mapped[str] = mapped_column(String(32))
    uri: Mapped[str] = mapped_column(Text)
    uri_key: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    descriptor: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    enrichment_version: Mapped[str | None] = mapped_column(String(64))
    source_version: Mapped[str | None] = mapped_column(String(64))
    enrichment_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_text: Mapped[str] = mapped_column(Text, default="")
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    operation_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    memory_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("memory_items.id"), unique=True)

    __table_args__ = (Index(
        "ix_file_catalog_tombstone_binding", "connection_id", "binding_stamp", "runtime",
        "operation_started_at", postgresql_where=present.is_(False),
    ), UniqueConstraint(
        "connection_id", "binding_stamp", "runtime", "uri_key", name="uq_file_catalog_binding_uri",
    ),)


class FileIndexRun(Base):
    """Bounded traversal with a durable frontier and explicit coverage."""
    __tablename__ = "file_index_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"), index=True)
    binding_stamp: Mapped[str] = mapped_column(String(64))
    runtime: Mapped[str] = mapped_column(String(32), default="internal")
    root_uri: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    frontier: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    directories: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_entries: Mapped[int] = mapped_column(Integer, default=100000)
    max_depth: Mapped[int] = mapped_column(Integer, default=64)
    error_type: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'retry', 'success', 'partial', 'error', 'excluded', 'cancelled')", name="ck_file_index_run_status"),
        CheckConstraint("max_entries BETWEEN 1 AND 1000000 AND max_depth BETWEEN 0 AND 64 AND scanned >= 0 AND attempts >= 0", name="ck_file_index_run_budget"),
    )


class FileObservationRepair(Base):
    """Persist source evidence before projection, never replay external effects."""
    __tablename__ = "file_observation_repairs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"), index=True)
    binding_stamp: Mapped[str] = mapped_column(String(64))
    runtime: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error_type: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'success', 'error', 'excluded')", name="ck_file_observation_repair_status"),
    )
