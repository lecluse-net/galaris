"""Global and per-Goal weekly-schedule controls for the Goal runner."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from pydantic import ValidationError

from core import websocket
from core.params import Params, params_service

from .models import Goal
from .schemas import (
    GoalScheduleWindow,
    GoalScheduleConfig,
    GoalSettingsConfig,
    GoalSettingsRead,
    GoalSettingsUpdate,
)


class GoalSettingsUnavailableError(RuntimeError):
    """Raised when deployment reference data has not yet been synchronized."""


def _timezone() -> tuple[str, ZoneInfo]:
    timezone_name = (os.getenv("TZ") or "UTC").strip() or "UTC"
    try:
        return timezone_name, ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid application timezone {!r}; Goal schedule uses UTC", timezone_name)
        return "UTC", ZoneInfo("UTC")


def _clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


def _window_interval(
    local_date: date,
    window: GoalScheduleWindow,
    local_zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    start = datetime.combine(local_date, _clock(window.start_time), tzinfo=local_zone)
    end_date = local_date + timedelta(days=window.end_time <= window.start_time)
    end = datetime.combine(end_date, _clock(window.end_time), tzinfo=local_zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _schedule_state(
    config: GoalScheduleConfig,
    *,
    now: datetime,
    local_zone: ZoneInfo,
) -> tuple[bool, datetime | None]:
    """Return current schedule availability and the next opening in UTC."""

    reference = now.astimezone(timezone.utc)
    local_now = reference.astimezone(local_zone)
    local_today = local_now.date()

    for window in config.schedule:
        for day_offset in (-1, 0):
            start_date = local_today + timedelta(days=day_offset)
            if start_date.weekday() not in window.weekdays:
                continue
            start, end = _window_interval(start_date, window, local_zone)
            if start <= reference < end:
                return True, None

    candidates: list[datetime] = []
    for day_offset in range(8):
        start_date = local_today + timedelta(days=day_offset)
        for window in config.schedule:
            if start_date.weekday() not in window.weekdays:
                continue
            start, _ = _window_interval(start_date, window, local_zone)
            if start > reference:
                candidates.append(start)
    return False, min(candidates, default=None)


def evaluate_settings(
    config: GoalSettingsConfig,
    *,
    now: datetime | None = None,
) -> GoalSettingsRead:
    """Evaluate durable settings against one timezone-aware instant."""

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("Goal schedule evaluation requires a timezone-aware datetime")
    timezone_name, local_zone = _timezone()

    if config.globally_paused:
        return GoalSettingsRead(
            **config.model_dump(),
            timezone=timezone_name,
            is_active=False,
            inactive_reason="GLOBAL_PAUSE",
        )
    if not config.schedule_enabled:
        return GoalSettingsRead(
            **config.model_dump(),
            timezone=timezone_name,
            is_active=True,
        )

    is_active, next_active_at = _schedule_state(
        config,
        now=reference,
        local_zone=local_zone,
    )
    return GoalSettingsRead(
        **config.model_dump(),
        timezone=timezone_name,
        is_active=is_active,
        inactive_reason=None if is_active else "OUTSIDE_SCHEDULE",
        next_active_at=next_active_at,
    )


def evaluate_goal_schedule(
    source: Goal | GoalScheduleConfig,
    *,
    now: datetime | None = None,
) -> tuple[bool, datetime | None]:
    """Evaluate one Goal's optional restriction, after the global gate passed."""

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("Goal schedule evaluation requires a timezone-aware datetime")
    if not source.schedule_enabled:
        return True, None
    try:
        config = GoalScheduleConfig.model_validate(
            {
                "schedule_enabled": source.schedule_enabled,
                "schedule": source.schedule,
            }
        )
    except ValidationError as exc:
        logger.error("Invalid schedule for Goal; scheduled activity is blocked: {}", exc)
        return False, None
    _, local_zone = _timezone()
    return _schedule_state(config, now=reference, local_zone=local_zone)


