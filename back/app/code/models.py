"""Durable repository identities, explicit grants, links and human IDE sessions."""

from datetime import datetime
from uuid import UUID, uuid4

from core.database import Base
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CodeWorkspace(Base):
    __tablename__ = "code_workspaces"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    root: Mapped[str] = mapped_column(Text)
    home: Mapped[str] = mapped_column(Text)
    git_paths: Mapped[list[str]] = mapped_column(JSONB)
    generation: Mapped[str] = mapped_column(String(64))
    connection_fingerprint: Mapped[str] = mapped_column(String(64))
    branch: Mapped[str | None] = mapped_column(String(300))
    head: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("connection_id", "root", "generation"),)


class CodeGrant(Base):
    __tablename__ = "code_grants"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("code_workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(10))
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (agent_id IS NULL)", name="ck_code_grant_subject"),
        CheckConstraint("mode IN ('read', 'edit')", name="ck_code_grant_mode"),
        UniqueConstraint("workspace_id", "user_id"), UniqueConstraint("workspace_id", "agent_id"),
    )


class CodeConversationLink(Base):
    __tablename__ = "code_conversation_links"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("code_workspaces.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("messenger_rooms.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("workspace_id", "room_id"),)


class CodeDisplayRequest(Base):
    __tablename__ = "code_display_requests"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("code_workspaces.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[UUID] = mapped_column(ForeignKey("messenger_rooms.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    file: Mapped[str | None] = mapped_column(String(1024))
    view: Mapped[str] = mapped_column(String(10))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodeSession(Base):
    __tablename__ = "code_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("code_workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"))
    role_bound: Mapped[bool] = mapped_column(default=False)
    session_family: Mapped[str] = mapped_column(String(36))
    auth_version: Mapped[int] = mapped_column()
    mode: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(10), default="opening")
    ticket_digest: Mapped[str | None] = mapped_column(String(64))
    ticket_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cookie_digest: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("mode IN ('read', 'edit')", name="ck_code_session_mode"),
        CheckConstraint("state IN ('opening', 'ready', 'closing', 'closed', 'failed')", name="ck_code_session_state"),
        Index("uq_code_active_session", "workspace_id", "user_id", "mode", "session_family", unique=True,
              postgresql_where=text("(state)::text = ANY ((ARRAY['opening'::character varying, 'ready'::character varying])::text[])")),
    )
