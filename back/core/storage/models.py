"""Backend-independent identities for internally managed immutable files."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, HistoryMixin


class StoredFile(HistoryMixin, Base):
    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(512))
    original_name: Mapped[str | None] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(80), default="disk")
    storage_key: Mapped[str] = mapped_column(String(1024))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("backend", "storage_key"),
        CheckConstraint("size_bytes >= 0", name="ck_files_size"),
        CheckConstraint("purged_at IS NULL OR deleted_at IS NOT NULL", name="ck_files_purged"),
        Index("ix_files_pending_purge", "id", postgresql_where=text("deleted_at IS NOT NULL AND purged_at IS NULL")),
    )


class FileAlias(Base):
    """A domain-owned reference. Its domain remains responsible for authorization."""

    __tablename__ = "file_aliases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    uri: Mapped[str] = mapped_column(Text, unique=True)
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id"), index=True)


class FileStore(Base):
    """Bind the disk volume to the database, detecting a missing/replaced mount."""

    __tablename__ = "file_stores"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
