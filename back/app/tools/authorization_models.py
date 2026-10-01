"""One-operation approvals and committed delivery/reconciliation work."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ActionAuthorization(Base):
    __tablename__ = "tool_action_authorizations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    operation_key: Mapped[str] = mapped_column(String(64), unique=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    approver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    tool_id: Mapped[int | None] = mapped_column(ForeignKey("tools.id", ondelete="SET NULL"), nullable=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"), nullable=True)
    runtime_grant_id: Mapped[UUID | None] = mapped_column(ForeignKey("runtime_run_grants.id", ondelete="SET NULL"), nullable=True)
    runtime_grant_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(8))
    capability_kind: Mapped[str] = mapped_column(String(8))
    capability_name: Mapped[str] = mapped_column(String(2000))
    policy_name: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    runtime: Mapped[str] = mapped_column(String(50))
    context_key: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    configuration_fingerprint: Mapped[str] = mapped_column(String(64))
    remember_configuration_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deferred_payload_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_expected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    dispatch_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_source: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending", index=True)
    decision_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    # Contents never appear in activity events or public request summaries.
    encrypted_arguments: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview: Mapped[str] = mapped_column(Text)
    interaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("messenger_interactions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    notification_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wake_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','denied','expired','invalidated','executing','completed','failed','outcome_unknown')", name="ck_action_authorization_status"),
        CheckConstraint("source IN ('mcp','runtime','domain')", name="ck_action_authorization_source"),
        Index("ix_action_authorization_agent_status", "agent_id", "status"),
    )


class RuntimeRunGrant(Base):
    """Server-issued run authority, distinct from a reusable agent MCP credential."""

    __tablename__ = "runtime_run_grants"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("agent_mcp_tokens.id", ondelete="CASCADE"))
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    actor_key: Mapped[str] = mapped_column(String(64), server_default="")
    context_fingerprint: Mapped[str] = mapped_column(String(64), server_default="")
    runtime: Mapped[str] = mapped_column(String(50))
    context_key: Mapped[str] = mapped_column(String(255), index=True)
    run_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    attempt_key: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    target_ref: Mapped[str] = mapped_column(String(255))
    target_revision: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
