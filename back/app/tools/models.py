from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base
from core.database.vector import Vector


class Tool(Base):
    """Database-backed MCP tool definition and its optional integration configuration."""
    __tablename__ = "tools"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    # Software-owned policy, never accepted by the Tool write schemas.
    can_disable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    mcp_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    file_share_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    messenger_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    listener_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    connection_schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Administrator-owned values inherited by every connection.  This column is deliberately
    # separate from ``connection_schema`` because integrated Tool synchronization replaces the
    # schema while configured values must survive upgrades and restarts.
    global_params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    task_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    conversation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        default=lambda: datetime.now(timezone.utc),
    )


class ToolSearchDocument(Base):
    """Rebuildable, permission-neutral search projection of one MCP definition."""

    __tablename__ = "tool_search_documents"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    definition_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    runtime: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    parameters_json_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )
    search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple'::regconfig, coalesce(name, '')), 'A') || "
            "setweight(to_tsvector('simple'::regconfig, "
            "coalesce(description, '')), 'B') || "
            "setweight(to_tsvector('simple'::regconfig, "
            "coalesce(search_text, '')), 'C')",
            persisted=True,
        ),
        nullable=False,
    )
    model_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_tool_search_documents_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_tool_search_documents_semantic",
            "model_key",
            "dimensions",
            "definition_fingerprint",
        ),
        Index("ix_tool_search_documents_last_seen", "last_seen_at"),
    )
