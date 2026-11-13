"""Human administration API for agent calendars."""

from __future__ import annotations
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope
from app.connection.facade import get_connection

from . import service, store
from .models import CalendarEvent
from core.database import get_db
from sqlalchemy import select
from .schemas import (
    CalendarConnectionStatus,
    CalendarFeedCreate,
    CalendarFeedRead,
    CalendarFeedUpdate,
    CalendarReminderPage,
    CalendarEventWindow, CalendarEventCreate, CalendarEventUpdate, CalendarEventDelete, CalendarMutationReceipt,
    CalendarActionWrite, CalendarActionRead,
    CalendarConflictResolution, CalendarConflictRead, CalendarEventDetail, CalendarEventHistoryRead, CalendarSyncRunRead,
    CalendarExecutionRelaunch, CalendarExecutionReceipt,
)


router = APIRouter(prefix="/calendars", tags=["calendars"])


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _invalid(exc: ValueError | PermissionError) -> HTTPException:
    code = status.HTTP_403_FORBIDDEN if isinstance(exc, PermissionError) else status.HTTP_409_CONFLICT if isinstance(exc, store.CalendarConflictError) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except LookupError as exc:
        raise _not_found(exc) from exc
    except (ValueError, PermissionError) as exc:
        raise _invalid(exc) from exc


async def _event_uid(calendar_id: int, event_id: UUID, *, deleted: bool = False) -> str:
    await _require_calendar_scope(calendar_id)
    statement = select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.calendar_id == calendar_id)
    if deleted:
        statement = statement.execution_options(include_historized=True)
    event = await get_db().scalar(statement)
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    return event.uid


async def _require_connection_scope(connection_id: int) -> None:
    connection = await get_connection(connection_id)
    scope = await current_management_scope()
    if connection is None or not scope.allows(connection.agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar connection not found",
        )


async def _require_calendar_scope(calendar_id: int) -> None:
    feed = await service.get_feed(calendar_id)
    if feed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar not found",
        )
    await _require_connection_scope(feed.connection_id)


@router.get("/connection-options")
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def connection_options() -> list[dict[str, object]]:
    scope = await current_management_scope()
    return await service.connection_options(scope.agent_ids)


