"""Partial local calendar constraints, independent of memory validity."""

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.util import local_timezone_name


class MemoryTemporalAnchor(BaseModel):
    """Unset components are wildcards; weekday uses ISO Monday=1, Sunday=7."""

    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=1, le=9999, strict=True)
    month: int | None = Field(default=None, ge=1, le=12, strict=True)
    day: int | None = Field(default=None, ge=1, le=31, strict=True)
    weekday: int | None = Field(default=None, ge=1, le=7, strict=True)
    hour: int | None = Field(default=None, ge=0, le=23, strict=True)
    minute: int | None = Field(default=None, ge=0, le=59, strict=True)
    timezone: str = Field(default_factory=local_timezone_name, max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone such as Europe/Paris.") from exc
        return value

    @model_validator(mode="after")
    def possible_calendar(self) -> "MemoryTemporalAnchor":
        if not any(getattr(self, field) is not None for field in COMPONENTS):
            raise ValueError("Provide a calendar component, or null for no temporality.")
        # A 400-year cycle covers every Gregorian leap-year/weekday combination.
        years = [self.year] if self.year is not None else range(2000, 2400)
        months = [self.month] if self.month is not None else range(1, 13)
        for year in years:
            for month in months:
                days = [self.day] if self.day is not None else range(1, 8)
                for day in days:
                    if day <= monthrange(year, month)[1] and (
                        self.weekday is None or date(year, month, day).isoweekday() == self.weekday
                    ):
                        return self
        raise ValueError("The calendar components never match a valid date.")


COMPONENTS = ("year", "month", "day", "weekday", "hour", "minute")


class MemoryTemporalWindow(BaseModel):
    start: datetime
    end: datetime
    timezone: str


class MemoryTemporalFilter(BaseModel):
    """An empty target uses server time, without changing current access rights."""

    model_config = ConfigDict(extra="forbid")

    target_at: datetime | None = None
    timezone: str = Field(default_factory=local_timezone_name, max_length=100)
    lookahead_hours: int | None = Field(default=None, ge=0, le=744, strict=True)

    @model_validator(mode="after")
    def resolve_target(self) -> "MemoryTemporalFilter":
        MemoryTemporalAnchor.valid_timezone(self.timezone)
        if self.target_at is None:
            return self
        target = self.target_at
        if not 2 <= target.year <= 9998:
            raise ValueError("Use a target year between 2 and 9998.")
        if target.utcoffset() is None:
            zone = ZoneInfo(self.timezone)
            candidates: set[datetime] = set()
            for fold in (0, 1):
                instant = target.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if instant.astimezone(zone).replace(tzinfo=None) == target:
                    candidates.add(instant)
            if len(candidates) != 1:
                raise ValueError("This local time is nonexistent or ambiguous; use UTC or an explicit UTC offset.")
            target = candidates.pop()
        self.target_at = target.astimezone(timezone.utc)
        return self

    def window(self, *, now: datetime, default_hours: int) -> MemoryTemporalWindow:
        start = self.target_at or now
        hours = default_hours if self.lookahead_hours is None else self.lookahead_hours
        return MemoryTemporalWindow(start=start, end=start + timedelta(hours=hours), timezone=self.timezone)


def next_match(anchor: MemoryTemporalAnchor, start: datetime, end: datetime) -> datetime | None:
    """First matching minute in an inclusive UTC window; an active minute returns start.

    Round-tripping both folds rejects nonexistent local times and preserves both
    occurrences of repeated times. Seconds are deliberately not a constraint.
    """
    if start.utcoffset() is None or end.utcoffset() is None or end < start:
        raise ValueError("Use an ordered, timezone-aware interval.")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    zone = ZoneInfo(anchor.timezone)
    local_start = start.astimezone(zone)
    if all(expected is None or actual == expected for actual, expected in (
        (local_start.year, anchor.year), (local_start.month, anchor.month),
        (local_start.day, anchor.day), (local_start.isoweekday(), anchor.weekday),
        (local_start.hour, anchor.hour), (local_start.minute, anchor.minute),
    )):
        return start
    current = local_start.date()
    last = end.astimezone(zone).date()
    while current <= last:
        if all(expected is None or actual == expected for actual, expected in (
            (current.year, anchor.year), (current.month, anchor.month),
            (current.day, anchor.day), (current.isoweekday(), anchor.weekday),
        )):
            candidates: list[datetime] = []
            for hour in [anchor.hour] if anchor.hour is not None else range(24):
                for minute in [anchor.minute] if anchor.minute is not None else range(60):
                    naive = datetime.combine(current, time(hour, minute))
                    for fold in (0, 1):
                        instant = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                        if instant.astimezone(zone).replace(tzinfo=None) != naive:
                            continue
                        if instant <= end and instant + timedelta(minutes=1) > start:
                            candidates.append(max(instant, start))
            if candidates:
                return min(candidates)
        if current == last:
            break
        current += timedelta(days=1)
    return None
