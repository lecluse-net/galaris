"""Read-only HTTP contracts for Dream monitoring."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.llm.schemas import LLMCallRead

from .contracts import DreamRuntimePhase, DreamRuntimeReason, DreamRuntimeStatus


class DreamRuntimeView(BaseModel):
    status: DreamRuntimeStatus
    phase: DreamRuntimePhase
    reason: DreamRuntimeReason
    worker_running: bool
    current_mechanism: str | None = None
    current_subject_kind: str | None = None
    current_subject_id: str | None = None
    last_cycle_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    next_cycle_at: datetime | None = None
    state_changed_at: datetime | None = None
    cycle_count: int = 0
    last_error_type: str | None = None


class DreamMechanismSummary(BaseModel):
    mechanism_key: str
    pending: int = 0
    running: int = 0
    retry: int = 0
    success: int = 0
    error: int = 0
    result_count: int = 0
    cost: float = 0.0


def _empty_mechanism_summaries() -> list[DreamMechanismSummary]:
    return []


class DreamOverview(BaseModel):
    runtime: DreamRuntimeView
    total_operations: int = 0
    completed_operations: int = 0
    pending_operations: int = 0
    terminal_tasks: int = 0
    unscanned_tasks: int = 0
    running_receipts: int = 0
    retry_receipts: int = 0
    successful_receipts: int = 0
    error_receipts: int = 0
    memories_created: int = 0
    memories_linked: int = 0
    total_cost: float = 0.0
    mechanisms: list[DreamMechanismSummary] = Field(
        default_factory=_empty_mechanism_summaries
    )


class DreamReceiptSummary(BaseModel):
    id: UUID
    mechanism_key: str
    subject_kind: str
    subject_id: str
    status: str
    attempts: int
    result_count: int
    cost: float
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    subject_preview: str | None = None
    task_label: str | None = None
    task_status: str | None = None
    agent_id: int | None = None


class DreamReceiptDetail(DreamReceiptSummary):
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    prepared_payload: dict[str, Any] | None = None
    llm_calls: list[LLMCallRead] = Field(default_factory=lambda: [])


class DreamReceiptPage(BaseModel):
    items: list[DreamReceiptSummary]
    total: int
    page: int
    page_size: int


TopicAssignmentSubjectKind = Literal[
    "task",
    "message",
    "conversation_round",
    "voice_session",
]
TopicAssignmentAction = Literal["continuity", "reuse", "create"]


class DreamTopicAssignmentAudit(BaseModel):
    """Bounded provenance for the Topic currently shown on one activity."""

    topic_id: UUID
    subject_kind: TopicAssignmentSubjectKind
    subject_id: UUID
    origin: Literal["dream", "manual"]
    reason: str | None = None
    action: TopicAssignmentAction | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    human_confirmed: bool = False
    dream_receipt_id: UUID | None = None
    dream_mechanism_key: str | None = None
    dream_subject_kind: str | None = None
    dream_subject_id: str | None = None
    decided_at: datetime | None = None


__all__ = [
    "DreamMechanismSummary",
    "DreamOverview",
    "DreamReceiptDetail",
    "DreamReceiptPage",
    "DreamReceiptSummary",
    "DreamRuntimeView",
    "DreamTopicAssignmentAudit",
    "TopicAssignmentAction",
    "TopicAssignmentSubjectKind",
]
