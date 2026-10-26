"""Dataset-owned content, history, ACL."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin
from app.share import Shareable


class Dataset(Shareable, HistoryMixin, Base):
    __share_kind__ = "dataset"
    __tablename__ = "datasets"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id: Mapped[UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    legacy_global_access: Mapped[int] = mapped_column("global_access", Integer, default=0, server_default="0")
    legacy_group_access: Mapped[int] = mapped_column("group_access", Integer, default=0, server_default="0")
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    creation_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    creation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        *Shareable.share_constraints("datasets", "dataset"),
        CheckConstraint("owner_agent_id IS NULL OR owner_user_id IS NULL"),
        CheckConstraint("global_access IN (0,1,2) AND group_access IN (0,1,2)"),
        CheckConstraint("global_access = 0 OR group_access = 0"),
        CheckConstraint("revision > 0 AND lock_version > 0"),
    )


class DatasetRevision(Base):
    __tablename__ = "dataset_revisions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    author_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document_source_revision_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_revisions.id", ondelete="RESTRICT"), unique=True)
    __table_args__ = (UniqueConstraint("dataset_id", "revision"),)


class DatasetGrant(Base):
    __tablename__ = "dataset_grants"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (
        CheckConstraint("num_nonnulls(agent_id,user_id,team_id) = 1"),
        UniqueConstraint("dataset_id", "agent_id"), UniqueConstraint("dataset_id", "user_id"), UniqueConstraint("dataset_id", "team_id"),
    )


class DatasetAlias(Base):
    __tablename__ = "dataset_aliases"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    legacy_document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), unique=True)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), unique=True)
    source_revision: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetAttachment(HistoryMixin, Base):
    __tablename__ = "dataset_attachments"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    uri: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    legacy_attachment_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_attachments.id", ondelete="RESTRICT"), unique=True)



class DatasetWriteBudget(Base):
    __tablename__ = "dataset_write_budgets"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    writes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_written: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "dataset_id"),)


class DatasetAppearance(Base):
    __tablename__ = "dataset_appearances"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    icon: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    at_root: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    __table_args__ = (UniqueConstraint("user_id", "dataset_id"),)


class DatasetTag(HistoryMixin, Base):
    __tablename__ = "dataset_tags"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("dataset_tags.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)


class DatasetTagAssignment(Base):
    __tablename__ = "dataset_tag_assignments"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_tags.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("dataset_id", "tag_id"),)


class DatasetAppConsent(HistoryMixin, Base):
    __tablename__ = "dataset_app_consents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    app_key: Mapped[str] = mapped_column(String(40))
    alias: Mapped[str] = mapped_column(String(40))
    document_revision: Mapped[int] = mapped_column(Integer)
    access: Mapped[str | None] = mapped_column(String(5))
    __table_args__ = (UniqueConstraint("user_id", "document_id", "app_key", "alias"), CheckConstraint("access IS NULL OR access IN ('read','write')"))