@router.get("", response_model=list[CalendarFeedRead])
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def read_calendars(connection_id: int | None = Query(default=None, gt=0), agent_id: int | None = Query(default=None, gt=0)) -> list[CalendarFeedRead]:
    if connection_id is not None:
        await _require_connection_scope(connection_id)
    elif agent_id is None or not (await current_management_scope()).allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return await service.list_feeds(connection_id=connection_id, agent_id=agent_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.get("/reminders", response_model=CalendarReminderPage)
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def read_reminders(connection_id: int = Query(gt=0), skip: int = Query(default=0, ge=0),
                         limit: int = Query(default=50, ge=1, le=500), event_id: UUID | None = None,
                         recurrence_key: str | None = None) -> CalendarReminderPage:
    await _require_connection_scope(connection_id)
    try:
        return await service.list_reminders(connection_id, skip=skip, limit=limit, event_id=event_id, recurrence_key=recurrence_key)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.get("/events", response_model=CalendarEventWindow)
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def read_events(agent_id: int, start: datetime | None = None, end: datetime | None = None,
                      calendar_ids: list[int] | None = Query(default=None),
                      period: Literal["month", "week", "day", "next30"] = "month", month: str | None = None,
                      timezone_name: str = "Europe/Paris") -> CalendarEventWindow:
    if not (await current_management_scope()).allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    with _errors():
        lower, upper = service.date_window(period, month, timezone_name) if start is None and end is None else (start, end)
        if lower is None or upper is None:
            raise ValueError("Both start and end are required")
        return await service.event_window(agent_id, lower, upper, calendar_ids=calendar_ids)


@router.post("/{calendar_id}/events", response_model=CalendarMutationReceipt, status_code=201)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def create_event(calendar_id: int, data: CalendarEventCreate) -> CalendarMutationReceipt:
    await _require_calendar_scope(calendar_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.create_calendar_event(calendar_id, connection.agent_id, data)


@router.put("/{calendar_id}/events/{event_id}", response_model=CalendarMutationReceipt)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def update_event(calendar_id: int, event_id: UUID, data: CalendarEventUpdate) -> CalendarMutationReceipt:
    uid = await _event_uid(calendar_id, event_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.update_calendar_event(calendar_id, connection.agent_id, uid, data)


@router.get("/{calendar_id}/events/{event_id}", response_model=CalendarEventDetail)
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def event_detail(calendar_id: int, event_id: UUID, recurrence_key: str | None = None) -> CalendarEventDetail:
    uid = await _event_uid(calendar_id, event_id, deleted=True)
    with _errors():
        return await service.event_detail(calendar_id, uid, recurrence_key)


@router.get("/{calendar_id}/events/{event_id}/history", response_model=list[CalendarEventHistoryRead])
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def event_history(calendar_id: int, event_id: UUID, skip: int = Query(default=0, ge=0),
                         limit: int = Query(default=50, ge=1, le=500)) -> list[CalendarEventHistoryRead]:
    uid = await _event_uid(calendar_id, event_id, deleted=True)
    with _errors():
        return await service.event_history(calendar_id, uid, skip=skip, limit=limit)


@router.get("/{calendar_id}/conflicts", response_model=list[CalendarConflictRead])
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def calendar_conflicts(calendar_id: int, skip: int = Query(default=0, ge=0),
                            limit: int = Query(default=50, ge=1, le=500)) -> list[CalendarConflictRead]:
    await _require_calendar_scope(calendar_id)
    return await service.list_conflicts(calendar_id, skip=skip, limit=limit)


@router.post("/{calendar_id}/events/{event_id}/resolve", response_model=CalendarMutationReceipt)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def resolve_conflict(calendar_id: int, event_id: UUID, data: CalendarConflictResolution) -> CalendarMutationReceipt:
    uid = await _event_uid(calendar_id, event_id, deleted=True)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.resolve_conflict(calendar_id, connection.agent_id, uid, data.expected_revision, data.choice)


@router.get("/{calendar_id}/sync-runs", response_model=list[CalendarSyncRunRead])
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def sync_runs(calendar_id: int, skip: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=500)) -> list[CalendarSyncRunRead]:
    await _require_calendar_scope(calendar_id)
    return await service.sync_runs(calendar_id, skip=skip, limit=limit)


@router.delete("/{calendar_id}/events/{event_id}", response_model=CalendarMutationReceipt)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def delete_event(calendar_id: int, event_id: UUID, data: CalendarEventDelete) -> CalendarMutationReceipt:
    uid = await _event_uid(calendar_id, event_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.delete_calendar_event(calendar_id, connection.agent_id, uid, data)


@router.get("/{calendar_id}/events/{event_id}/actions", response_model=list[CalendarActionRead])
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def read_actions(calendar_id: int, event_id: UUID) -> list[CalendarActionRead]:
    uid = await _event_uid(calendar_id, event_id)
    with _errors():
        return await service.list_actions(calendar_id, uid)


@router.post("/{calendar_id}/events/{event_id}/actions", response_model=CalendarActionRead, status_code=201)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def create_action(calendar_id: int, event_id: UUID, data: CalendarActionWrite) -> CalendarActionRead:
    uid = await _event_uid(calendar_id, event_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.write_action(calendar_id, connection.agent_id, uid, data)


@router.put("/{calendar_id}/events/{event_id}/actions/{action_id}", response_model=CalendarActionRead)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def update_action(calendar_id: int, event_id: UUID, action_id: UUID, data: CalendarActionWrite) -> CalendarActionRead:
    uid = await _event_uid(calendar_id, event_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.write_action(calendar_id, connection.agent_id, uid, data, action_id)


@router.post("", response_model=CalendarFeedRead, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def create_calendar(data: CalendarFeedCreate) -> CalendarFeedRead:
    try:
        await _require_connection_scope(data.connection_id)
        return await service.create_feed(data)
    except HTTPException:
        raise
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.post("/{calendar_id}/executions/{execution_id}/relaunch", response_model=CalendarExecutionReceipt, status_code=201)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def relaunch_execution(calendar_id: int, execution_id: UUID, data: CalendarExecutionRelaunch) -> CalendarExecutionReceipt:
    await _require_calendar_scope(calendar_id)
    with _errors():
        _, connection = await service.feed_context(calendar_id, require_active_connection=True)
        return await service.relaunch_execution(calendar_id, execution_id, connection.agent_id, data.request_key, data.expected_event_revision)


@router.put("/{calendar_id}", response_model=CalendarFeedRead)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def update_calendar(calendar_id: int, data: CalendarFeedUpdate) -> CalendarFeedRead:
    try:
        await _require_calendar_scope(calendar_id)
        return await service.update_feed(calendar_id, data)
    except HTTPException:
        raise
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.CALENDAR_EDIT)
async def delete_calendar(calendar_id: int) -> None:
    await _require_calendar_scope(calendar_id)
    try:
        if not await service.delete_feed(calendar_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar not found")
    except ValueError as exc:
        raise _invalid(exc) from exc


@router.post("/{calendar_id}/test", response_model=CalendarConnectionStatus)
@authorize(privileges=[Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT])
async def test_calendar(calendar_id: int) -> CalendarConnectionStatus:
    try:
        await _require_calendar_scope(calendar_id)
        return await service.test_feed(calendar_id)
    except HTTPException:
        raise
    except LookupError as exc:
        raise _not_found(exc) from exc
    except (ValueError, PermissionError) as exc:
        raise _invalid(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The calendar resource could not be read",
        ) from exc


__all__ = ["router"]
