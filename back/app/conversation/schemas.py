"""HTTP contracts for conversation monitoring and topic assignment."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field
from app.task import TaskStartupTiming


class ConversationNotificationTarget(BaseModel):
    kind: Literal["task", "process"]
    link_id: UUID
    attempt_number: int = Field(ge=0)


class ConversationUnknownNotification(ConversationNotificationTarget):
    target_id: UUID
    error: str | None = None


def _empty_unknown_notifications() -> list[ConversationUnknownNotification]:
    return []


class ConversationDeliveryResolve(BaseModel):
    decision: Literal["DELIVERED", "SKIPPED"]
    evidence: str = Field(min_length=10, max_length=2000)
    notification: ConversationNotificationTarget | None = None


class ConversationStatusOverview(BaseModel):
    idle: int = 0
    ready: int = 0
    running: int = 0
    errors: int = 0


class ConversationMessageRead(BaseModel):
    id: UUID
    room_id: UUID
    sequence: int
    agent_id: int
    agent_name: str | None = None
    agent_code: str | None = None
    channel_kind: str
    connection_id: int
    participant_key: str
    language: str
    payload: dict[str, object]
    created_at: datetime
    round_id: UUID | None = None
    round_status: str | None = None
    response_text: str | None = None
    response_error: str | None = None
    responded_at: datetime | None = None
    aggregated_message_count: int = 0
    topic_id: UUID | None = None


class ConversationMessagePage(BaseModel):
    items: list[ConversationMessageRead]
    total: int
    page: int
    page_size: int
    summary: ConversationStatusOverview


class ConversationTopicUpdate(BaseModel):
    topic_id: UUID | None = None


def _empty_rendered_input() -> list[dict[str, object]]:
    return []


class ConversationRoundRead(BaseModel):
    id: UUID
    requester_user_id: int | None = None
    topic_id: UUID | None = None
    status: str
    rendered_input: list[dict[str, object]] = Field(
        default_factory=_empty_rendered_input
    )
    response_text: str | None = None
    execution_result: dict[str, object] | None = None
    delivery_state: str
    effect_started: bool
    attempt_count: int
    last_error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ConversationRoundDetail(ConversationRoundRead):
    """One round with its canonical room metadata for the monitoring modal."""

    agent_id: int
    task_startup_timings: list[TaskStartupTiming] = Field(default_factory=list[TaskStartupTiming])
    agent_name: str | None = None
    channel_kind: str
    connection_id: int
    room_id: UUID
    participant_key: str
    language: str
    unknown_notifications: list[ConversationUnknownNotification] = Field(default_factory=_empty_unknown_notifications)


__all__ = [
    "ConversationMessagePage",
    "ConversationMessageRead",
    "ConversationRoundDetail",
    "ConversationRoundRead",
    "ConversationStatusOverview",
    "ConversationTopicUpdate",
]
