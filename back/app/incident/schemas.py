"""HTTP contracts for reviewing durable failure incidents."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal[
    "new", "triaged", "fix_planned", "resolved", "ignored", "regression"
]


class FailurePatternRead(BaseModel):
    id: UUID
    fingerprint: str
    fingerprint_version: int
    kind: str
    category: str
    title: str
    status: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    diagnosis: str
    root_cause: str
    remediation: str
    fixed_by_commit: str
    regression_test: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FailurePatternUpdate(BaseModel):
    status: ReviewStatus | None = None
    diagnosis: str | None = Field(default=None, max_length=100_000)
    root_cause: str | None = Field(default=None, max_length=100_000)
    remediation: str | None = Field(default=None, max_length=100_000)
    fixed_by_commit: str | None = Field(default=None, max_length=200)
    regression_test: str | None = Field(default=None, max_length=500)


class FailureIncidentRead(BaseModel):
    id: UUID
    pattern_id: UUID
    pattern_status: str
    pattern_occurrence_count: int
    causal_incident_id: UUID | None
    idempotency_key: str
    kind: str
    category: str
    phase: str
    severity: str
    error_type: str
    error_code: str | None
    error_message: str
    retryable: bool | None
    attempt_number: int | None
    retry_limit: int | None
    will_retry: bool | None
    recovered_at: datetime | None
    task_id: UUID | None
    task_attempt_id: UUID | None
    llm_call_id: UUID | None
    conversation_round_id: UUID | None
    process_run_id: UUID | None
    agent_id: int | None
    run_uuid: UUID | None
    driver_code: str | None
    provider_code: str | None
    model_code: str | None
    tool_name: str | None
    tool_call_external_id: str | None
    occurred_at: datetime
    created_at: datetime


class FailureIncidentDetail(FailureIncidentRead):
    pattern: FailurePatternRead
    trace_schema_version: str
    trace: dict[str, Any]
    redacted_fields: list[str]
    truncated_fields: list[str]
    trace_content_hash: str
    trace_byte_size: int


class FailureIncidentSummaryRead(BaseModel):
    """Detail-free incident projection for overview surfaces."""

    id: UUID
    kind: str
    recovered_at: datetime | None
    occurred_at: datetime


class FailureIncidentPage(BaseModel):
    items: list[FailureIncidentRead]
    total: int
    page: int
    page_size: int


class FailurePatternPage(BaseModel):
    items: list[FailurePatternRead]
    total: int
    page: int
    page_size: int


class FailureIncidentSummaryPage(BaseModel):
    items: list[FailureIncidentSummaryRead]
    total: int
    page: int
    page_size: int


__all__ = [
    "FailureIncidentDetail",
    "FailureIncidentPage",
    "FailureIncidentRead",
    "FailureIncidentSummaryPage",
    "FailureIncidentSummaryRead",
    "FailurePatternPage",
    "FailurePatternRead",
    "FailurePatternUpdate",
]
