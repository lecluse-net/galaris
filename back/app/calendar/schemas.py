"""HTTP and tool contracts for calendar configuration and events."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def _valid_temporal_range(start: datetime | date, end: datetime | date) -> bool:
    start_is_datetime = isinstance(start, datetime)
    end_is_datetime = isinstance(end, datetime)
    if start_is_datetime != end_is_datetime:
        return False
    return end > start


def validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown IANA timezone") from exc


class CalendarFeedCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=200)
    owner_label: str | None = Field(default=None, max_length=200)
    source_kind: Literal["internal"] = "internal"
    timezone: str = "Europe/Paris"
    actions_enabled: bool = True
    active: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> "CalendarFeedCreate":
        validate_timezone(self.timezone)
        return self


class CalendarFeedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    owner_label: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    actions_enabled: bool | None = None


class CalendarFeedRead(BaseModel):
    @computed_field
    @property
    def resource_uri(self) -> str:
        return f"galaris://calendar/{self.id}"

    id: int
    connection_id: int
    agent_id: int
    label: str
    tool_label: str = ""
    owner_label: str | None
    source_kind: Literal["internal", "ical", "caldav", "google", "microsoft", "icloud"] = "caldav"
    timezone: str = "Europe/Paris"
    writable: bool = False
    initialized: bool = False
    actions_enabled: bool = True
    is_default: bool = False
    origin: str
    url_configured: bool = True
    username_configured: bool
    password_configured: bool
    active: bool
    last_synced_at: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    sync_interval_hours: int = 2
    next_sync_at: datetime | None = None
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
    sync_run_id: UUID | None = None
    events_seen: int = Field(ge=0)
    next_events: list[CalendarConnectionEvent] = Field(
        default_factory=list[CalendarConnectionEvent], max_length=3
    )


class CalendarEventRead(BaseModel):
    contact_id: UUID | None = None
    source_kind: Literal["calendar", "memory"] = "calendar"
    source_uri: str | None = None
    informational: bool = False
    temporal: dict[str, int | None] | None = None
    event_id: UUID | None = None
    occurrence_id: UUID | None = None
    recurrence_key: str = ""
    revision: int = 1
    recurring: bool = False
    sync_state: Literal["local", "synced", "pending", "conflict"] = "local"
    calendar_id: int
    calendar_label: str
    uid: str
    summary: str
    description: str = ""
    location: str = ""
    start: datetime
    end: datetime
    all_day: bool = False
    start_date: date | None = None
    end_date: date | None = None
    timezone_name: str = "UTC"
    status: str = ""
    transparent: bool = False
    untrusted_content: bool = True


CalendarReminderState = Literal["scheduled", "cancelled", "skipped", "pending", "dispatch_error", "queued", "running", "waiting", "paused", "done", "error", "unavailable"]


class CalendarReminderRead(BaseModel):
    id: UUID
    calendar_id: int
    calendar_label: str
    event_uid: str
    event_summary: str
    reminder_at: datetime
    dispatch_status: str
    task_uri: str | None = None
    task_status: str | None = None
    state: CalendarReminderState
    treated: bool = False
    event_id: UUID | None = None
    recurrence_key: str = ""
    action_key: str = ""
    reason: str | None = None


class CalendarReminderPage(BaseModel):
    items: list[CalendarReminderRead]
    total: int


class CalendarOccurrenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    recurrence_key: str = Field(max_length=100)


class CalendarExecutionSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: int = Field(gt=0)
    occurrences: list[CalendarOccurrenceSelection] = Field(min_length=1, max_length=500)


class CalendarExecutionSummary(CalendarOccurrenceSelection):
    total: int = 0
    states: dict[CalendarReminderState, int] = Field(default_factory=dict[CalendarReminderState, int])


class CalendarAvailability(BaseModel):
    start: datetime
    end: datetime
    available: bool | None
    complete: bool = True
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
    contact_id: UUID | None = None
    reminder_minutes_before: int | None = Field(default=None, ge=0, le=525_600)
    timezone: str = "Europe/Paris"
    rrule: str | None = Field(default=None, max_length=2000)
    rdates: list[datetime | date] = Field(default_factory=list[datetime | date], max_length=1000)
    exdates: list[datetime | date] = Field(default_factory=list[datetime | date], max_length=1000)

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarEventCreate":
        if not _valid_temporal_range(self.start, self.end):
            raise ValueError("start and end must use the same type, with end after start")
        validate_timezone(self.timezone)
        if isinstance(self.start, datetime) and (self.start.tzinfo is None or not isinstance(self.end, datetime) or self.end.tzinfo is None):
            raise ValueError("Timed events require explicit timezone offsets")
        return self


class CalendarEventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=1_000)
    start: datetime | date | None = None
    end: datetime | date | None = None
    reminder_minutes_before: int | None = Field(default=None, ge=0, le=525_600)
    clear_reminder: bool = False
    expected_revision: int = Field(ge=1)
    contact_id: UUID | None = None
    clear_contact: bool = False
    scope: Literal["series", "occurrence", "following"] = "series"
    recurrence_key: str | None = Field(default=None, max_length=100)
    rrule: str | None = Field(default=None, max_length=2000)
    clear_recurrence: bool = False
    timezone: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarEventUpdate":
        if self.clear_contact and self.contact_id is not None:
            raise ValueError("Supply contact_id or clear_contact, not both")
        if self.start is not None and self.end is not None and not _valid_temporal_range(self.start, self.end):
            raise ValueError("start and end must use the same type, with end after start")
        if self.scope != "series" and not self.recurrence_key:
            raise ValueError("An occurrence identity is required for this scope")
        for value in (self.start, self.end):
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("Timed events require explicit timezone offsets")
        if self.timezone:
            validate_timezone(self.timezone)
        return self


class CalendarMutationReceipt(BaseModel):
    contact_id: UUID | None = None
    event_id: UUID | None = None
    revision: int = 1
    sync_state: Literal["local", "pending", "synced", "conflict"] = "local"
    calendar_id: int
    uid: str
    state: Literal["created", "updated", "deleted"]


class CalendarEventWindow(BaseModel):
    items: list[CalendarEventRead]
    total: int
    complete: bool
    stale_calendar_ids: list[int] = Field(default_factory=list[int])


class CalendarActionFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recurrence_key: str | None = Field(default=None, max_length=100)
    anchor: Literal["start", "end"] = "start"
    offset_minutes: int = Field(default=0, ge=-525600, le=525600)
    instructions: str = Field(min_length=1, max_length=20000)
    active: bool = True
    max_lateness_minutes: int = Field(default=60, ge=0, le=10080)


class CalendarActionWrite(CalendarActionFields):
    expected_revision: int | None = Field(default=None, ge=1)
    request_key: UUID | None = None


class CalendarActionRead(CalendarActionFields):
    id: UUID
    event_id: UUID
    revision: int


class CalendarEventDelete(BaseModel):
    expected_revision: int = Field(ge=1)
    scope: Literal["series", "occurrence", "following"] = "series"
    recurrence_key: str | None = Field(default=None, max_length=100)


class CalendarConflictResolution(BaseModel):
    expected_revision: int = Field(ge=1)
    choice: Literal["local", "remote"]


class CalendarConflictRead(BaseModel):
    event_id: UUID
    uid: str
    revision: int
    local_deleted: bool
    remote_deleted: bool
    local_ical: str
    remote_ical: str | None


class CalendarAlarmRead(BaseModel):
    key: str
    at: datetime
    anchor: Literal["start", "end", "absolute"]
    offset_seconds: int | None


class CalendarEventDetail(BaseModel):
    contact_id: UUID | None = None
    event_id: UUID
    calendar_id: int
    uid: str
    revision: int
    timezone: str
    summary: str
    description: str
    location: str
    start: datetime
    end: datetime
    all_day: bool
    start_date: date | None = None
    end_date: date | None = None
    recurring: bool
    deleted: bool = False
    parent_event_id: UUID | None = None
    rrule: str | None = None
    rdates: list[datetime | date] = Field(default_factory=list[datetime | date])
    exdates: list[datetime | date] = Field(default_factory=list[datetime | date])
    alarms: list[CalendarAlarmRead] = Field(default_factory=list[CalendarAlarmRead])
    sync_state: Literal["local", "pending", "synced", "conflict"] = "local"
    ical: str


class CalendarEventHistoryRead(BaseModel):
    contact_id: UUID | None = None
    revision: int
    deleted: bool
    created_at: datetime
    ical: str


class CalendarSyncStepRead(BaseModel):
    stage: str
    started_at: datetime
    finished_at: datetime | None = None


class CalendarSyncProgressRead(BaseModel):
    calendar_changed: bool = False
    steps: list[CalendarSyncStepRead] = Field(default_factory=list[CalendarSyncStepRead])
    server_reached: bool = False
    network_phase: str | None = None
    http_requests: int = 0
    last_http_status: int | None = None
    calendars: int = 0
    downloaded: int = 0
    download_total: int | None = None
    applied: int = 0
    apply_total: int | None = None
    uploaded: int = 0
    upload_total: int | None = None
    upload_succeeded: int = 0
    conflicts: int = 0
    deleted: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    transfer_completed: int = 0
    transfer_total: int | None = None


class CalendarSyncRunRead(BaseModel):
    id: UUID
    stage: str
    state: str
    operation_id: UUID | None
    error_category: str | None
    http_status: int | None
    error_location: str | None
    started_at: datetime
    finished_at: datetime | None
    progress: CalendarSyncProgressRead = Field(default_factory=CalendarSyncProgressRead)


class CalendarExecutionRelaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_event_revision: int = Field(ge=1)


class CalendarExecutionReceipt(BaseModel):
    id: UUID
    task_uri: str | None
    state: str


__all__ = [
    "CalendarReminderRead",
    "CalendarReminderPage",
    "CalendarReminderState",
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
