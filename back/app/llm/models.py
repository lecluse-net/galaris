"""Persistent models for the LLM module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class LLMInference(Base):
    __tablename__ = "llm_inferences"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    replay_of_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_inferences.id"), index=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requester_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    authority: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LLMInferenceAttempt(Base):
    __tablename__ = "llm_inference_attempts"
    __table_args__ = (UniqueConstraint("inference_id", "number"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    inference_id: Mapped[UUID] = mapped_column(ForeignKey("llm_inferences.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    final_sequence: Mapped[int | None] = mapped_column(Integer)


class LLMInferenceCommand(Base):
    __tablename__ = "llm_inference_commands"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    inference_id: Mapped[UUID] = mapped_column(ForeignKey("llm_inferences.id"), index=True)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("llm_inference_attempts.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replay_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_inferences.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LLMCallEvent(Base):
    """Ordered inference payloads; the existing LLMCall owns lifecycle and billing."""

    __tablename__ = "llm_call_events"
    __table_args__ = (UniqueConstraint("call_id", "sequence"), UniqueConstraint("inference_id", "inference_sequence"))

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("llm_calls.id", ondelete="CASCADE"), index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    inference_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_inferences.id"), index=True)
    inference_sequence: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
    )


class LLMCall(Base):
    """A provider LLM call with an inspectable trace."""

    __tablename__ = "llm_calls"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4, index=True
    )
    inference_attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_inference_attempts.id"), index=True)
    task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    conversation_round_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_rounds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    process_run_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("process_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    correlation_ref: Mapped[Optional[str]] = mapped_column(
        String(300), nullable=True, index=True
    )
    # Snapshot the label, never the credential; survives token rename/deletion.
    # NULL: no recorded API token. Empty: an authenticated token without a label.
    api_token_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )
    agent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    llm_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("llms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    provider_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    provider_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    requested_model: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    effective_model: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    reasoning_effort: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)
    stream: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # A non-stream payload or a reconstructed terminal stream result. Partial SSE chunks are
    # never persisted here; a stream without a terminal result leaves this field empty.
    raw_response: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    finish_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ``cost`` is the amount actually billed. ``inference_cost`` preserves the provider-reported
    # or locally estimated per-inference value even when a subscription makes billing zero.
    cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    inference_cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    cost_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_subscription: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    upstream_request_id: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    first_token_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
