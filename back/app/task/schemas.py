from core.util import normalize_html
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List, Any, Dict, Literal
from uuid import UUID
from datetime import datetime
from .models import TaskStatus
from app.agent.contracts import TaskMessage
from app.agent.contracts import ExecutionEffort, ForcedRoute, ReasoningEffort

CoordinationType = Literal["await_reply"]


class TaskBudget(BaseModel):
    """Optional admission limits; recorded usage and reservations are estimates."""

    enabled: bool
    scope: Literal["task_tree", "goal"]
    provider_hard_cap: bool = False
    recorded_tokens: int
    recorded_cost: float
    active_phases: int
    reserved_tokens: int
    reserved_cost: float
    elapsed_seconds: float
    max_tokens: int | None
    max_cost: float | None
    max_seconds: float | None
    remaining_tokens: int | None
    remaining_cost: float | None
    remaining_seconds: float | None
    observed_at: datetime

AWAIT_KEY = "awaiting_reply"
RESOLVED_BY_KEY = "resolved_by_task_id"


# Task schemas

class TaskBase(BaseModel):
    """Base task schema."""
    label: str = Field(..., max_length=400)
    objective: Optional[str] = None
    status: TaskStatus = TaskStatus.CREATE
    paused: bool = False
    ai: bool = False
    feedback: Optional[str] = None
    cost: float = Field(default=0.0, ge=0.0)
    effort: ExecutionEffort = "standard"
    forced_route: Optional[ForcedRoute] = None
    forced_effort: Optional[ExecutionEffort] = None
    reasoning_effort_override: Optional[ReasoningEffort] = None
    auto_approve: bool = False
    agent_id: Optional[int] = None
    goal_id: Optional[UUID] = None
    requester_agent_id: Optional[int] = None
    messenger_connection_id: Optional[int] = Field(default=None, gt=0)
    message_platform: Optional[str] = Field(default=None, max_length=100)
    message_group_id: Optional[str] = Field(default=None, max_length=512)
    dispatch_result: Optional[Dict[str, Any]] = None
    briefing_result: Optional[Dict[str, Any]] = None
    execution_result: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    messages: Optional[List[TaskMessage]] = None
    parent_id: Optional[UUID] = None
    source_task_id: Optional[UUID] = None
    plan: Optional[Dict[str, Any]] = None


class TaskCreate(TaskBase):
    """Task creation schema."""
    topic_id: Optional[UUID] = None


    @field_validator("objective")
    @classmethod
    def validate_editorial_html(cls, value: str | None) -> str | None:
        return normalize_html(value) if value is not None else None


class TaskUpdate(BaseModel):
    """Fields a human may edit through the generic API.

    Phases, pauses, traces, costs, links, and checkpoints are controlled exclusively by
    explicit commands and internal engine services.
    """

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    label: Optional[str] = Field(default=None, max_length=400)
    objective: Optional[str] = None
    forced_route: Optional[ForcedRoute] = None
    forced_effort: Optional[ExecutionEffort] = None
    reasoning_effort_override: Optional[ReasoningEffort] = None
    auto_approve: Optional[bool] = None
    agent_id: Optional[int] = None
    topic_id: Optional[UUID] = None


    @field_validator("objective")
    @classmethod
    def validate_editorial_html(cls, value: str | None) -> str | None:
        return normalize_html(value) if value is not None else None


class TaskCommand(BaseModel):
    """Shared precondition for explicit mutating commands."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class Task(TaskBase):
    objective_media_type: str = "text/html"
    content_profile: str = "rich-text"
    content_profile_version: int = 1
    """Complete task API response schema."""
    id: UUID
    messenger_message_id: Optional[UUID] = None
    requester_user_id: Optional[int] = None
    topic_id: Optional[UUID] = None
    contact_memory_item_id: Optional[UUID] = None
    revision: int = 1
    created_at: Optional[datetime] = None
    created_by: Optional[int] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[int] = None
    coordination_type: Optional[CoordinationType] = None
    is_coordination: bool = False
    execution_expected: bool = True
    resolved_by_task_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("revision", mode="before")
    @classmethod
    def default_unpersisted_revision(cls, value: Any) -> int:
        """Transient ORM objects in tests have not received their SQL default yet."""
        return int(value or 1)

    @model_validator(mode="after")
    def derive_coordination_fields(self) -> "Task":
        data = self.data if isinstance(self.data, dict) else {}
        if isinstance(data.get(AWAIT_KEY), dict):
            self.coordination_type = "await_reply"
            self.is_coordination = True
            self.execution_expected = False
            raw_resolved_by = data.get(RESOLVED_BY_KEY)
            if raw_resolved_by:
                try:
                    self.resolved_by_task_id = UUID(str(raw_resolved_by))
                except (TypeError, ValueError):
                    self.resolved_by_task_id = None
        return self


class TaskOverview(BaseModel):
    """Status totals for every task matching the current list filters."""

    running: int = 0
    completed: int = 0
    paused: int = 0
    errors: int = 0


class TaskPage(BaseModel):
    """Paginated task-list response."""
    items: List[Task]
    total: int
    summary: TaskOverview


class TaskWithAssignments(Task):
    """Task schema with assignments."""
    pass

    model_config = ConfigDict(from_attributes=True)


class TaskFull(Task):
    """Complete task schema with flat relationships and no nested tree."""

    model_config = ConfigDict(from_attributes=True)
