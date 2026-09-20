"""Public contracts for the runtime-neutral conversation domain."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

from app.agent import AIMessage, AIResult
from app.agent.contracts import ReasoningEffort
from app.process import ProcessRunRead
from app.task import TaskRead

from .trace_projection import public_mapping, public_text


FreshnessGuard = Callable[[], Awaitable[bool]]


class ConversationLeaseLostError(RuntimeError):
    """The caller no longer owns the active conversation attempt."""


class BackgroundTaskAdmission(Protocol):
    """Create one durable Task from a deterministic conversation directive."""

    async def __call__(
        self,
        objective: str,
        *,
        forced_route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None,
        forced_effort: Literal["standard", "high"] | None = None,
        require_briefing: bool = False,
        auto_approve: bool = False,
    ) -> Mapping[str, object]: ...


def public_ai_message(message: AIMessage) -> AIMessage:
    """Return the bounded, credential-redacted public form of one ``AIMessage``."""

    return message.model_copy(
        update={
            "content": public_text(message.content, limit=8_000),
            "tool_name": public_text(message.tool_name, limit=200) or None,
            "tool_arguments": public_mapping(message.tool_arguments),
            "tool_result": public_mapping(message.tool_result),
        }
    )


def public_ai_result(result: AIResult) -> AIResult:
    """Bound a terminal result without inventing a conversation-only trace format."""

    return result.model_copy(
        update={
            "prompt": "",
            "system_prompt": "",
            "messages": [public_ai_message(message) for message in result.messages],
            "result": public_text(result.result, limit=8_000),
            "metadata": {},
        }
    )


class ConversationRuntimeEvent(BaseModel):
    """Ephemeral ordered state for one running conversation round."""

    round_id: UUID
    kind: Literal["started", "message", "reset", "snapshot", "finished"]
    sequence: int = Field(ge=0)
    attempt: int = Field(default=1, ge=1)
    topic_id: UUID | None = None
    message: AIMessage | None = None
    result: AIResult | None = None
    success: bool = True

    @model_validator(mode="after")
    def canonical_payload_matches_kind(self) -> "ConversationRuntimeEvent":
        if self.kind == "message" and self.message is None:
            raise ValueError("A conversation message event must contain an AIMessage.")
        if self.kind != "message" and self.message is not None:
            raise ValueError("Only a conversation message event may contain an AIMessage.")
        if self.kind not in {"snapshot", "finished"} and self.result is not None:
            raise ValueError("Only a snapshot or finished conversation event may contain an AIResult.")
        if self.kind == "snapshot" and self.result is None:
            raise ValueError("A conversation snapshot must contain an AIResult.")
        return self


ConversationProgressPublisher = Callable[
    [AIMessage], Awaitable[None]
]
ConversationProgressResetter = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class ConversationTurn:
    """Frozen, bounded input sent to the fast conversation controller."""

    room_id: UUID
    round_id: UUID
    agent_id: int
    language: str
    objective: str
    messages: tuple[Mapping[str, object], ...]
    messaging_context: Mapping[str, object] = field(default_factory=dict[str, object])
    # Complete admitted input, before controller budgeting and display annotations.
    # Voice/legacy callers fall back to their admitted objective, never their history.
    source_request: str | None = None
    linked_work: tuple[Mapping[str, object], ...] = ()
    pending_interactions: tuple[Mapping[str, object], ...] = ()
    omitted_input_count: int = 0
    assert_fresh_before_effect: FreshnessGuard | None = None
    should_interrupt: FreshnessGuard | None = None
    admit_background_task: BackgroundTaskAdmission | None = None
    origin: Literal["text", "voice"] = "text"
    topic_id: UUID | None = None
    direct_task_requested: bool = False
    reasoning_effort_override: ReasoningEffort | None = None
    contact_memory_item_id: UUID | None = None
    publish_progress: ConversationProgressPublisher | None = None
    reset_progress: ConversationProgressResetter | None = None
    attempt: int = 1

    @property
    def sender_is_ai(self) -> bool:
        """Return whether the newest admitted input belongs to another agent."""

        if not self.messages:
            return False
        sender_agent_id = self.messages[-1].get("sender_agent_id")
        return (
            isinstance(sender_agent_id, int)
            and not isinstance(sender_agent_id, bool)
            and sender_agent_id != self.agent_id
        )


@dataclass(frozen=True)
class ConversationOutcome:
    """Controller output separated from durable effects executed by its tools."""

    text: str
    effect_started: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict[str, object])
    execution_result: AIResult | None = None


class ConversationExecutionError(RuntimeError):
    """Failed short run carrying the partial driver trace produced before failure."""

    def __init__(
        self,
        message: str,
        *,
        execution_result: AIResult | None = None,
    ) -> None:
        super().__init__(message)
        self.execution_result = execution_result


class ConversationActivity(BaseModel):
    """Sanitized execution summary suitable for a human room participant."""

    id: UUID
    response_message_id: UUID | None = None
    message_ids: list[UUID] = Field(default_factory=list[UUID])
    topic_id: UUID | None = None
    status: str
    effect_started: bool
    tools_used: list[str] = Field(default_factory=list)
    execution_time: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)
    process_started: bool = False
    created_at: datetime
    finished_at: datetime | None = None


class ConversationActivityPage(BaseModel):
    items: list[ConversationActivity]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    runtime: ConversationRuntimeEvent | None = None


class ConversationActivityInteraction(BaseModel):
    """One user-safe step from a persisted agent execution trace."""

    sequence: int = Field(ge=0)
    kind: Literal["thinking", "tool_call", "ai_message", "error"]
    content: str = Field(default="", max_length=40_000)
    tool_name: str | None = Field(default=None, max_length=200)
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    result: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    success: bool = True
    execution_time: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)


class ConversationActivityDetail(BaseModel):
    """Sanitized AIResult projection visible to an authorized room participant."""

    id: UUID
    status: str
    success: bool
    execution_time: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)
    result: str = Field(default="", max_length=100_000)
    tools_used: list[str] = Field(default_factory=list[str])
    interactions: list[ConversationActivityInteraction] = Field(
        default_factory=list[ConversationActivityInteraction]
    )
    created_at: datetime
    finished_at: datetime | None = None


class ConversationTask(TaskRead):
    """One Task in the transitive work tree started by a conversation."""

    tree_parent_id: UUID | None = None
    directly_linked: bool = False


class ConversationTaskTree(BaseModel):
    """One recent-first page of the Task tree for one Messenger room."""

    items: list[ConversationTask] = Field(default_factory=list[ConversationTask])
    total: int = Field(ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=500)


class ConversationDocument(BaseModel):
    """One mutable working document referenced by visible conversation work."""

    id: UUID
    uri: str
    label: str = Field(default="", max_length=500)
    revision: int | None = Field(default=None, ge=1)
    source_task_id: UUID | None = None
    updated_at: datetime | None = None


class ConversationDocumentList(BaseModel):
    items: list[ConversationDocument] = Field(default_factory=list[ConversationDocument])
    total: int = Field(ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=500)


class ConversationProcessList(BaseModel):
    items: list[ProcessRunRead] = Field(default_factory=list[ProcessRunRead])
    total: int = Field(ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=500)


class ConversationController(Protocol):
    """Concrete low-latency controller implemented outside the domain."""

    async def run(self, turn: ConversationTurn) -> ConversationOutcome: ...


__all__ = [
    "ConversationController",
    "ConversationDocument",
    "ConversationDocumentList",
    "ConversationExecutionError",
    "ConversationActivity",
    "ConversationActivityDetail",
    "ConversationActivityInteraction",
    "ConversationActivityPage",
    "ConversationTask",
    "ConversationTaskTree",
    "ConversationOutcome",
    "ConversationProgressPublisher",
    "ConversationProgressResetter",
    "ConversationProcessList",
    "ConversationRuntimeEvent",
    "ConversationTurn",
    "BackgroundTaskAdmission",
    "FreshnessGuard",
    "public_ai_message",
    "public_ai_result",
]
