"""Durable models for governed agent memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base, HistoryMixin
from core.util import ContentProfile

from .vector import Vector
from .document_types import DocumentType


class DocumentTag(HistoryMixin, Base):
    """A human's private document classification, independent of document ownership."""

    __tablename__ = "document_tags"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_tags.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    memory_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_items.id"), nullable=True, unique=True,
    )
    # Automatic personal classification identity; names and placement stay editable.
    goal_id: Mapped[UUID | None] = mapped_column(ForeignKey("goals.id"), index=True)
    system_role: Mapped[str | None] = mapped_column(String(30))
    generated_name: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        Index("uq_document_tags_user_goal", "user_id", "goal_id", unique=True,
              postgresql_where=sql_text("deleted_at IS NULL AND goal_id IS NOT NULL")),
        Index("uq_document_tags_user_goals_root", "user_id", unique=True,
              postgresql_where=sql_text("deleted_at IS NULL AND system_role = 'goals_root'")),
    )


class DocumentTagIcon(HistoryMixin, Base):
    """Uploaded icons in one human's private, reusable palette."""

    __tablename__ = "document_tag_icons"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    data: Mapped[str] = mapped_column(Text)


class DocumentTagAssignment(Base):
    __tablename__ = "document_tag_assignments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("document_tags.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (UniqueConstraint("tag_id", "document_id"),)


class DocumentIcon(Base):
    """Personal document appearance shared by all UI projections for one user."""

    __tablename__ = "document_icons"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    icon: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("user_id", "document_id"),)


class DocumentAppGrant(HistoryMixin, Base):
    """Human consent, outside generated content and scoped to an exact document revision."""

    __tablename__ = "document_app_grants"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    app_key: Mapped[str] = mapped_column(String(40))
    alias: Mapped[str] = mapped_column(String(40))
    document_revision: Mapped[int] = mapped_column(Integer)
    access: Mapped[str | None] = mapped_column(String(5))
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", "app_key", "alias"),
        CheckConstraint("access IS NULL OR access IN ('read', 'write')"),
    )


class DocumentAppWriteBudget(Base):
    """Transactional write budget shared by all apps for a reader and Dataset."""

    __tablename__ = "document_app_write_budgets"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    writes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_written: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "dataset_id"),)


class DocumentListPosition(Base):
    """Personal list order, independent of folder placement and document content."""

    __tablename__ = "document_list_positions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (UniqueConstraint("user_id", "document_id"),)