def is_goal_processing_allowed(
    source: Goal | GoalScheduleConfig,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the current instant belongs to one Goal's weekly schedule."""

    return evaluate_goal_schedule(source, now=now)[0]


def next_schedule_at(
    source: Goal | GoalScheduleConfig,
    config: GoalSettingsConfig,
    *,
    not_before: datetime,
) -> datetime | None:
    """Find the first instant in both weekly schedules, at or after eligibility."""

    if not_before.tzinfo is None or not_before.utcoffset() is None:
        raise ValueError("Goal scheduling requires a timezone-aware datetime")
    if config.globally_paused:
        return None
    try:
        individual = GoalScheduleConfig.model_validate(
            {"schedule_enabled": source.schedule_enabled, "schedule": source.schedule}
        )
    except ValidationError as exc:
        logger.error("Invalid schedule for Goal; next cycle is unavailable: {}", exc)
        return None
    reference = not_before.astimezone(timezone.utc)
    _, local_zone = _timezone()
    local_today = reference.astimezone(local_zone).date()
    # Two weekly recurrences also cover an opening lost to the spring clock change.
    horizon = datetime.combine(local_today + timedelta(days=15), time(), tzinfo=local_zone)

    def intervals(schedule: GoalScheduleConfig) -> list[tuple[datetime, datetime]]:
        if not schedule.schedule_enabled:
            return [(reference, horizon.astimezone(timezone.utc))]
        result: list[tuple[datetime, datetime]] = []
        for offset in range(-1, 15):
            start_date = local_today + timedelta(days=offset)
            for window in schedule.schedule:
                if start_date.weekday() not in window.weekdays:
                    continue
                start, end = _window_interval(start_date, window, local_zone)
                if max(start, reference) < end:
                    result.append((max(start, reference), end))
        return sorted(result)

    common, own = intervals(config), intervals(individual)
    common_index = own_index = 0
    while common_index < len(common) and own_index < len(own):
        common_start, common_end = common[common_index]
        own_start, own_end = own[own_index]
        opening = max(common_start, own_start)
        if opening < min(common_end, own_end):
            return opening
        if common_end <= own_end:
            common_index += 1
        else:
            own_index += 1
    return None


def projected_next_cycle_at(goal: Goal, config: GoalSettingsConfig) -> datetime | None:
    """Keep durable eligibility intact while announcing an executable scheduled time."""

    if goal.manual_run_requested_at is not None:
        return goal.manual_run_requested_at
    if goal.next_cycle_at is None:
        return None
    if not config.globally_paused and not config.schedule_enabled and not goal.schedule_enabled:
        return goal.next_cycle_at
    return next_schedule_at(
        goal, config, not_before=max(goal.next_cycle_at, datetime.now(timezone.utc))
    )


def _decode(raw: str | None) -> GoalSettingsConfig:
    if not raw:
        return GoalSettingsConfig()
    try:
        parsed: object = json.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("Goal runtime settings must be a JSON object")
        return GoalSettingsConfig.model_validate(cast(dict[str, object], parsed))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error("Invalid persisted Goal runtime settings; safe defaults applied: {}", exc)
        return GoalSettingsConfig()


async def get_config() -> GoalSettingsConfig:
    raw = await params_service.get_or_default(Params.GOAL_RUNTIME_SETTINGS)
    return _decode(raw)


async def get_settings(*, now: datetime | None = None) -> GoalSettingsRead:
    return evaluate_settings(await get_config(), now=now)


async def is_processing_allowed(*, now: datetime | None = None) -> bool:
    return (await get_settings(now=now)).is_active


async def update_settings(data: GoalSettingsUpdate) -> GoalSettingsRead:
    current = await get_config()
    merged = {
        **current.model_dump(mode="json"),
        **data.model_dump(mode="json", exclude_unset=True),
    }
    config = GoalSettingsConfig.model_validate(merged)
    saved = await params_service.set(
        Params.GOAL_RUNTIME_SETTINGS,
        config.model_dump_json(),
    )
    if not saved:
        # Dataset synchronization runs in a separate process. Refresh a possibly stale worker
        # cache once before reporting that the deployment data is genuinely missing.
        await params_service.refresh()
        saved = await params_service.set(
            Params.GOAL_RUNTIME_SETTINGS,
            config.model_dump_json(),
        )
    if not saved:
        raise GoalSettingsUnavailableError(
            "Goal runtime settings are not initialized; run make sync-db in development "
            "or make update in production."
        )

    result = evaluate_settings(config)
    await websocket.emit(
        "goal_settings",
        "update",
        result.model_dump(mode="json"),
        None,
    )
    from .schemas import GoalRuntimeRead
    await websocket.emit("goal_runtime", "update", GoalRuntimeRead.model_validate(result.model_dump()).model_dump(mode="json"), None)
    logger.info(
        "Goal runtime settings updated: paused={}, schedule_enabled={}, windows={}",
        config.globally_paused,
        config.schedule_enabled,
        len(config.schedule),
    )
    return result
