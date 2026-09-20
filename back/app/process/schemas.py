"""Public Pydantic contracts for processes and their engines."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


ProcessStatus = Literal[
    "queued", "running", "waiting", "success", "error", "cancelling", "cancelled", "unknown"
]


class EngineError(BaseModel):
    code: str
    message: str
    node_name: Optional[str] = None


class EngineProcessDefinition(BaseModel):
    engine_process_id: str
    label: str
    description: Optional[str] = None
    active: bool


class ProcessEngineHealth(BaseModel):
    tool_code: str
    status: Literal["healthy", "degraded", "error"]
    reachable: bool
    authenticated: bool
    supports_cancel: bool
    cancel_mode: Literal["supported", "best_effort", "unsupported"]
    message: str
    details: list[str] = Field(default_factory=list)
    checked_at: datetime


class ProcessOperationsRead(BaseModel):
    status_counts: dict[str, int] = Field(default_factory=dict)
    pending_start_jobs: int = 0
    stale_active_runs: int = 0
    failed_last_24h: int = 0
    oldest_pending_job_seconds: Optional[float] = None
    checked_at: datetime


class EngineStartResult(BaseModel):
    accepted: bool
    engine_run_id: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class EngineRunSnapshot(BaseModel):
    status: ProcessStatus
    engine_run_id: Optional[str] = None
    output: Optional[dict[str, Any]] = None
    error: Optional[EngineError] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class EngineRunReference(BaseModel):
    id: UUID
    engine_run_id: Optional[str] = None
    correlation_id: str
    callback_token: str = ""


class ProcessFileInput(BaseModel):
    uri: str = Field(min_length=1)
    description: str = ""


class ProcessFileRef(BaseModel):
    kind: Literal["galaris_file_ref"] = "galaris_file_ref"
    id: str
    uri: str = Field(validation_alias=AliasChoices("uri", "path"))
    runtime: str = "internal"
    task_id: UUID | None = None
    filename: str
    content_type: str
    size: int
    description: str = ""
    download_url: str
    expires_at: datetime


class ProcessStartPayload(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    files: list[ProcessFileRef] = Field(default_factory=lambda: [])
    launch_snapshot: dict[str, Any] = Field(default_factory=dict)


class ProcessDefinitionBase(BaseModel):
    agent_id: Optional[int] = None
    tool_id: int
    engine_process_id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class ProcessDefinitionCreate(ProcessDefinitionBase):
    pass


class ProcessDefinitionUpdate(BaseModel):
    agent_id: Optional[int] = Field(default=None, gt=0)
    tool_id: Optional[int] = Field(default=None, gt=0)
    engine_process_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class ProcessDefinitionRead(ProcessDefinitionBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ProcessToolRead(BaseModel):
    id: int
    code: str
    label: str
    model_config = ConfigDict(from_attributes=True)


class ProcessStartRequest(BaseModel):
    workflow_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    files: list[ProcessFileInput] = Field(default_factory=lambda: [])
    wait_for_completion: bool = False
    idempotency_key: Optional[str] = Field(default=None, max_length=255)


class AdminProcessStartRequest(ProcessStartRequest):
    agent_id: int
    task_id: Optional[UUID] = None
    runtime: str = "internal"


class ProcessStartResponse(BaseModel):
    run_id: UUID
    status: ProcessStatus
    workflow_id: str
    tool: str
    engine_run_id: Optional[str] = None
    deduplicated: bool = False
    tracking_message: str


class ProcessRunRead(BaseModel):
    id: UUID
    process_id: int
    workflow_id: Optional[str] = None
    process_label: Optional[str] = None
    launcher_agent_id: int
    launcher_agent_code: Optional[str] = None
    task_id: Optional[UUID] = None
    await_task_id: Optional[UUID] = None
    tool_code: str = Field(validation_alias=AliasChoices("engine_code", "tool_code"))
    engine_run_id: Optional[str] = None
    correlation_id: str
    status: ProcessStatus
    input: dict[str, Any]
    output: Optional[dict[str, Any]] = None
    engine_metadata: dict[str, Any]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    fresh: bool = True
    summary: str = ""
    model_config = ConfigDict(from_attributes=True)


class ProcessRunPage(BaseModel):
    items: list[ProcessRunRead] = Field(default_factory=lambda: [])
    total: int
    page: int
    page_size: int


class ProcessRunEventRead(BaseModel):
    id: int
    run_id: UUID
    event_id: Optional[str] = None
    source: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProcessLLMCallRead(BaseModel):
    id: UUID
    task_id: Optional[UUID] = None
    purpose: Optional[str] = None
    provider_name: str
    requested_model: str
    effective_model: str
    status: str
    duration: float = 0.0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    error: Optional[str] = None
    started_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProcessRunDetail(ProcessRunRead):
    events: list[ProcessRunEventRead] = Field(default_factory=lambda: [])
    task_ids: list[UUID] = Field(default_factory=lambda: [])
    llm_calls: list[ProcessLLMCallRead] = Field(default_factory=lambda: [])


class ProcessCallbackEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    status: Literal["running", "waiting", "success", "error", "cancelled"]
    engine_run_id: Optional[str] = None
    node_name: Optional[str] = None
    event_type: Optional[str] = None
    error: Optional[EngineError] = None
    output: Optional[dict[str, Any]] = None
    occurred_at: Optional[datetime] = None


class ProcessAnalysis(BaseModel):
    run_id: UUID
    success: bool
    status: ProcessStatus
    summary: str
    duration_seconds: Optional[float] = None
    failed_steps: list[str] = Field(default_factory=lambda: [])
    agent_calls: list[dict[str, Any]] = Field(default_factory=lambda: [])
    llm_calls: list[dict[str, Any]] = Field(default_factory=lambda: [])
    recommendations: list[str] = Field(default_factory=lambda: [])
