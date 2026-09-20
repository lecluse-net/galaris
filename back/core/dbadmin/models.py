"""Technical, append-oriented DbAdmin journal models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DbAdminRun(Base):
    """One synchronization attempt; intentionally not historized or soft-deleted."""

    __tablename__ = "dbadmin_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    target_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DbAdminIssueRecord(Base):
    """Bounded error details attached to a DbAdmin run."""

    __tablename__ = "dbadmin_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("dbadmin_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    object_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fatal: Mapped[bool] = mapped_column(nullable=False, default=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_dbadmin_issues_run_fatal", "run_id", "fatal"),)


class DbAdminActionRecord(Base):
    """Latest durable state of one developer-owned idempotent action."""

    __tablename__ = "dbadmin_actions"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DbAdminActionRevision(Base):
    """Immutable criticality of each action implementation admitted to execution.

    A separate journal table can be bootstrapped even when upgrading an older
    journal, before Atlas expands application tables.
    """

    __tablename__ = "dbadmin_action_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_key: Mapped[str] = mapped_column(
        ForeignKey("dbadmin_actions.key", ondelete="CASCADE"), nullable=False
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(nullable=False)
    __table_args__ = (UniqueConstraint("action_key", "checksum"),)
