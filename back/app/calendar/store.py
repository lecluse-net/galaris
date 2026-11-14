"""Local persistence and disposable occurrence/deadline projections. No transport."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

from pydantic import TypeAdapter
from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from app.agent import find_background_tasks
from app.connection import Connection
from . import calculation, ical
from .crypto import decrypt, digest, encrypt
from .models import (CalendarAction, CalendarEvent, CalendarEventException, CalendarEventRevision,
                     CalendarFeed, CalendarOccurrence, CalendarSyncOperation, CalendarTrigger)
from .models import CalendarProjectionWindow

_occurrence_adapter = TypeAdapter(ical.ParsedEvent)
EVENT_START_ACTION_KEY = "event:start"


class CalendarConflictError(ValueError):
    """A revision changed, or an unresolved remote version exists."""


async def event_by_uid(calendar_id: int, uid: str, *, lock: bool = False, deleted: bool = False) -> CalendarEvent:
    statement = select(CalendarEvent).where(CalendarEvent.calendar_id == calendar_id, CalendarEvent.uid == uid)
    if deleted:
        statement = statement.execution_options(include_historized=True)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    event = await get_db().scalar(statement)
    if event is None:
        raise LookupError("Calendar event not found")
    return event


async def resource_content(event: CalendarEvent) -> bytes:
    if not event.recurring:
        return decrypt(event.content_encrypted).encode()
    exceptions = (await get_db().scalars(select(CalendarEventException).where(CalendarEventException.event_id == event.id)
        .order_by(CalendarEventException.recurrence_key))).all()
    return await asyncio.to_thread(ical.join_resource, decrypt(event.content_encrypted), [decrypt(row.content_encrypted) for row in exceptions])


async def save_resource(feed: CalendarFeed, resource: ical.EventResource, *, local: bool,
                        existing: CalendarEvent | None = None, known: bool = False, contact_id: UUID | None = None) -> CalendarEvent:
    if not known:
        existing = await get_db().scalar(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id,
            CalendarEvent.uid == resource.uid).execution_options(include_historized=True).with_for_update())
    event = existing
    if event is None:
        event = CalendarEvent(id=uuid4(), calendar_id=feed.id, uid=resource.uid, revision=1, synced_revision=0,
            content_encrypted=encrypt(resource.master), content_hash=resource.digest, start_at=resource.start,
            end_at=resource.end, recurring=resource.recurring, conflict=False, contact_id=contact_id)
        get_db().add(event)
    else:
        event.revision += 1
        event.restore()
        event.content_encrypted = encrypt(resource.master)
        event.content_hash = resource.digest
        event.start_at, event.end_at, event.recurring = resource.start, resource.end, resource.recurring
    event.has_actions = True
    event.actions_planned_until = None
    await get_db().flush()
    await get_db().execute(delete(CalendarProjectionWindow).where(CalendarProjectionWindow.event_id == event.id))
    await get_db().execute(delete(CalendarEventException).where(CalendarEventException.event_id == event.id))
    if resource.exceptions:
        await get_db().execute(insert(CalendarEventException), [dict(id=uuid4(), event_id=event.id,
            recurrence_key=key, content_encrypted=encrypt(content)) for key, content in resource.exceptions])
    content = ical.join_resource(resource.master, [value for _, value in resource.exceptions]).decode() if resource.exceptions else resource.master
    get_db().add(CalendarEventRevision(event_id=event.id, revision=event.revision, contact_id=event.contact_id,
        content_encrypted=encrypt(content), deleting=False))
    if local and feed.source_kind not in ("internal", "ical"):
        get_db().add(CalendarSyncOperation(calendar_id=feed.id, event_id=event.id, revision=event.revision,
            deleting=False, content_encrypted=encrypt(content), content_hash=resource.digest))
        feed.sync_requested = True
    elif not local:
        event.synced_revision = event.revision
    return event


async def delete_local_event(feed: CalendarFeed, event: CalendarEvent, *, local: bool) -> None:
    agent_id = (await get_db().scalars(select(Connection.agent_id).where(Connection.id == feed.connection_id))).one()
    await reconcile_admissions([event.id], agent_id)
    content = (await resource_content(event)).decode()
    event.revision += 1
    event.soft_delete()
    get_db().add(CalendarEventRevision(event_id=event.id, revision=event.revision, contact_id=event.contact_id,
        content_encrypted=encrypt(content), deleting=True))
    if local and feed.source_kind not in ("internal", "ical"):
        get_db().add(CalendarSyncOperation(calendar_id=feed.id, event_id=event.id, revision=event.revision,
            deleting=True, content_encrypted=encrypt(content), content_hash=event.content_hash))
        feed.sync_requested = True
    await get_db().execute(delete(CalendarOccurrence).where(CalendarOccurrence.event_id == event.id))
    await cancel_pending([event.id])


async def cancel_pending(event_ids: Sequence[UUID]) -> None:
    await get_db().execute(update(CalendarTrigger).where(CalendarTrigger.event_id.in_(event_ids),
        CalendarTrigger.status.in_(("scheduled", "pending", "error")), CalendarTrigger.task_id.is_(None),
        CalendarTrigger.lease_token.is_(None)).values(status="cancelled"))


async def reconcile_admissions(event_ids: Sequence[UUID], agent_id: int) -> None:
    rows = list((await get_db().scalars(select(CalendarTrigger).where(CalendarTrigger.event_id.in_(event_ids),
        CalendarTrigger.task_id.is_(None), or_(CalendarTrigger.status.in_(("pending", "error")), CalendarTrigger.lease_token.is_not(None))))).all())
    for index in range(0, len(rows), 500):
        batch = rows[index:index + 500]
        tasks = await find_background_tasks(agent_id, [f"calendar:{row.id}" for row in batch])
        for row in batch:
            task_id = tasks.get(f"calendar:{row.id}")
            if task_id:
                row.task_id, row.status, row.lease_token, row.lease_expires_at = task_id, "submitted", None, None
                row.error_message = None
    await get_db().flush()


async def project_events(feed: CalendarFeed, events: Sequence[CalendarEvent], *, agent_id: int,
                         start: datetime | None = None, end: datetime | None = None, reschedule: bool = True) -> None:
    """Batch expansion amortizes parser/worker startup; single events never expand."""
    if not events:
        return
    now = datetime.now(timezone.utc)
    window_start = start or now - timedelta(days=7)
    window_end = end or now + timedelta(days=366 if any(event.has_actions for event in events) else 32)
    for offset in range(0, len(events), 100):
        batch = events[offset:offset + 100]
        ids = [event.id for event in batch]
        if reschedule:
            await reconcile_admissions(ids, agent_id)
        exceptions = (await get_db().scalars(select(CalendarEventException).where(CalendarEventException.event_id.in_(ids)))).all()
        grouped: dict[UUID, list[str]] = defaultdict(list)
        for exception in exceptions:
            grouped[exception.event_id].append(decrypt(exception.content_encrypted))
        recurring = [event for event in batch if event.recurring]
        lower, upper = window_start, window_end
        parsed: dict[str, list[ical.ParsedEvent]] = defaultdict(list)
        if recurring:
            for part in range(0, len(recurring), 10):
                contents = [ical.join_resource(decrypt(event.content_encrypted), grouped[event.id]) for event in recurring[part:part + 10]]
                combined = await asyncio.to_thread(ical.combine_resources, contents)
                spans = [combined] if len(combined) <= 5 * 1024 * 1024 else contents
                for span in spans:
                    for occurrence in await calculation.events_between(span, lower, upper, feed.timezone, compact=True):
                        parsed[occurrence.uid].append(occurrence)
        for event in batch:
            if not event.recurring:
                parsed[event.uid] = [ical.master_event(decrypt(event.content_encrypted).encode(), feed.timezone)]
        obsolete = or_(*[(CalendarOccurrence.event_id == event.id) & (CalendarOccurrence.event_revision != event.revision) for event in batch])
        await get_db().execute(delete(CalendarOccurrence).where(obsolete))
        if reschedule:
            await cancel_pending(ids)
        actions = list((await get_db().scalars(select(CalendarAction).where(CalendarAction.event_id.in_(ids), CalendarAction.active.is_(True)))).all()) if reschedule else []
        action_groups: dict[UUID, list[CalendarAction]] = defaultdict(list)
        for action in actions:
            action_groups[action.event_id].append(action)
        occurrences: list[dict[str, object]] = []
        deadlines: list[dict[str, object]] = []
        for event in batch:
            if reschedule:
                event.has_actions = True
                event.actions_planned_until = upper
            if event.recurring:
                covered = insert(CalendarProjectionWindow).values(id=uuid4(), event_id=event.id, event_revision=event.revision,
                    start_at=lower, end_at=upper, built_at=now)
                await get_db().execute(covered.on_conflict_do_update(constraint="uq_calendar_projection_window", set_={"built_at": now}))
            for occurrence in parsed[event.uid]:
                identity = uuid5(event.id, occurrence.recurrence_key)
                payload = asdict(occurrence)
                # Grid metadata is compact; long text stays once per resource.
                payload["description"] = ""
                payload["alarms"] = []
                occurrences.append(dict(id=identity, calendar_id=feed.id, event_id=event.id,
                    recurrence_key=occurrence.recurrence_key, event_revision=event.revision,
                    start_at=occurrence.start, end_at=occurrence.end, transparent=occurrence.transparent,
                    cancelled=occurrence.status.upper() == "CANCELLED", payload_encrypted=encrypt(json.dumps(payload, default=str))))
                if not reschedule or occurrence.status.upper() == "CANCELLED" or not feed.actions_enabled:
                    continue
                planned: list[tuple[str, datetime, str, int, int | None]] = [(alarm.key, alarm.at, "", 60, None) for alarm in occurrence.alarms]
                for action in action_groups[event.id]:
                    if action.recurrence_key is None or action.recurrence_key == occurrence.recurrence_key:
                        at = (occurrence.start if action.anchor == "start" else occurrence.end) + timedelta(minutes=action.offset_minutes)
                        planned.append((str(action.id), at, "", action.max_lateness_minutes, action.revision))
                if not planned:
                    planned.append((EVENT_START_ACTION_KEY, occurrence.start, "", 60, None))
                for key, at, instructions, lateness, action_revision in planned:
                    fingerprint = digest(f"{event.id}:{occurrence.recurrence_key}:{key}:0")
                    snapshot = dict(agent_id=agent_id, label=f"Agenda: {occurrence.summary or feed.label}"[:400],
                        instructions=instructions, payload=dict(calendar_id=feed.id, calendar_label=feed.label,
                        calendar_owner=feed.owner_label, event_id=str(event.id), recurrence_key=occurrence.recurrence_key,
                        event=payload, triggered_at=at.isoformat(), untrusted_content=True))
                    deadlines.append(dict(id=uuid4(), calendar_id=feed.id, event_id=event.id, event_uid=event.uid,
                        recurrence_key=occurrence.recurrence_key, action_key=key, action_revision=action_revision, launch_number=0, event_revision=event.revision,
                        fingerprint=fingerprint, trigger_kind="alarm", occurrence_at=at, max_lateness_minutes=lateness,
                        dispatch_encrypted=encrypt(json.dumps(snapshot, default=str)), status="scheduled"))
        for index in range(0, len(occurrences), 200):
            projected = insert(CalendarOccurrence).values(occurrences[index:index + 200])
            await get_db().execute(projected.on_conflict_do_update(constraint="uq_calendar_occurrence",
                set_={name: getattr(projected.excluded, name) for name in ("event_revision", "start_at", "end_at", "transparent", "cancelled", "payload_encrypted")}))
        for index in range(0, len(deadlines), 200):
            statement = insert(CalendarTrigger).values(deadlines[index:index + 200])
            await get_db().execute(statement.on_conflict_do_update(constraint="uq_calendar_action_launch",
                set_={**{name: getattr(statement.excluded, name) for name in ("event_revision", "action_revision", "occurrence_at", "dispatch_encrypted", "max_lateness_minutes", "status")}, "error_message": None},
                where=(CalendarTrigger.task_id.is_(None) & (CalendarTrigger.status != "submitted"))))
    await get_db().flush()


async def ensure_coverage(feed: CalendarFeed, start: datetime, end: datetime, agent_id: int) -> None:
    covered = select(CalendarProjectionWindow.id).where(CalendarProjectionWindow.event_id == CalendarEvent.id,
        CalendarProjectionWindow.event_revision == CalendarEvent.revision, CalendarProjectionWindow.start_at <= start,
        CalendarProjectionWindow.end_at >= end, CalendarProjectionWindow.built_at >= datetime.now(timezone.utc) - timedelta(days=30)).exists()
    events = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id,
        CalendarEvent.recurring, ~covered))).all())
    if events:
        # Serialize cache reconstruction with mutations, then re-read their revisions.
        locked = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.id.in_([event.id for event in events]))
            .with_for_update().execution_options(populate_existing=True))).all())
        await project_events(feed, locked, agent_id=agent_id, start=start, end=end, reschedule=False)


def decode_occurrence(row: CalendarOccurrence) -> ical.ParsedEvent:
    return _occurrence_adapter.validate_json(decrypt(row.payload_encrypted))


async def import_new_resources(feed: CalendarFeed, resources: Sequence[ical.EventResource]) -> list[CalendarEvent]:
    """Bulk first import: a bounded number of SQL statements per resource batch."""
    events = [CalendarEvent(id=uuid4(), calendar_id=feed.id, uid=resource.uid, revision=1, synced_revision=1,
        content_encrypted=encrypt(resource.master), content_hash=resource.digest, start_at=resource.start,
        end_at=resource.end, recurring=resource.recurring, has_actions=True, conflict=False) for resource in resources]
    get_db().add_all(events)
    await get_db().flush()
    exception_rows: list[dict[str, object]] = []
    revisions: list[dict[str, object]] = []
    for event, resource in zip(events, resources, strict=True):
        exception_rows.extend(dict(id=uuid4(), event_id=event.id, recurrence_key=key, content_encrypted=encrypt(value))
                              for key, value in resource.exceptions)
        revisions.append(dict(id=uuid4(), event_id=event.id, revision=1, deleting=False,
            content_encrypted=encrypt(ical.join_resource(resource.master, [value for _, value in resource.exceptions]).decode() if resource.exceptions else resource.master)))
    if exception_rows:
        await get_db().execute(insert(CalendarEventException), exception_rows)
    if revisions:
        await get_db().execute(insert(CalendarEventRevision), revisions)
    return events
