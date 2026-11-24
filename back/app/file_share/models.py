"""Private resource identities, retained independently of source availability."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint, Index, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.elements import ColumnElement

from app.memory import MemoryURL, folded_lexical_sql

from core.database import Base, Vector


class ResourceIndexContent(Base):
    """A disposable analysis shared by compatible observations of identical content."""

    __tablename__ = "resource_index_contents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_key: Mapped[str] = mapped_column(String(64), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    analysis_version: Mapped[int] = mapped_column(Integer, server_default="1")
    generated_summary: Mapped[str] = mapped_column(Text, default="")
    generated_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    embedding_model_key: Mapped[str | None] = mapped_column(String(64))
    suggested_topic_id: Mapped[UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    document_kind: Mapped[str | None] = mapped_column(String(16))
    contact_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    order_key: Mapped[str | None] = mapped_column(String(64), index=True)
    order_role: Mapped[str | None] = mapped_column(String(16))
    order_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ResourceIndexSource(Base):
    """One current index pointer per source; the owning domain controls access."""

    __tablename__ = "resource_index_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_key: Mapped[UUID] = mapped_column()
    uri: Mapped[str] = mapped_column(Text, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    content_id: Mapped[UUID] = mapped_column(ForeignKey("resource_index_contents.id"), index=True)
    topic_id: Mapped[UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), index=True)

    __table_args__ = (UniqueConstraint("source_kind", "source_key"),)


class ResourceIndexPassage(Base):
    __tablename__ = "resource_index_passages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_id: Mapped[UUID] = mapped_column(ForeignKey("resource_index_contents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column()
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True))
    search_vector_folded: Mapped[str] = mapped_column(TSVECTOR, Computed(
        f"to_tsvector('simple'::regconfig, {folded_lexical_sql('text')})", persisted=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector())

    __table_args__ = (
        UniqueConstraint("content_id", "position"),
        Index("ix_resource_index_passages_search", "search_vector", postgresql_using="gin"),
        Index("ix_resource_index_passages_search_folded", "search_vector_folded", postgresql_using="gin"),
    )


class ResourceIndexLink(Base):
    """A typed, evidence-backed relation between current source observations."""

    __tablename__ = "resource_index_links"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("resource_index_sources.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[UUID] = mapped_column(ForeignKey("resource_index_sources.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(16))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation"),
        CheckConstraint("source_id <> target_id", name="ck_resource_index_link_distinct"),
        CheckConstraint("state IN ('proposed', 'confirmed')", name="ck_resource_index_link_state"),
    )


class ManagedFileOwner(Base):
    """Private standalone uploads; attachments instead inherit their domain ACL."""

    __tablename__ = "file_owners"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id"), unique=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)


class FileOperationMemo(Base):
    """Bounded disposable receipts; never a resource or an authorization grant."""

    __tablename__ = "file_operation_memos"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("agent_id", "key", name="uq_file_operation_memo"),)


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
    memory_url_id: Mapped[UUID | None] = mapped_column(ForeignKey("memory_urls.id", ondelete="SET NULL"), index=True)
    memory_url: Mapped[MemoryURL | None] = relationship(lazy="selectin")
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    fingerprint_version: Mapped[str | None] = mapped_column(String(64))

    @hybrid_property
    def memory_node_id(self) -> UUID | None:
        """Derived through the URL relation; never a second persisted association."""
        return self.memory_url.memory_node_id if self.memory_url is not None else None

    @memory_node_id.inplace.expression
    @classmethod
    def _memory_node_expression(cls) -> ColumnElement[UUID | None]:
        return cast(ColumnElement[UUID | None], select(MemoryURL.memory_node_id).where(
            MemoryURL.id == cls.memory_url_id,
        ).correlate(cls).scalar_subquery())

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
