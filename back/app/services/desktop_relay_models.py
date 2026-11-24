"""Desktop MCP registrations and short-lived requests shared by API workers."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class DesktopMcpRelay(Base):
    __tablename__ = "desktop_mcp_relays"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), unique=True)
    desktop_digest: Mapped[str] = mapped_column(String(64))
    service_digest: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DesktopMcpRequest(Base):
    __tablename__ = "desktop_mcp_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    relay_id: Mapped[UUID] = mapped_column(ForeignKey("desktop_mcp_relays.id", ondelete="CASCADE"), index=True)
    session_key: Mapped[UUID] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    message_ciphertext: Mapped[str | None] = mapped_column(Text)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    response_ciphertext: Mapped[str | None] = mapped_column(Text)
