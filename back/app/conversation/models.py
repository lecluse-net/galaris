"""Durable conversation rounds, message membership, and lineage."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.database import Base


class ConversationDeliveryResolution(Base):
    """An operator's evidence-based resolution; never an instruction to resend."""

    __tablename__ = "conversation_delivery_resolutions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(ForeignKey("conversation_rounds.id", ondelete="CASCADE"), nullable=False, unique=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConversationNotificationResolution(Base):
    """One operator decision for one attempt to notify a Task or Process result."""

    __tablename__ = "conversation_notification_resolutions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_link_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation_task_links.id", ondelete="CASCADE"))
    process_link_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation_process_links.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint("(task_link_id IS NULL) <> (process_link_id IS NULL)", name="ck_notification_resolution_target"),
        UniqueConstraint("task_link_id", "attempt_number", name="uq_notification_resolution_task_attempt"),
        UniqueConstraint("process_link_id", "attempt_number", name="uq_notification_resolution_process_attempt"),
    )


class ConversationRound(Base):
    """One durable conversational agent run, independent from its medium."""

    __tablename__ = "conversation_rounds"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_rooms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    voice_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("voice_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    topic_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_memory_item_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memory_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="fr", server_default="fr"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="FROZEN", server_default="FROZEN", index=True
    )
    execution_result: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_round_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_by_round_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    effective_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default="PENDING"
    )
    effect_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    effect_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_text_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_audio_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    interrupted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_conversation_round_frozen_room",
            "room_id",
            unique=True,
            postgresql_where=text("status = 'FROZEN'"),
        ),
        Index(
            "uq_conversation_round_processing_room",
            "room_id",
            unique=True,
            postgresql_where=text(
                "(status)::text = ANY ((ARRAY["
                "'CLAIMED'::character varying, "
                "'RUNNING'::character varying])::text[])"
            ),
        ),
        UniqueConstraint(
            "voice_session_id",
            "sequence",
            name="uq_conversation_round_voice_session_sequence",
        ),
    )


class ConversationRoundMessage(Base):
    """Ordered input/output membership between a round and canonical messages."""

    __tablename__ = "conversation_round_messages"

    round_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="CASCADE"),
        primary_key=True,
    )
    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    response_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('input', 'output')",
            name="ck_conversation_round_message_role",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_conversation_round_message_sequence",
        ),
        CheckConstraint(
            "(role = 'input' AND response_sequence IS NULL) OR "
            "(role = 'output' AND response_sequence IS NOT NULL "
            "AND response_sequence > 0)",
            name="ck_conversation_round_message_response",
        ),
        CheckConstraint(
            "role = 'input' OR consumed_at IS NULL",
            name="ck_conversation_round_message_consumed_input",
        ),
        Index(
            "uq_conversation_round_input_sequence",
            "round_id",
            "sequence",
            unique=True,
            postgresql_where=text("role = 'input'"),
        ),
        Index(
            "uq_conversation_round_output_sequence",
            "round_id",
            "response_sequence",
            "sequence",
            unique=True,
            postgresql_where=text("role = 'output'"),
        ),
    )


class ConversationRoundAttempt(Base):
    """Audit record for one round claim."""

    __tablename__ = "conversation_round_attempts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    lease_token: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="CLAIMED", server_default="CLAIMED"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("round_id", "attempt_number", name="uq_conversation_round_attempt"),
    )


class ConversationTaskLink(Base):
    """Idempotent lineage from a round to one background Task."""

    __tablename__ = "conversation_task_links"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    action_key: Mapped[str] = mapped_column(String(200), nullable=False)
    notification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="IDLE", server_default="IDLE"
    )
    notification_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    notification_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    notification_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    notification_task_attempt_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("round_id", "action_key", name="uq_conversation_task_action"),
    )


class ConversationProcessLink(Base):
    """Idempotent lineage from a round to one business Process run."""

    __tablename__ = "conversation_process_links"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    process_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    action_key: Mapped[str] = mapped_column(String(200), nullable=False)
    notification_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default="PENDING"
    )
    notification_message_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messenger_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_lease_token: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    notification_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    notification_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("round_id", "action_key", name="uq_conversation_process_action"),
    )


__all__ = [
    "ConversationProcessLink",
    "ConversationRound",
    "ConversationRoundAttempt",
    "ConversationRoundMessage",
    "ConversationTaskLink",
]
