"""Editorial documents, shared summaries, provenance and personal classification."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    literal,
    String,
    Text,
    UniqueConstraint,
    func,
    case,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, column_property, synonym
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.elements import ColumnElement

from core.database import Base, HistoryMixin
from app.share import Shareable, ShareReference, ShareGrant
from core.util import ContentProfile

from .document_types import DocumentType


class DocumentSharingIntent(Base):
    """Authoritative own ACL; common sharing tables are the effective projection."""

    __tablename__ = "document_sharing_intents"
    share_id: Mapped[UUID] = mapped_column(ForeignKey("share_configs.id", ondelete="CASCADE"), primary_key=True)
    global_access: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    group_access: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    grants: Mapped[list[dict[str, int | bool | str]]] = mapped_column(JSONB, default=list, server_default="[]")
    __table_args__ = (CheckConstraint("global_access IN (0,1,2) AND group_access IN (0,1,2)", name="ck_document_sharing_intents_access"),)

class DocumentTag(Shareable, HistoryMixin, Base):
    __share_kind__ = "document"
    """A human's private document classification, independent of document ownership."""

    __tablename__ = "document_tags"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_tags.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    grants: Mapped[list[ShareGrant]] = relationship(
        ShareGrant,
        primaryjoin="and_(DocumentTag.share_id == foreign(ShareGrant.share_id), ShareGrant.agent_id.is_not(None))",
        viewonly=True,
    )
    memory_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True, unique=True,
    )

    __table_args__ = (
        *ShareReference.share_constraints("document_tags", "document"),
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
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (UniqueConstraint("tag_id", "document_id"),)

class DocumentNesting(Base):
    """One user's document hierarchy; ownership and grants remain independent."""

    __tablename__ = "document_nesting"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    parent_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (
        UniqueConstraint("user_id", "document_id"),
        CheckConstraint("document_id <> parent_document_id", name="ck_document_nesting_not_self"),
        Index("ix_document_nesting_user_parent", "user_id", "parent_document_id"),
    )

class DocumentIcon(Base):
    """Personal document appearance shared by all UI projections for one user."""

    __tablename__ = "document_icons"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    icon: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("user_id", "document_id"),)

class DocumentAppGrant(HistoryMixin, Base):
    """Human consent, outside generated content and scoped to an exact document revision."""

    __tablename__ = "document_app_grants"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
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
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    writes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_written: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "dataset_id"),)

class DocumentListPosition(Base):
    """Personal list order, independent of folder placement and document content."""

    __tablename__ = "document_list_positions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    at_root: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (UniqueConstraint("user_id", "document_id"),)

