"""Harness catalogue and per-agent runtime persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base, HistoryMixin

if TYPE_CHECKING:
    from app.agent import Agent


class HarnessExecutionConfiguration(HistoryMixin, Base):
    """Common execution settings; every provider, including embedded, has the same row shape."""

    __tablename__ = "harness_execution_configurations"
    __table_args__ = (CheckConstraint("revision >= 1", name="ck_harness_execution_configuration_revision"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Harness(HistoryMixin, Base):
    """Reusable operator-managed OpenAI Messages Harness configuration."""

    __tablename__ = "harnesses"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_harnesses_revision_positive"),
        CheckConstraint(
            "provider_code = 'openai_messages'",
            name="ck_harnesses_openai_messages_only",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    driver_code: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    base_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    model: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    capabilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignments: Mapped[list["AgentHarness"]] = relationship(
        "AgentHarness", back_populates="harness", passive_deletes=True
    )


class AgentHarness(Base):
    """The one external Harness runtime currently selected by an agent."""

    __tablename__ = "agent_harnesses"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_harnesses_agent_id"),
        CheckConstraint(
            "lifecycle_status IN ('absent', 'provisioning', 'ready', 'deprovisioning', 'error')",
            name="ck_agent_harnesses_lifecycle_status",
        ),
        CheckConstraint("revision >= 1", name="ck_agent_harnesses_revision_positive"),
        CheckConstraint(
            "(provider_code = 'openai_messages' AND harness_id IS NOT NULL) OR "
            "(provider_code <> 'openai_messages' AND harness_id IS NULL)",
            name="ck_agent_harnesses_selection_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE", name="fk_agent_harnesses_agent_id"),
        nullable=False,
        index=True,
    )
    harness_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "harnesses.id",
            ondelete="RESTRICT",
            name="fk_agent_harnesses_harness_id",
        ),
        nullable=True,
        index=True,
    )
    provider_code: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="openai_messages"
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="absent", server_default="absent"
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    runtime_base_url: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    runtime_model: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent: Mapped["Agent"] = relationship("Agent", foreign_keys=[agent_id])
    harness: Mapped[Harness | None] = relationship(Harness, back_populates="assignments")


__all__ = ["AgentHarness", "Harness"]
