"""Persistent configuration and session state for the Hermes driver."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class HermesAgentConfig(Base):
    """Driver-owned configuration for one generic Galaris agent.

    The legacy ``agents.hermes_*`` columns deliberately remain in place only as
    a one-way backfill source until a separately reviewed contraction migration.
    """

    __tablename__ = "hermes_agent_configs"

    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="hermes-agent",
        server_default="hermes-agent",
    )
    use_galaris_llm: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    api_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dashboard_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    dashboard_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dashboard_username: Mapped[str | None] = mapped_column(String, nullable=True)
    dashboard_password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    compose: Mapped[str | None] = mapped_column(Text, nullable=True)
    mcp_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_env: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class HermesSessionBinding(Base):
    """Persistent pointer to the active Hermes session for a conversation.

    Hermes may rotate its identifier while compacting context. The logical
    Galaris key remains stable while ``session_id`` follows that rotation.
    """

    __tablename__ = "hermes_session_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "scope_hash", name="uq_hermes_session_binding_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_key: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
