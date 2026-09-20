"""HTTP and tool contracts for calendar configuration and events."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


CalendarAccess = Literal["read", "write"]
CalendarAction = Literal["task", "process"]


def _valid_temporal_range(start: datetime | date, end: datetime | date) -> bool:
    start_is_datetime = isinstance(start, datetime)
    end_is_datetime = isinstance(end, datetime)
    if start_is_datetime != end_is_datetime:
        return False
    return end > start


class CalendarFeedCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=200)
    owner_label: str | None = Field(default=None, max_length=200)
    access_mode: CalendarAccess = "read"
    url: SecretStr
    username: SecretStr | None = None
    password: SecretStr | None = None
    active: bool = True
    trigger_on_start: bool = True
    trigger_on_alarm: bool = True
    action_kind: CalendarAction = "task"
    process_workflow_id: str | None = Field(default=None, max_length=255)
    action_instructions: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def validate_action(self) -> "CalendarFeedCreate":
        if self.action_kind == "process" and not (self.process_workflow_id or "").strip():
            raise ValueError("process_workflow_id is required for a process action")
        return self


class CalendarFeedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    owner_label: str | None = Field(default=None, max_length=200)
    access_mode: CalendarAccess | None = None
    url: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    clear_username: bool = False
    clear_password: bool = False
    active: bool | None = None
    trigger_on_start: bool | None = None
    trigger_on_alarm: bool | None = None
    action_kind: CalendarAction | None = None
    process_workflow_id: str | None = Field(default=None, max_length=255)
    action_instructions: str | None = Field(default=None, max_length=4_000)


class CalendarFeedRead(BaseModel):
    id: int
    connection_id: int
    agent_id: int
    label: str
    owner_label: str | None
    access_mode: CalendarAccess
    origin: str
    url_configured: bool = True
    username_configured: bool
    password_configured: bool
    active: bool
    trigger_on_start: bool
    trigger_on_alarm: bool
    action_kind: CalendarAction
    process_workflow_id: str | None
    action_instructions: str | None
    last_synced_at: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime | None


class CalendarConnectionEvent(BaseModel):
    uid: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool = False


class CalendarConnectionStatus(BaseModel):
    calendar_id: int
    ok: bool
    events_seen: int = Field(ge=0)
    writable_advertised: bool | None = None
    next_events: list[CalendarConnectionEvent] = Field(
        default_factory=list[CalendarConnectionEvent], max_length=3
    )


class CalendarEventRead(BaseModel):
    calendar_id: int
    calendar_label: str
    uid: str
    summary: str
    description: str = ""
    location: str = ""
    start: datetime
    end: datetime
    all_day: bool = False
    status: str = ""
    transparent: bool = False
    untrusted_content: bool = True


class CalendarAvailability(BaseModel):
    start: datetime
    end: datetime
    available: bool
    conflicts: list[CalendarEventRead] = Field(default_factory=list[CalendarEventRead])


class CalendarFreeSlot(BaseModel):
    start: datetime
    end: datetime
    timezone: str


class CalendarEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=20_000)
    location: str = Field(default="", max_length=1_000)
    start: datetime | date
    end: datetime | date
    uid: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarEventCreate":
        if not _valid_temporal_range(self.start, self.end):
            raise ValueError("start and end must use the same type, with end after start")
        return self


class CalendarEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=1_000)
    start: datetime | date | None = None
    end: datetime | date | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarEventUpdate":
        if self.start is not None and self.end is not None and not _valid_temporal_range(self.start, self.end):
            raise ValueError("start and end must use the same type, with end after start")
        return self


class CalendarMutationReceipt(BaseModel):
    calendar_id: int
    uid: str
    state: Literal["created", "updated", "deleted"]


__all__ = [
    "CalendarAction",
    "CalendarAccess",
    "CalendarConnectionEvent",
    "CalendarConnectionStatus",
    "CalendarAvailability",
    "CalendarEventCreate",
    "CalendarEventRead",
    "CalendarEventUpdate",
    "CalendarFeedCreate",
    "CalendarFeedRead",
    "CalendarFeedUpdate",
    "CalendarFreeSlot",
    "CalendarMutationReceipt",
]
