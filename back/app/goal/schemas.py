"""API and structured-judgement contracts for Goals."""

from __future__ import annotations
from core.util import normalize_html, visible_text

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    GoalCycleTriggerKind,
    GoalCycleStatus,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)


GoalWeekday = Annotated[int, Field(ge=0, le=6)]
_GOAL_CLOCK_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


def _required_html(value: str) -> str:
    normalized = normalize_html(value)
    if not normalized:
        raise ValueError("Editorial HTML must contain visible content.")
    return normalized


HtmlBody = Annotated[str, AfterValidator(_required_html)]


def _tracking_html(value: str) -> str:
    normalized = normalize_html(value)
    if len(normalized) > 120_000 or len(visible_text(normalized)) > 30_000:
        raise ValueError("Goal tracking exceeds its serialized or visible text limit.")
    return normalized


TrackingBody = Annotated[str, AfterValidator(_tracking_html)]


class GoalScheduleWindow(BaseModel):
    """One local-time weekly window, optionally shared by several weekdays."""

    model_config = ConfigDict(extra="forbid")

    weekdays: list[GoalWeekday] = Field(min_length=1, max_length=7)
    start_time: str = Field(pattern=_GOAL_CLOCK_PATTERN)
    end_time: str = Field(pattern=_GOAL_CLOCK_PATTERN)

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, values: list[int]) -> list[int]:
        return sorted(set(values))

    @model_validator(mode="after")
    def reject_zero_length_window(self) -> "GoalScheduleWindow":
        if self.start_time == self.end_time:
            raise ValueError("A Goal schedule window must have different start and end times")
        return self


class GoalScheduleConfig(BaseModel):
    """Weekly schedule attached to the global runner or one Goal."""

    model_config = ConfigDict(extra="forbid")

    schedule_enabled: bool = False
    schedule: list[GoalScheduleWindow] = Field(default_factory=lambda: [], max_length=50)

    @model_validator(mode="after")
    def require_an_enabled_window(self) -> "GoalScheduleConfig":
        if self.schedule_enabled and not self.schedule:
            raise ValueError("At least one schedule window is required when scheduling is enabled")
        return self


class GoalSettingsConfig(GoalScheduleConfig):
    """Durable global Goal runner pause and common availability window."""

    globally_paused: bool = False


class GoalSettingsUpdate(BaseModel):
    """Partial update of the global Goal runner controls."""

    model_config = ConfigDict(extra="forbid")

    globally_paused: bool | None = None
    schedule_enabled: bool | None = None
    schedule: list[GoalScheduleWindow] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def reject_empty_or_null_update(self) -> "GoalSettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one Goal setting must be provided")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class GoalSettingsRead(GoalSettingsConfig):
    """Goal settings enriched with their effective state at response time."""

    timezone: str
    is_active: bool
    inactive_reason: Literal["GLOBAL_PAUSE", "OUTSIDE_SCHEDULE"] | None = None
    next_active_at: datetime | None = None


class GoalAgentReferrerInput(BaseModel):
    """Legacy service input retained only for historical Goal test fixtures."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["AGENT"]
    agent_id: int = Field(gt=0)


class GoalMessengerReferrerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["MESSENGER"]
    connection_id: int = Field(gt=0)
    user_id: str = Field(min_length=1, max_length=400)
    display_name: str = Field(min_length=1, max_length=500)

    @field_validator("user_id", "display_name")
    @classmethod
    def strip_contact_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped


GoalReferrerInput = Annotated[
    GoalAgentReferrerInput | GoalMessengerReferrerInput,
    Field(discriminator="type"),
]


class GoalReferrerRead(BaseModel):
    type: GoalReferrerType
    display_name: str
    agent_id: int | None = None
    agent_code: str | None = None
    connection_id: int | None = None
    user_id: str | None = None
    platform: str | None = None


class GoalCreate(GoalScheduleConfig):
    title: str = Field(min_length=1, max_length=400)
    description: HtmlBody = Field(min_length=1)
    agent_id: int = Field(gt=0)
    referrer: GoalReferrerInput
    cycle_delay_seconds: int | None = Field(default=3600, ge=0)
    parent_goal_id: UUID | None = None
    referrer_max_reminders: int = Field(default=1, ge=0)
    active: bool = True

    @field_validator("title", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped

    @model_validator(mode="after")
    def require_one_automatic_trigger_mode(self) -> "GoalCreate":
        has_temporal_trigger = self.cycle_delay_seconds is not None
        has_relational_trigger = self.parent_goal_id is not None
        if has_temporal_trigger == has_relational_trigger:
            raise ValueError(
                "A Goal must use exactly one automatic trigger: frequency or parent Goal"
            )
        if has_relational_trigger and self.schedule_enabled:
            raise ValueError("A parent-driven Goal cannot define its own time window")
        return self


class GoalApiCreate(GoalScheduleConfig):
    """Public HTTP contract: every newly assigned Goal has a human referrer."""

    title: str = Field(min_length=1, max_length=400)
    description: HtmlBody = Field(min_length=1)
    agent_id: int = Field(gt=0)
    referrer: GoalMessengerReferrerInput
    cycle_delay_seconds: int | None = Field(default=3600, ge=0)
    parent_goal_id: UUID | None = None
    referrer_max_reminders: int = Field(default=1, ge=0)
    active: bool = True

    @model_validator(mode="after")
    def validate_goal_create(self) -> "GoalApiCreate":
        GoalCreate.model_validate(self.model_dump())
        return self


class GoalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=400)
    description: HtmlBody | None = Field(default=None, min_length=1)
    tracking_content: TrackingBody | None = Field(default=None, max_length=120_000)
    agent_id: int | None = Field(default=None, gt=0)
    referrer: GoalReferrerInput | None = None
    cycle_delay_seconds: int | None = Field(default=None, ge=0)
    parent_goal_id: UUID | None = None
    referrer_max_reminders: int | None = Field(default=None, ge=0)
    schedule_enabled: bool | None = None
    schedule: list[GoalScheduleWindow] | None = Field(default=None, max_length=50)

    @field_validator("title", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "GoalUpdate":
        for field_name in (
            "title",
            "description",
            "tracking_content",
            "agent_id",
            "referrer",
            "referrer_max_reminders",
            "schedule_enabled",
            "schedule",
        ):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class GoalApiUpdate(BaseModel):
    """Public HTTP contract: a referrer change can only select a human."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=400)
    description: HtmlBody | None = Field(default=None, min_length=1)
    tracking_content: TrackingBody | None = Field(default=None, max_length=120_000)
    agent_id: int | None = Field(default=None, gt=0)
    referrer: GoalMessengerReferrerInput | None = None
    cycle_delay_seconds: int | None = Field(default=None, ge=0)
    parent_goal_id: UUID | None = None
    referrer_max_reminders: int | None = Field(default=None, ge=0)
    schedule_enabled: bool | None = None
    schedule: list[GoalScheduleWindow] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_goal_update(self) -> "GoalApiUpdate":
        GoalUpdate.model_validate(self.model_dump(exclude_unset=True))
        return self


class GoalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class GoalRead(GoalScheduleConfig):
    id: UUID
    memory_item_id: UUID | None = None
    revision: int
    title: str
    description_document_id: UUID
    tracking_document_id: UUID
    description: str
    tracking_content: str
    content_media_type: str = "text/html"
    content_profile: str = "rich-text"
    content_profile_version: int = 1
    agent_id: int
    requester_user_id: int | None = None
    agent_name: str = ""
    agent_code: str = ""
    referrer: GoalReferrerRead | None = None
    cycle_delay_seconds: int | None
    parent_goal_id: UUID | None = None
    parent_title: str | None = None
    children_count: int = 0
    referrer_max_reminders: int
    status: GoalStatus
    pause_reason: str | None
    next_cycle_at: datetime | None
    completed_at: datetime | None
    last_error: str | None
    cycle_count: int = 0
    task_cost: float = 0.0
    evaluation_cost: float = 0.0
    total_cost: float = 0.0
    current_task_id: UUID | None = None
    last_task_finished_at: datetime | None = None
    last_verdict: GoalVerdict | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    updated_by: int | None = None

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class GoalCycleRead(BaseModel):
    id: UUID
    memory_item_id: UUID | None = None
    goal_id: UUID
    sequence: int
    trigger_kind: GoalCycleTriggerKind
    source_cycle_id: UUID | None
    task_id: UUID | None
    task_label: str | None = None
    task_status: str | None = None
    task_cost: float = 0.0
    status: GoalCycleStatus
    verdict: GoalVerdict | None
    reason: str | None
    progress_changed: bool | None
    progress_summary: str | None
    evidence: list[str] = Field(default_factory=list)
    task_finished_at: datetime | None
    judge_cost: float
    judge_llm_id: int | None
    judge_attempt_count: int
    judge_started_at: datetime | None
    judge_finished_at: datetime | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GoalDetail(GoalRead):
    pass


class GoalTreeNode(BaseModel):
    id: UUID
    parent_goal_id: UUID | None
    title: str
    agent_id: int
    agent_name: str
    agent_code: str
    status: GoalStatus
    cycle_delay_seconds: int | None
    next_cycle_at: datetime | None
    children_count: int = 0


class GoalTreePage(BaseModel):
    items: list[GoalTreeNode] = Field(default_factory=lambda: [])
    total: int


class GoalCyclePage(BaseModel):
    items: list[GoalCycleRead] = Field(default_factory=lambda: [])
    total: int
    page: int
    page_size: int


class GoalSummary(BaseModel):
    active: int = 0
    paused: int = 0
    completed: int = 0
    errors: int = 0
    total_cost: float = 0.0


class GoalPage(BaseModel):
    items: list[GoalRead]
    total: int
    summary: GoalSummary
    tracking_llm_configured: bool


class MessengerReferrerOption(BaseModel):
    connection_id: int
    tool_id: int
    platform: str
    user_id: str
    display_name: str
    is_current_user: bool = False


class GoalProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: bool
    summary: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("evidence")
    @classmethod
    def compact_evidence(cls, values: list[str]) -> list[str]:
        return [value.strip()[:1000] for value in values if value.strip()]

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Progress summary must not be empty")
        return stripped


class GoalJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["CONTINUE", "STOP"]
    reason: str = Field(min_length=1, max_length=4000)
    progress: GoalProgress
    tracking_content: str = Field(min_length=1, max_length=120_000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Reason must not be empty")
        return stripped

    @field_validator("tracking_content")
    @classmethod
    def strip_tracking_content(cls, value: str) -> str:
        normalized = normalize_html(value)
        if not normalized or len(visible_text(normalized)) > 30_000:
            raise ValueError("Goal tracking requires 1 to 30000 visible characters of HTML.")
        return normalized

    @model_validator(mode="after")
    def require_stop_evidence(self) -> "GoalJudgement":
        if self.action == "STOP" and not self.progress.evidence:
            raise ValueError("STOP requires at least one observable evidence item")
        return self