class DocumentAttachment(Base):
    """One durable attachment identity and its exclusive textual Memory companion.

    The document attachment manifest remains authoritative for membership. Retained
    attachments keep their identity and description but are absent from live recall.
    """

    __tablename__ = "document_attachments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), index=True)
    memory_item_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id"), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class MemoryItem(HistoryMixin, Base):
    """Stable logical memory whose payload lives in a resource provider."""

    __tablename__ = "memory_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # This date tracks meaningful memory content changes, unlike the generic
    # audit timestamp inherited by other models. Services set it explicitly
    # when payload or keywords change.
    updated_at: Mapped[datetime | None] = mapped_column(  # pyright: ignore[reportIncompatibleVariableOverride]
        DateTime(timezone=True), nullable=True
    )
    # For documents this is the visible content revision; metadata and ACL
    # writes remain concurrency-safe through the separate ORM lock_version.
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    owner_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    topic_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    provider_code: Mapped[str] = mapped_column(
        String(80), nullable=False, default="native", server_default="native", index=True
    )
    resource_id: Mapped[str] = mapped_column(String(1_024), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    memory_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="semantic", server_default="semantic", index=True
    )
    node_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="memory", server_default="memory", index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        String(30), nullable=False, default="html", server_default="html", index=True
    )
    content_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="text", server_default="text", index=True
    )
    media_type: Mapped[str] = mapped_column(
        String(255), nullable=False, default="text/markdown", server_default="text/markdown"
    )
    content_profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private", index=True
    )
    global_access: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    group_access: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    read_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    deletion_protected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    source_managed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    managed_source_kind: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    managed_source_ref: Mapped[str | None] = mapped_column(
        String(1_024), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    semantic_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default="", index=True
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('simple'::regconfig, "
            "coalesce(keywords::text, '')), 'B') || "
            "setweight(to_tsvector('simple'::regconfig, coalesce(search_text, '')), 'C')",
            persisted=True,
        ),
        nullable=False,
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    access_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        Computed(
            "GREATEST("
            "COALESCE(last_accessed_at, created_at), "
            "COALESCE(updated_at, created_at)"
            ")",
            persisted=True,
        ),
        nullable=False,
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    old_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    old_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)

    @property
    def content_profile(self) -> ContentProfile:
        return "document" if self.node_kind == "document" and not self.deletion_protected else "rich-text"

    revisions: Mapped[list["MemoryRevision"]] = relationship(
        "MemoryRevision",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MemoryRevision.revision",
    )
    grants: Mapped[list["MemoryItemGrant"]] = relationship(
        "MemoryItemGrant", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('core', 'working', 'episodic', 'semantic', 'procedural', 'social')",
            name="ck_memory_items_type",
        ),
        CheckConstraint(
            "document_type IN ('html', 'dataset') AND "
            "(document_type != 'dataset' OR (node_kind = 'document' AND "
            "content_type = 'text' AND media_type = 'application/json' AND "
            "content_profile_version IS NULL)) AND "
            "(node_kind != 'document' OR document_type != 'html' OR media_type LIKE 'text/%')",
            name="ck_memory_items_document_type",
        ),
        CheckConstraint(
            "node_kind IN ('memory', 'document', 'attachment', 'folder')",
            name="ck_memory_items_node_kind",
        ),
        CheckConstraint(
            "node_kind != 'document' OR "
            "(memory_type = 'working' AND content_type = 'text' "
            "AND source_managed = false AND read_only = false "
            "AND visibility != 'public')",
            name="ck_memory_items_document",
        ),
        CheckConstraint(
            "visibility IN ('private', 'shared', 'public')",
            name="ck_memory_items_visibility",
        ),
        CheckConstraint(
            "group_access IN (0, 1, 2) AND (group_access = 0 OR "
            "(node_kind = 'document' AND global_access = 0 AND visibility = 'shared'))",
            name="ck_memory_items_group_access",
        ),
        CheckConstraint(
            "global_access IN (0, 1, 2)",
            name="ck_memory_items_global_access",
        ),
        CheckConstraint(
            "global_access = 0 OR visibility = 'shared'",
            name="ck_memory_items_global_access_visibility",
        ),
        CheckConstraint(
            "topic_id IS NULL OR (source_managed = true "
            "AND managed_source_kind = 'topic' "
            "AND managed_source_ref = 'topic:' || topic_id::text "
            "AND visibility = 'public' AND owner_agent_id IS NULL "
            "AND owner_user_id IS NULL)",
            name="ck_memory_items_topic_projection",
        ),
        CheckConstraint(
            "owner_agent_id IS NULL OR owner_user_id IS NULL",
            name="ck_memory_items_exclusive_owner",
        ),
        CheckConstraint(
            "owner_user_id IS NULL OR "
            "(node_kind = 'document' AND source_managed = false) OR "
            "(node_kind IN ('attachment', 'folder') AND source_managed = true)",
            name="ck_memory_items_user_owner",
        ),
        CheckConstraint(
            "(node_kind IN ('attachment', 'folder') AND source_managed = true "
            "AND managed_source_kind = node_kind AND managed_source_ref IS NOT NULL "
            "AND read_only = true AND (owner_agent_id IS NOT NULL OR owner_user_id IS NOT NULL)) OR "
            "(source_managed = false AND node_kind IN ('memory', 'document') AND managed_source_kind IS NULL "
            "AND managed_source_ref IS NULL "
            "AND ((node_kind = 'document' AND "
            "(owner_agent_id IS NOT NULL OR owner_user_id IS NOT NULL)) "
            "OR (node_kind != 'document' AND owner_agent_id IS NOT NULL))) OR "
            "(source_managed = true AND managed_source_kind IS NOT NULL "
            "AND managed_source_ref IS NOT NULL AND read_only = true "
            "AND owner_user_id IS NULL "
            "AND ((visibility = 'private' AND owner_agent_id IS NOT NULL) "
            "OR (visibility = 'public' AND owner_agent_id IS NULL)))",
            name="ck_memory_items_managed_source",
        ),
        UniqueConstraint(
            "managed_source_kind",
            "managed_source_ref",
            name="uq_memory_items_managed_source",
        ),
        Index("ix_memory_items_owner_hash", "owner_agent_id", "content_hash"),
        Index("ix_memory_items_user_owner_hash", "owner_user_id", "content_hash"),
        Index("ix_memory_items_activity", "activity_at"),
        Index(
            "ix_memory_items_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
    )
    __mapper_args__ = {"version_id_col": lock_version}


