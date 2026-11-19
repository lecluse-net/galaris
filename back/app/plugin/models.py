"""Plugin releases, retained identities and their administration history."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base

from .contracts import Operation


class PluginRelease(Base):
    __tablename__ = "plugin_releases"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_plugin_release_code_version"),
        Index("ix_plugin_release_active", "code", unique=True, postgresql_where=text("active")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(32))
    signer: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[str] = mapped_column(Text)
    presets: Mapped[str] = mapped_column(Text)
    archive: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    installed: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)
    forced_host: Mapped[str | None] = mapped_column(String(64))


class PluginEvent(Base):
    __tablename__ = "plugin_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("plugin_releases.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    operation: Mapped[Operation] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    forced: Mapped[bool] = mapped_column(Boolean)
    host_version: Mapped[str | None] = mapped_column(Text)
    host_revision: Mapped[str | None] = mapped_column(String(64))
    host_identity: Mapped[str | None] = mapped_column(String(64))


class DevelopmentSampleState(Base):
    """Instance-wide selection of a sample shipped with a development checkout."""

    __tablename__ = "plugin_development_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    active: Mapped[bool] = mapped_column(Boolean)
