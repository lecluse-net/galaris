"""HTTP contracts for durable voice conversations and topic assignment."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VoiceConversationSummary(BaseModel):
    """One durable phone call displayed in execution monitoring."""

    id: UUID
    agent_id: int | None = None
    agent_name: str | None = None
    agent_code: str | None = None
    caller_name: str | None = None
    connection_id: int | None = None
    topic_id: UUID | None = None
    transport_kind: str
    room_id: str
    language: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration: float = 0.0
    turn_count: int = 0
    interrupted_count: int = 0
    failed_count: int = 0


class VoiceConversationTurnRead(BaseModel):
    """One transcribed user turn and the response produced for it."""

    id: UUID
    sequence: int
    run_id: UUID
    source_turn_id: UUID | None = None
    resolved_by_turn_id: UUID | None = None
    topic_id: UUID | None = None
    transcript: str | None = None
    effective_objective: str | None = None
    assistant_response: str | None = None
    status: str
    error: str | None = None
    started_at: datetime
    first_text_at: datetime | None = None
    first_audio_at: datetime | None = None
    interrupted_at: datetime | None = None
    completed_at: datetime | None = None
    llm_call_count: int = 0


class VoiceConversationTopicUpdate(BaseModel):
    topic_id: UUID | None = None


class VoiceConversationTurnDetail(VoiceConversationTurnRead):
    """One turn with its complete driver exchange, loaded only on demand."""

    session_id: UUID
    agent_id: int | None = None
    agent_name: str | None = None
    caller_name: str | None = None
    connection_id: int | None = None
    transport_kind: str
    room_id: str
    language: str
    execution_result: dict[str, object] | None = None


def _empty_turns() -> list[VoiceConversationTurnRead]:
    return []


class VoiceConversationDetail(VoiceConversationSummary):
    """A call and its complete ordered transcript."""

    error: str | None = None
    turns: list[VoiceConversationTurnRead] = Field(default_factory=_empty_turns)


class VoiceConversationOverview(BaseModel):
    """Status totals for every call matching the non-status list filters."""

    active: int = 0
    completed: int = 0
    cancelled: int = 0
    errors: int = 0


class VoiceConversationPage(BaseModel):
    """Paginated voice-call history."""

    items: list[VoiceConversationDetail]
    total: int
    page: int
    page_size: int
    summary: VoiceConversationOverview


__all__ = [
    "VoiceConversationDetail",
    "VoiceConversationOverview",
    "VoiceConversationPage",
    "VoiceConversationSummary",
    "VoiceConversationTopicUpdate",
    "VoiceConversationTurnDetail",
    "VoiceConversationTurnRead",
]