class MemoryItemGrant(Base):
    """Item-level read/write permission for one agent."""

    __tablename__ = "memory_item_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    can_write: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint("item_id", "agent_id", name="uq_memory_item_agent"),
    )


class DocumentUserGrant(Base):
    """Direct human access to a memory resource, independent of managed Agents."""

    __tablename__ = "document_user_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (UniqueConstraint("item_id", "user_id"),)


class DocumentTeamGrant(Base):
    """Live access for a team's current human and Agent members."""

    __tablename__ = "document_team_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("memory_items.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (UniqueConstraint("item_id", "team_id"),)


class MemoryRevision(Base):
    """Immutable metadata and resource pointer for one item revision."""

    __tablename__ = "memory_revisions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(1_024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    document_content_version: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    document_append: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    author_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    item: Mapped[MemoryItem] = relationship("MemoryItem", back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("item_id", "revision", name="uq_memory_item_revision"),
    )


class MemoryLink(HistoryMixin, Base):
    """Explicit or suggested typed edge in the knowledge graph."""

    __tablename__ = "memory_links"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    suggested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    created_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    projection_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    projection_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )

    __table_args__ = (
        CheckConstraint("source_item_id <> target_item_id", name="ck_memory_links_not_self"),
        CheckConstraint(
            "(projection_key IS NULL AND projection_version IS NULL) OR "
            "(projection_key IS NOT NULL AND projection_version > 0)",
            name="ck_memory_links_projection_identity",
        ),
        UniqueConstraint(
            "source_item_id",
            "target_item_id",
            "relation_type",
            name="uq_memory_link_edge",
        ),
    )


class MemoryContextNode(Base):
    """Private structural node that is never part of memory retrieval."""

    __tablename__ = "memory_context_nodes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context_kind: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=""
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
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

    __table_args__ = (
        CheckConstraint(
            "context_kind IN ('conversation')",
            name="ck_memory_context_nodes_kind",
        ),
        UniqueConstraint(
            "owner_agent_id",
            "context_kind",
            "context_key",
            name="uq_memory_context_node_key",
        ),
    )


class MemoryContextEdge(Base):
    """Association between a structural context and a recallable memory item."""

    __tablename__ = "memory_context_edges"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    context_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_context_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(
        String(80), nullable=False, default="contains", server_default="contains"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "context_node_id",
            "item_id",
            "relation_type",
            name="uq_memory_context_edge",
        ),
    )


class MemoryContactItem(Base):
    """Authoritative ownership of one conversational memory by one contact."""

    __tablename__ = "memory_contact_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(1_024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "contact_item_id <> item_id",
            name="ck_memory_contact_item_distinct",
        ),
        UniqueConstraint("item_id", name="uq_memory_contact_item_memory"),
    )


class MemoryContactIdentity(Base):
    """One durable address resolving to a canonical contact Memory item."""

    __tablename__ = "memory_contact_identities"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    namespace: Mapped[str] = mapped_column(String(512), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    galaris_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
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

    __table_args__ = (
        CheckConstraint(
            "identity_kind IN ('messenger', 'galaris_user')",
            name="ck_memory_contact_identity_kind",
        ),
        CheckConstraint(
            "(identity_kind = 'galaris_user' AND namespace = 'galaris' "
            "AND galaris_user_id IS NOT NULL) OR "
            "(identity_kind = 'messenger' AND galaris_user_id IS NULL)",
            name="ck_memory_contact_identity_shape",
        ),
        UniqueConstraint(
            "owner_agent_id",
            "identity_kind",
            "namespace",
            "external_id",
            name="uq_memory_contact_identity_address",
        ),
        Index(
            "uq_memory_contact_identity_galaris_user",
            "owner_agent_id",
            "galaris_user_id",
            unique=True,
            postgresql_where=sql_text("galaris_user_id IS NOT NULL"),
        ),
    )


class MemoryTopicContactScope(Base):
    """Authoritative private scope for one agent, public Topic, and human contact."""

    __tablename__ = "memory_topic_contact_scopes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "topic_item_id <> contact_item_id",
            name="ck_memory_topic_contact_scope_distinct",
        ),
        UniqueConstraint(
            "owner_agent_id",
            "topic_item_id",
            "contact_item_id",
            name="uq_memory_topic_contact_scope",
        ),
    )


