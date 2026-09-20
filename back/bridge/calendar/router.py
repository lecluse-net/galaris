"""Human administration API for agent calendars."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope
from app.connection.facade import get_connection

from . import service
from .schemas import (
    CalendarConnectionStatus,
    CalendarFeedCreate,
    CalendarFeedRead,
    CalendarFeedUpdate,
)


router = APIRouter(prefix="/calendars", tags=["calendars"])


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _invalid(exc: ValueError | PermissionError) -> HTTPException:
    code = status.HTTP_403_FORBIDDEN if isinstance(exc, PermissionError) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


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


@router.get("", response_model=list[CalendarFeedRead])
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def read_calendars(connection_id: int = Query(gt=0)) -> list[CalendarFeedRead]:
    await _require_connection_scope(connection_id)
    return await service.list_feeds(connection_id=connection_id)


@router.post("", response_model=CalendarFeedRead, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.CONNECTION_EDIT)
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


@router.put("/{calendar_id}", response_model=CalendarFeedRead)
@authorize(privileges=Privileges.CONNECTION_EDIT)
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
@authorize(privileges=Privileges.CONNECTION_EDIT)
async def delete_calendar(calendar_id: int) -> None:
    await _require_calendar_scope(calendar_id)
    if not await service.delete_feed(calendar_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar not found")


@router.post("/{calendar_id}/test", response_model=CalendarConnectionStatus)
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
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
