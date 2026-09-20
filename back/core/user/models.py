from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy import JSON, String, DateTime, func, ForeignKey, LargeBinary, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from loguru import logger

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    auth_version: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    language: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    document_open_mode: Mapped[str] = mapped_column(
        String(16), default="split", server_default="split", nullable=False,
    )
    avatar: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary,
        nullable=True,
        deferred=True,
    )
    avatar_mime_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    avatar_key: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    failed_login_attempts: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        nullable=False,
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    totp_secret_encrypted: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
        nullable=False,
    )
    totp_last_counter: Mapped[Optional[int]] = mapped_column(nullable=True)
    recovery_code_hashes: Mapped[List[str]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'::json"),
        nullable=False,
    )

    tokens: Mapped[List["UserToken"]] = relationship("UserToken", back_populates="user", cascade="all, delete-orphan")
    refresh_sessions: Mapped[List["UserRefreshSession"]] = relationship(
        "UserRefreshSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def avatar_url(self) -> str | None:
        """Return the cache-safe internal URL for this user's avatar."""

        if self.avatar_key is None or self.avatar_mime_type is None:
            return None
        return f"/api/auth/avatars/{self.avatar_key}"


class UserHelpDismissal(Base):
    """Permanent, independent acknowledgements of contextual help per account."""

    __tablename__ = "user_help_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "help_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    help_key: Mapped[str] = mapped_column(String(100))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="tokens")

    @property
    def token(self) -> str:
        """Return a masked display value; the actual token stays encrypted."""
        from core.util.encryption import decrypt_value
        try:
            plain = decrypt_value(self.token_encrypted)
            if len(plain) <= 20:
                return plain
            return f"{plain[:8]}...{plain[-8:]}"
        except Exception:
            logger.exception("Unable to decrypt user token id={}", self.id)
            return "ut_***...***"


class UserRefreshSession(Base):
    """Rotating browser session backing the HttpOnly refresh cookie."""

    __tablename__ = "user_refresh_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="refresh_sessions")