class MemoryTopicContactItem(Base):
    """Membership of one governed memory in an exact Topic/contact scope."""

    __tablename__ = "memory_topic_contact_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    scope_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_topic_contact_scopes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(1_024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "scope_id", "item_id", name="uq_memory_topic_contact_item"
        ),
        UniqueConstraint(
            "item_id",
            "source_kind",
            "source_ref",
            name="uq_memory_topic_contact_source",
        ),
    )


class MemorySource(Base):
    """Provenance edge linking a memory to one canonical observed source.

    The typed foreign keys make Task and conversation-round provenance genuine
    many-to-many relations.  ``source_kind``/``source_ref`` remain the
    stable, extensible identity for source kinds that do not own a canonical
    table and for detailed evidence such as one Task outcome fingerprint.
    """

    __tablename__ = "memory_sources"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    conversation_round_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(1_024), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "item_id", "source_kind", "source_ref", name="uq_memory_item_source"
        ),
    )


class MemoryAcquisition(HistoryMixin, Base):
    """Internal idempotency and audit record for one autonomous acquisition."""

    __tablename__ = "memory_candidates"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False, default="create", server_default="create", index=True
    )
    target_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(1_024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        "reviewed_at", DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[int | None] = mapped_column(
        "reviewed_by", ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('create', 'update', 'link', 'contradict', 'skip')",
            name="ck_memory_candidates_action",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'merged')",
            name="ck_memory_candidates_status",
        ),
    )


class MemoryUsage(Base):
    """Auditable retrieval or explicit-read association."""

    __tablename__ = "memory_usages"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    access_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "item_id", "agent_id", "task_id", "access_kind", name="uq_memory_usage_task_item"
        ),
    )


class MemoryAssociation(Base):
    """Legacy symmetric co-usage scores retained but ignored by recall."""

    __tablename__ = "memory_associations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    item_a_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_b_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    observations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("item_a_id <> item_b_id", name="ck_memory_associations_not_self"),
        UniqueConstraint("item_a_id", "item_b_id", name="uq_memory_association_pair"),
    )


class MemoryEmbeddingManifest(Base):
    """Atomically published completeness declaration for a vector generation."""

    __tablename__ = "memory_embedding_manifests"

    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), primary_key=True,
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("chunk_count > 0 AND dimensions > 0", name="ck_memory_embedding_manifest_shape"),
        CheckConstraint("indexed_word_count >= 0 AND source_word_count >= indexed_word_count", name="ck_memory_embedding_manifest_coverage"),
    )


class MemoryEmbeddingChunk(Base):
    """Rebuildable vector projection of one current memory payload chunk."""

    __tablename__ = "memory_embedding_chunks"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model_code: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "dimensions > 0",
            name="ck_memory_embedding_chunks_dimensions",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_memory_embedding_chunks_index",
        ),
        UniqueConstraint(
            "item_id",
            "source_fingerprint",
            "model_key",
            "chunk_index",
            name="uq_memory_embedding_chunk_projection",
        ),
        Index(
            "ix_memory_embedding_chunks_current",
            "model_key",
            "dimensions",
            "source_fingerprint",
            "item_id",
        ),
    )


class MemoryFinding(Base):
    """Durable deterministic maintenance finding awaiting an optional action."""

    __tablename__ = "memory_findings"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    primary_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    primary_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    related_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('duplicate', 'contradiction', 'aging')",
            name="ck_memory_findings_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'applied', 'dismissed', 'obsolete', 'error')",
            name="ck_memory_findings_status",
        ),
        CheckConstraint(
            "(kind = 'aging' AND related_item_id IS NULL AND related_revision IS NULL) OR "
            "(kind IN ('duplicate', 'contradiction') AND related_item_id IS NOT NULL "
            "AND related_revision IS NOT NULL)",
            name="ck_memory_findings_pair",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_memory_findings_score",
        ),
        CheckConstraint(
            "threshold >= 0 AND threshold <= 36500",
            name="ck_memory_findings_threshold",
        ),
        Index("ix_memory_findings_item_status", "primary_item_id", "status"),
        Index("ix_memory_findings_related_status", "related_item_id", "status"),
    )


class MemoryAutomationJob(Base):
    """Durable idempotent work item for post-task capture and maintenance."""

    __tablename__ = "memory_automation_jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'error')",
            name="ck_memory_automation_jobs_status",
        ),
    )
