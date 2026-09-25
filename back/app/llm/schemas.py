"""LLM module API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .provider_facade import ReasoningEffort
from .trace import infer_call_purpose, infer_call_type


class LLMCallRead(BaseModel):
    id: UUID
    api_token_label: str | None = None
    requester_user_id: Optional[int] = None
    task_id: Optional[UUID] = None
    task_attempt_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    conversation_round_id: Optional[UUID] = None
    process_run_id: Optional[UUID] = None
    correlation_ref: Optional[str] = None
    purpose: Optional[str] = None
    agent_id: Optional[int] = None
    llm_id: Optional[int] = None
    task_label: Optional[str] = None
    task_status: Optional[str] = None
    agent_name: Optional[str] = None
    agent_code: Optional[str] = None
    process_label: Optional[str] = None
    provider_name: str
    provider_code: Optional[str] = None
    requested_model: str
    effective_model: str
    reasoning_effort: ReasoningEffort | None = None
    status: str
    stream: bool
    request_messages: list[dict[str, Any]] = Field(default_factory=lambda: [])
    prompt: str = ""
    system_prompt: str = ""
    response_text: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=lambda: [])
    raw_response: str = ""
    finish_reason: Optional[str] = None
    usage: dict[str, Any] = Field(default_factory=lambda: {})
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float = 0.0
    inference_cost: float = 0.0
    cost_estimated: bool = True
    is_subscription: bool = False
    upstream_request_id: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime
    first_token_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration: float = 0.0
    created_at: datetime
    updated_at: datetime

    @field_validator("inference_cost", mode="before")
    @classmethod
    def _default_inference_cost(cls, value: Any) -> float:
        return float(value or 0.0)

    @field_validator("raw_response", mode="before")
    @classmethod
    def _default_raw_response(cls, value: Any) -> str:
        return value if isinstance(value, str) else ""

    @field_validator("is_subscription", mode="before")
    @classmethod
    def _default_subscription(cls, value: Any) -> bool:
        return bool(value)

    @model_validator(mode="after")
    def _infer_legacy_purpose(self) -> "LLMCallRead":
        if self.purpose is None:
            self.purpose = infer_call_purpose(
                self.request_messages,
                self.system_prompt,
            )
        return self

    @computed_field
    @property
    def call_type(self) -> str:
        """Stable UI category inferred from the persisted request trace."""
        return infer_call_type(self.request_messages, self.system_prompt)

    model_config = ConfigDict(from_attributes=True)


class LLMCallSummary(BaseModel):
    """Global totals across every persisted LLM call."""

    running: int = 0
    completed: int = 0
    errors: int = 0
    total_cost: float = 0.0
    total_inference_cost: float = 0.0


class LLMCallPage(BaseModel):
    """Paginated history of completed LLM calls."""

    items: list[LLMCallRead] = Field(default_factory=lambda: [])
    total: int
    page: int
    page_size: int
    summary: LLMCallSummary


class ProxyModel(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "galaris"
    context_length: Optional[int] = None


class ProxyModelList(BaseModel):
    object: str = "list"
    data: list[ProxyModel]
