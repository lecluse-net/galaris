"""Public inputs, lifecycle and events of durable inference."""

from typing import Annotated, Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, model_validator

from app.agent.contracts import AIMessage, AIResult
from .provider_facade import ReasoningEffort
from .decision_contracts import ChoiceQuestion


class InferenceInput(BaseModel):
    llm_id: int
    task_id: UUID | None = None
    agent_id: int | None = None
    prompt: str
    system_prompt: str = ""
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    request_limit: int | None = Field(default=3, ge=1)
    count_tokens_before_request: bool = True
    purpose: str
    model_field: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    correlation_ref: str | None = None
    agent_run_id: UUID | None = None
    conversation_round_id: UUID | None = None
    process_run_id: UUID | None = None


class TextInferenceRequest(InferenceInput):
    schema_version: Literal["galaris.text-inference-request/v1"] = (
        "galaris.text-inference-request/v1"
    )


class StructuredOutputSpec(BaseModel):
    contract: str = Field(min_length=1)
    json_schema: dict[str, JsonValue]
    mode: Literal["tool", "prompted"] = "tool"
    context: dict[str, JsonValue] = Field(default_factory=dict)


class StructuredInferenceRequest(InferenceInput):
    schema_version: Literal["galaris.structured-inference-request/v1"] = (
        "galaris.structured-inference-request/v1"
    )
    output: StructuredOutputSpec
    output_retries: int | None = Field(default=None, ge=0)


class ProtocolInferenceRequest(InferenceInput):
    schema_version: Literal["galaris.protocol-inference-request/v1"] = (
        "galaris.protocol-inference-request/v1"
    )
    protocol: Literal["chat", "responses", "compact"]
    body: dict[str, JsonValue]
    sdk_request: bool = False
    managed_runtime_request: bool = False
    unwrap_deferred_tools: bool = False
    force_reasoning_effort: bool = False
    request_timeout: dict[str, float | None] | None = None


class DecisionInferenceRequest(InferenceInput):
    schema_version: Literal["galaris.decision-inference-request/v1"] = "galaris.decision-inference-request/v1"
    questions: dict[str, ChoiceQuestion] = Field(min_length=1)
    fallback_llm_id: int | None = None
    allow_text_fallback: bool = True
    timeout_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    model_bindings: dict[str, str] = Field(default_factory=dict)


InferenceRequest = Annotated[
    TextInferenceRequest | StructuredInferenceRequest | ProtocolInferenceRequest | DecisionInferenceRequest,
    Field(discriminator="schema_version")
]
InferenceRequestAdapter: TypeAdapter[InferenceRequest] = TypeAdapter(InferenceRequest)


class InferenceEvent(BaseModel):
    schema_version: Literal["galaris.inference-event/v1"] = "galaris.inference-event/v1"
    call_id: UUID
    sequence: int = Field(ge=1)
    kind: Literal["message", "result"]
    message: AIMessage | None = None
    result: AIResult | None = None

    @model_validator(mode="after")
    def consistent_payload(self) -> "InferenceEvent":
        if self.kind == "message":
            if self.message is None or self.result is not None:
                raise ValueError("A message event must carry exactly one AIMessage.")
        elif self.result is None or self.message is not None:
            raise ValueError("A terminal event must carry exactly one AIResult.")
        return self


InferenceStatus = Literal[
    "queued",
    "running",
    "pausing",
    "stopping",
    "paused",
    "stopped",
    "completed",
    "failed",
    "interrupted",
]
InferenceAction = Literal["pause", "stop", "resume", "replay"]


class InferenceAttempt(BaseModel):
    id: UUID
    number: int
    status: InferenceStatus
    call_ids: list[UUID] = Field(default_factory=list[UUID])
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: AIResult | None = None


class InferenceRead(BaseModel):
    id: UUID
    replay_of_id: UUID | None = None
    request: InferenceRequest
    status: InferenceStatus
    attempts: list[InferenceAttempt]
    cost: float = 0


class InferenceCommand(BaseModel):
    id: UUID
    inference_id: UUID
    attempt_id: UUID
    action: InferenceAction
    applied_at: datetime | None = None
    replay_id: UUID | None = None


class InferenceControlInput(BaseModel):
    action: InferenceAction
    command_id: UUID | None = None


class InferenceRunEvent(BaseModel):
    inference_id: UUID
    attempt_id: UUID
    sequence: int
    kind: Literal["message", "result"]
    call_id: UUID | None = None
    message: AIMessage | None = None
    result: AIResult | None = None