class DocumentAttachment(Base):
    """One durable attachment identity and its textual Memory companion.

    The document attachment manifest remains authoritative for membership. Retained
    attachments keep their identity and description but are absent from live recall.
    """

    __tablename__ = "document_attachments"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    memory_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("memory_items.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

class Document(Shareable, HistoryMixin, Base):
    __share_kind__ = "document"
    """Authoritative editorial content, policy and shared summary; no required Memory row."""

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id: Mapped[UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(1_024), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    storage_kind: Mapped[str] = mapped_column(String(10), default="text", server_default="text")
    creation_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    creation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    stored_document_type: Mapped[str] = mapped_column("document_type", String(30), nullable=False, default="text", server_default="text")
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, default="text", server_default="text")
    media_type: Mapped[str] = mapped_column(String(255), nullable=False, default="text/html", server_default="text/html")
    content_profile_version: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str | None] = mapped_column(String(500))
    # UUID of a disposable WebP file in the document thumbnail cache.
    thumbnail_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private", server_default="private")
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


    owner_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    deletion_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    temporal: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    search_vector: Mapped[str] = mapped_column(TSVECTOR, Computed(
        "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
        "setweight(to_tsvector('simple'::regconfig, coalesce(keywords::text, '')), 'B') || "
        "setweight(to_tsvector('simple'::regconfig, coalesce(search_text, '')), 'C')", persisted=True))
    node_kind: Mapped[str] = column_property(literal("document"))
    source_managed: Mapped[bool] = column_property(literal(False))
    managed_source_kind: Mapped[str | None] = column_property(literal(None, String))
    managed_source_ref: Mapped[str | None] = column_property(literal(None, String))
    old_at: Mapped[datetime | None] = column_property(literal(None, DateTime(timezone=True)))
    old_reason: Mapped[str | None] = column_property(literal(None, String))
    summary_provider_code: Mapped[str] = mapped_column(String(80), default="native", server_default="native")
    summary_resource_id: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    summary_content: Mapped[str | None] = mapped_column(Text, default="", server_default="")
    summary_media_type: Mapped[str] = mapped_column(String(50), default="text/html", server_default="text/html")
    summary_content_hash: Mapped[str] = mapped_column(String(64), default="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", server_default="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    summary_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    summary_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    summary_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    summary_source_text: Mapped[str | None] = mapped_column(Text)
    revisions: Mapped[list[DocumentRevision]] = relationship(back_populates="document", foreign_keys="DocumentRevision.document_id", cascade="all, delete-orphan", passive_deletes=True, order_by="DocumentRevision.revision")
    grants: Mapped[list[ShareGrant]] = relationship(ShareGrant, primaryjoin="and_(Document.share_id == foreign(ShareGrant.share_id), ShareGrant.agent_id.is_not(None))", viewonly=True)
    url_relations: Mapped[list[DocumentURL]] = relationship(back_populates="document", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def content_profile(self) -> ContentProfile:
        return "rich-text" if self.deletion_protected else "document"

    @hybrid_property
    def document_type(self) -> DocumentType:
        return cast(DocumentType, "text" if self.stored_document_type in {"html", "form"} else self.stored_document_type)

    @document_type.inplace.setter
    def _document_type_set(self, value: str) -> None:
        self.stored_document_type = "text" if value in {"html", "form"} else value

    @document_type.inplace.expression
    @classmethod
    def _document_type_expression(cls) -> ColumnElement[DocumentType]:
        return cast(ColumnElement[DocumentType], case((cls.stored_document_type.in_(("html", "form")), "text"), else_=cls.stored_document_type))

    type_discriminator: Mapped[str] = column_property(case((stored_document_type == "data", "data"), else_="text"))

    __mapper_args__ = {
        "version_id_col": lock_version,
        "polymorphic_on": type_discriminator,
        "polymorphic_identity": "text",
    }

    __table_args__ = (
        *ShareReference.share_constraints("documents", "document"),
        Index("ix_documents_search_vector_gin", "search_vector", postgresql_using="gin"),
        Index("ix_documents_native_content", "resource_id", postgresql_where=sql_text("provider_code = 'native' AND content IS NOT NULL")),
        CheckConstraint("document_type IN ('text', 'data', 'html', 'dataset', 'process', 'form')", name="ck_documents_type"),
        # Legacy shared memories may contain non-editorial text or binary bytes.
        # Preserve their format and retired form archives; APIs enforce current types.
        CheckConstraint("content_type IN ('text', 'binary')", name="ck_documents_text"),
        CheckConstraint("(document_type = 'dataset' AND content_type = 'text' AND media_type = 'application/json' AND content_profile_version IS NULL) OR (document_type = 'process' AND content_type = 'text' AND media_type = 'application/bpmn+xml' AND content_profile_version IS NULL) OR document_type IN ('text', 'html', 'form') OR (document_type='data' AND content_type='text' AND media_type='application/json' AND content_profile_version IS NULL)", name="ck_documents_content_type"),
        CheckConstraint("storage_kind IN ('text','file') AND ((storage_kind='text' AND file_id IS NULL) OR (storage_kind='file' AND file_id IS NOT NULL AND content IS NULL))", name="ck_documents_storage"),
        CheckConstraint("visibility IN ('private', 'shared')", name="ck_documents_visibility"),
    )

class DocumentURL(Base):
    """A canonical document location, independent of its optional graph reference."""

    __tablename__ = "document_urls"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="url_relations")
    __table_args__ = (UniqueConstraint("document_id", "url"), CheckConstraint("length(btrim(url)) > 0", name="ck_document_urls_nonempty"))


class DocumentRevision(Base):
    """Immutable metadata and resource pointer for one item revision."""

    __tablename__ = "document_revisions"

    temporal: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
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
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    author_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    storage_kind: Mapped[str] = mapped_column(String(10), default="text", server_default="text")
    dataset_id = synonym("document_id")
    document_source_revision_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_revisions.id", ondelete="RESTRICT"))

    def __init__(self, **kwargs: Any) -> None:
        from hashlib import sha256
        content = kwargs.get("content")
        defaults: dict[str, Any] = dict(provider_code="native", resource_id=str(uuid4()),
            content_type="text", media_type="application/json" if "dataset_id" in kwargs else "text/html", title="",
            metadata_={}, document_content_version=True)
        if isinstance(content, str):
            defaults["content_hash"] = sha256(content.encode()).hexdigest()
        super().__init__(**(defaults | kwargs))

    document: Mapped[Document] = relationship(back_populates="revisions", foreign_keys=[document_id])

    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="uq_document_revision"),
        CheckConstraint("storage_kind IN ('text','file') AND ((storage_kind='text' AND file_id IS NULL) OR (storage_kind='file' AND file_id IS NOT NULL AND content IS NULL))", name="ck_document_revisions_storage"),
        Index("ix_document_revisions_native_content", "resource_id", postgresql_where=sql_text("provider_code = 'native' AND content IS NOT NULL")),
    )

class DocumentSource(Base):
    """Provenance edge linking a memory to one canonical observed source.

    The typed foreign keys make Task and conversation-round provenance genuine
    many-to-many relations.  ``source_kind``/``source_ref`` remain the
    stable, extensible identity for source kinds that do not own a canonical
    table and for detailed evidence such as one Task outcome fingerprint.
    """

    __tablename__ = "document_sources"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
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
            "document_id", "source_kind", "source_ref", name="uq_document_source"
        ),
    )


class DocumentAutomationJob(Base):
    """Durable idempotent work item for post-task capture and maintenance."""

    __tablename__ = "document_automation_jobs"

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
            name="ck_document_automation_jobs_status",
        ),
    )
