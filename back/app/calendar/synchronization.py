"""Background-only synchronization. Reads and commands never call this module."""
from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

from loguru import logger
import httpx
from sqlalchemy import and_, func, or_, select, text, update

from app.connection import Connection
from app.connection.facade import calendar_access_token, invalidate_calendar_token
from app.tools.facade import get_tool_by_id
from core.database import get_db
from . import ical, store
from .calculation import CalendarCalculationError
from .contracts import CalDavTransport, InvalidSyncTokenError, RemoteChange, RemoteChanges, RemoteConflictError, StaleSyncError, calendar_provider, monitor_calendar_sync
from .sync_progress import SyncProgressReporter, historical_progress
from .crypto import decrypt, digest, encrypt
from .models import CalendarEvent, CalendarFeed, CalendarSyncOperation, CalendarSyncRun
from .transport import read_calendar


async def _fence(calendar_id: int, token: UUID, revision: int) -> CalendarFeed:
    feed = await get_db().scalar(select(CalendarFeed).join(Connection, Connection.id == CalendarFeed.connection_id)
        .where(CalendarFeed.id == calendar_id, CalendarFeed.lease_token == token, CalendarFeed.source_revision == revision,
            CalendarFeed.active.is_(True), Connection.active.is_(True), CalendarFeed.lease_expires_at > datetime.now(timezone.utc))
        .with_for_update(of=CalendarFeed).execution_options(populate_existing=True))
    if feed is None:
        raise StaleSyncError("Calendar synchronization context changed")
    feed.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    return feed


async def _conflict(event: CalendarEvent, content: bytes | None, etag: str | None = None) -> bool:
    changed = not event.conflict or decrypt(event.remote_content_encrypted) != (content.decode() if content is not None else "") or event.remote_etag != etag
    event.conflict = True
    event.remote_content_encrypted = encrypt(content.decode()) if content is not None else None
    event.remote_etag = etag
    await get_db().execute(update(CalendarSyncOperation).where(CalendarSyncOperation.event_id == event.id,
        CalendarSyncOperation.state.in_(("pending", "error"))).values(state="conflict", error_message="RemoteConflictError"))
    logger.warning("Calendar sync conflict calendar_id={} event_id={}", event.calendar_id, event.id)
    return changed


async def _apply(feed: CalendarFeed, batch: RemoteChanges, agent_id: int) -> tuple[int, int, bool]:
    """Validate the whole incoming payload before considering any remote deletion."""
    incoming: list[tuple[RemoteChange, ical.EventResource]] = []
    deleted: list[RemoteChange] = []
    for change in batch.changes:
        if change.deleted:
            deleted.append(change)
            continue
        if change.content is None:
            raise ValueError("Incomplete remote event")
        resources = await asyncio.to_thread(ical.split_resources, change.content, feed.timezone)
        if feed.source_kind not in ("internal", "ical") and len(resources) != 1:
            raise ValueError("A CalDAV event resource must contain one UID")
        incoming.extend((change, resource) for resource in resources)
    if len({resource.uid for _, resource in incoming}) != len(incoming):
        raise ValueError("Duplicate event UIDs in remote response")
    seen_uids = {resource.uid for _, resource in incoming}
    calendar_changed = False
    for offset in range(0, len(incoming), 200):
        items = incoming[offset:offset + 200]
        existing = {row.uid: row for row in (await get_db().scalars(select(CalendarEvent).where(
            CalendarEvent.calendar_id == feed.id, CalendarEvent.uid.in_([resource.uid for _, resource in items]))
            .execution_options(include_historized=True).with_for_update())).all()}
        fresh = [resource for _, resource in items if resource.uid not in existing]
        created = await store.import_new_resources(feed, fresh)
        events = {row.uid: row for row in created}
        changed = list(created)
        calendar_changed |= bool(created)
        for change, resource in items:
            event = existing.get(resource.uid) or events[resource.uid]
            pending = event.synced_revision < event.revision
            if event.uid in existing:
                if event.content_hash == resource.digest and event.deleted_at is None:
                    calendar_changed |= pending
                    event.synced_revision = event.revision
                    if pending:
                        await get_db().execute(update(CalendarSyncOperation).where(CalendarSyncOperation.event_id == event.id,
                            CalendarSyncOperation.content_hash == resource.digest, CalendarSyncOperation.deleting.is_(False),
                            CalendarSyncOperation.state.in_(("pending", "error"))).values(state="success", completed_at=datetime.now(timezone.utc)))
                elif pending:
                    previous = decrypt(event.remote_content_encrypted)
                    if previous and ical.resource_digest(previous.encode()) == resource.digest:
                        event.remote_etag = change.etag
                        continue
                    calendar_changed |= await _conflict(event, change.content, change.etag)
                    continue
                elif event.deleted_at is None or event.remote_etag != change.etag:
                    event = await store.save_resource(feed, resource, local=False, existing=event, known=True)
                    changed.append(event)
                    calendar_changed = True
            if feed.source_kind not in ("internal", "ical"):
                if event.remote_href_hash not in (None, digest(change.href)):
                    # Resource moves are reconciled by stable UID, not as a second event.
                    event.remote_href_hash = digest(change.href)
                event.remote_href_encrypted, event.remote_href_hash = encrypt(change.href), digest(change.href)
            event.remote_etag = change.etag
            event.remote_content_encrypted = encrypt(change.content.decode()) if change.content and feed.source_kind not in ("internal", "ical") else None
        await store.project_events(feed, changed, agent_id=agent_id)
    if batch.full:
        candidates = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id,
            CalendarEvent.synced_revision > 0))).all())
        missing = [event for event in candidates if event.uid not in seen_uids]
    else:
        hashes = [digest(change.href) for change in deleted]
        missing = list((await get_db().scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id,
            CalendarEvent.remote_href_hash.in_(hashes)))).all()) if hashes else []
    missing_ids = [event.id for event in missing]
    removed = 0
    for index in range(0, len(missing_ids), 200):
        locked = (await get_db().scalars(select(CalendarEvent).where(CalendarEvent.id.in_(missing_ids[index:index + 200]))
            .with_for_update().execution_options(populate_existing=True))).all()
        for event in locked:
            if event.synced_revision < event.revision:
                calendar_changed |= await _conflict(event, None)
            else:
                await store.delete_local_event(feed, event, local=False)
                event.synced_revision = event.revision
                removed += 1
    await get_db().flush()
    return len(incoming), removed, calendar_changed or removed > 0


async def _push(feed: CalendarFeed, token: UUID, source_revision: int, username: str | None, password: str | None, run_id: UUID,
                progress: SyncProgressReporter, transport: CalDavTransport) -> int:
    identities = list((await get_db().scalars(select(CalendarSyncOperation.id).where(CalendarSyncOperation.calendar_id == feed.id,
        CalendarSyncOperation.state.in_(("pending", "error"))).order_by(CalendarSyncOperation.created_at, CalendarSyncOperation.revision).limit(200))).all())
    count = 0
    progress.data.upload_total = len(identities)
    await progress.save()
    calendar_id = feed.id
    for identity in identities:
        feed = await _fence(calendar_id, token, source_revision)
        operation = (await get_db().scalars(select(CalendarSyncOperation).where(CalendarSyncOperation.id == identity)
            .with_for_update().execution_options(populate_existing=True))).one()
        event = (await get_db().scalars(select(CalendarEvent).where(CalendarEvent.id == operation.event_id)
            .execution_options(include_historized=True, populate_existing=True).with_for_update())).one()
        if event.conflict or operation.state not in ("pending", "error"):
            progress.data.uploaded += 1
            await get_db().commit()
            await progress.save()
            continue
        url = decrypt(feed.url_encrypted)
        href = decrypt(event.remote_href_encrypted) or urljoin(url.rstrip('/') + '/', f'{event.id}.ics')
        if urlsplit(href).netloc != urlsplit(url).netloc:
            raise ValueError("Remote calendar resource origin changed")
        event.remote_href_encrypted, event.remote_href_hash = encrypt(href), digest(href)
        etag = event.remote_etag
        content = decrypt(operation.content_encrypted).encode()
        deleting, revision, expected_hash = operation.deleting, operation.revision, operation.content_hash
        operation.attempts += 1
        await get_db().execute(update(CalendarSyncRun).where(CalendarSyncRun.id == run_id).values(stage="push", operation_id=identity))
        await get_db().commit()
        remote = None
        remote_content: bytes | None = None
        conflict = False
        if not feed.writable:
            raise PermissionError("Remote calendar is read-only")
        try:
            if deleting:
                if etag is None:
                    remote = await transport.fetch(href, username=username, password=password)
                    if remote is not None:
                        if ical.resource_digest(remote.content) != expected_hash:
                            raise RemoteConflictError("Remote deletion target changed")
                        etag = remote.headers.get("etag")
                        if etag is None:
                            raise RemoteConflictError("Remote deletion requires an ETag")
                if etag is not None:
                    await transport.remove(href, etag=etag, username=username, password=password)
            else:
                written = await transport.put(href, content, etag=etag, username=username, password=password)
                href = written.final_url
                remote = await transport.fetch(href, username=username, password=password)
                if remote is None or not remote.headers.get("etag"):
                    raise ValueError("Written calendar resource could not be verified")
                etag, remote_content = remote.headers["etag"], remote.content
                if ical.resource_digest(remote.content) != expected_hash:
                    raise RemoteConflictError("Written calendar resource differs from the intended event")
        except RemoteConflictError:
            remote = await transport.fetch(href, username=username, password=password)
            if deleting and remote is None:
                pass
            elif not deleting and remote is not None and ical.resource_digest(remote.content) == expected_hash:
                etag, remote_content = remote.headers.get("etag"), remote.content
            else:
                conflict, remote_content = True, remote.content if remote else None
                etag = remote.headers.get("etag") if remote else None
        feed = await _fence(calendar_id, token, source_revision)
        event = (await get_db().scalars(select(CalendarEvent).where(CalendarEvent.id == operation.event_id)
            .execution_options(include_historized=True, populate_existing=True).with_for_update())).one()
        if remote is not None:
            href = remote.final_url
        event.remote_href_encrypted, event.remote_href_hash = encrypt(href), digest(href)
        operation = (await get_db().scalars(select(CalendarSyncOperation).where(CalendarSyncOperation.id == identity)
            .execution_options(populate_existing=True))).one()
        if conflict:
            calendar_changed = await _conflict(event, remote_content, etag)
        else:
            calendar_changed = True
            operation.state, operation.completed_at, operation.error_message = "success", datetime.now(timezone.utc), None
            event.synced_revision = max(event.synced_revision, revision)
            event.remote_etag = etag
            event.remote_content_encrypted = encrypt(remote_content.decode()) if remote_content else None
            count += 1
            progress.data.upload_succeeded += 1
        await get_db().commit()
        progress.data.calendar_changed |= calendar_changed
        progress.data.uploaded += 1
        await progress.save()
    return count


async def synchronize_calendar(calendar_id: int, *, agent_id: int, automatic: bool = False) -> int:
    now, token = datetime.now(timezone.utc), uuid4()
    claim = update(CalendarFeed).where(CalendarFeed.id == calendar_id, CalendarFeed.active.is_(True),
        CalendarFeed.connection_id.in_(select(Connection.id).where(Connection.agent_id == agent_id, Connection.active.is_(True))),
        CalendarFeed.deleted_at.is_(None), or_(CalendarFeed.lease_expires_at.is_(None), CalendarFeed.lease_expires_at <= now))
    if automatic:
        anchor = func.coalesce(CalendarFeed.last_checked_at, CalendarFeed.last_synced_at)
        interval = CalendarFeed.sync_interval_hours * text("INTERVAL '1 hour'")
        claim = claim.where(or_(CalendarFeed.next_sync_at.is_(None), and_(CalendarFeed.next_sync_at <= now,
            or_(anchor.is_(None), anchor + interval <= now))))
    claimed = await get_db().scalar(claim
        .values(lease_token=token, lease_expires_at=now + timedelta(minutes=5)).returning(CalendarFeed.id))
    await get_db().commit()
    if claimed is None:
        return 0
    expired = (await get_db().scalars(select(CalendarSyncRun).where(CalendarSyncRun.calendar_id == calendar_id,
        CalendarSyncRun.state == "running").with_for_update())).all()
    for previous in expired:
        previous.state, previous.error_category, previous.finished_at = "interrupted", "LeaseExpired", now
        previous.progress = historical_progress(previous.progress)
    feed = (await get_db().scalars(select(CalendarFeed).where(CalendarFeed.id == calendar_id).execution_options(populate_existing=True))).one()
    revision = feed.source_revision
    # Persist the next automatic attempt before I/O, including interrupted reads.
    feed.last_checked_at = now
    feed.next_sync_at = now + timedelta(hours=feed.sync_interval_hours)
    run = await get_db().scalar(select(CalendarSyncRun).where(CalendarSyncRun.calendar_id == calendar_id,
        CalendarSyncRun.state == "queued").order_by(CalendarSyncRun.started_at).limit(1).with_for_update())
    if run is None:
        run = CalendarSyncRun(calendar_id=calendar_id, source_revision=revision, stage="connecting", state="running")
        get_db().add(run)
    else:
        run.source_revision, run.stage, run.state = revision, "connecting", "running"
    await get_db().flush()
    run_id = run.id
    progress = SyncProgressReporter(calendar_id, run_id, token, revision, run.progress or {})
    await get_db().commit()
    count = 0
    stage = "read"
    release = True
    bearer: str | None = None
    transport: CalDavTransport | None = None
    connection_id = feed.connection_id
    try:
        await progress.stage("connecting")
        url, username, password = decrypt(feed.url_encrypted), decrypt(feed.username_encrypted) or None, decrypt(feed.password_encrypted) or None
        if feed.source_kind == "internal":
            batch = RemoteChanges((), None, False)
        elif feed.source_kind == "ical":
            stage = "read"
            await progress.stage(stage)
            progress.data.download_total = 1
            with monitor_calendar_sync(progress.on_progress):
                response = await read_calendar(url, username=username, password=password, etag=feed.remote_etag)
            progress.data.downloaded = 0 if response.status_code == 304 else 1
            progress.data.download_total = progress.data.downloaded
            await progress.save()
            if response.status_code == 304 and not feed.initialized:
                raise ValueError("An initial iCalendar synchronization requires content")
            batch = RemoteChanges((), None, False) if response.status_code == 304 else RemoteChanges((RemoteChange(url, response.headers.get("etag"), response.content),), None, True)
        else:
            connection = await get_db().get(Connection, connection_id)
            tool = await get_tool_by_id(connection.tool_id) if connection else None
            oauth = feed.source_kind in ("google", "microsoft") or bool(feed.source_kind == "caldav" and tool and tool.calendar and tool.calendar.settings.get("auth_type") == "oauth")
            if oauth:
                _, bearer = await calendar_access_token(connection_id)
                await get_db().commit()
            transport = calendar_provider(feed.source_kind, bearer)
            if feed.source_kind not in ("internal", "ical"):
                discovery_url = (decrypt(feed.source_root_encrypted) or url) if feed.is_default else url
                stage = "discover"
                await progress.stage(stage)
                with monitor_calendar_sync(progress.on_progress):
                    calendars = await transport.discover(discovery_url, username=username, password=password)
                progress.data.calendars = len(calendars)
                selected = next((item for item in calendars if item.href.rstrip('/') == url.rstrip('/')), None)
                if selected is None:
                    if feed.initialized:
                        raise LookupError("CalDAV calendar is no longer discoverable")
                    selected = calendars[0]
                feed = await _fence(calendar_id, token, revision)
                calendar_changed = feed.writable != selected.writable or (not feed.initialized and feed.label != selected.label)
                feed.writable = selected.writable
                if not feed.initialized:
                    feed.label = selected.label
                existing = list((await get_db().scalars(select(CalendarFeed).where(CalendarFeed.connection_id == feed.connection_id))).all())
                hrefs = {decrypt(row.url_encrypted) for row in existing}
                feed.url_encrypted = encrypt(selected.href)
                url = selected.href
                for remote in calendars:
                    if remote.href == selected.href or remote.href in hrefs:
                        continue
                    get_db().add(CalendarFeed(connection_id=feed.connection_id, label=remote.label, source_kind=feed.source_kind,
                        source_root_encrypted=feed.source_root_encrypted, url_encrypted=encrypt(remote.href),
                        username_encrypted=feed.username_encrypted, password_encrypted=feed.password_encrypted,
                        timezone=feed.timezone, sync_interval_hours=feed.sync_interval_hours,
                        writable=remote.writable, initialized=False, actions_enabled=True))
                    calendar_changed = True
                await get_db().commit()
                progress.data.calendar_changed |= calendar_changed
            stage = "read"
            await progress.stage(stage)
            with monitor_calendar_sync(progress.on_progress):
                try:
                    batch = await transport.changes(url, token=decrypt(feed.sync_token_encrypted) or None, username=username, password=password)
                except InvalidSyncTokenError:
                    batch = await transport.changes(url, token=None, username=username, password=password)
            progress.data.downloaded = sum(not change.deleted for change in batch.changes)
            progress.data.download_total = progress.data.downloaded
        stage = "apply"
        await progress.stage(stage)
        feed = await _fence(calendar_id, token, revision)
        applied, deleted, calendar_changed = await _apply(feed, batch, agent_id)
        feed.sync_token_encrypted = encrypt(batch.token) if batch.token else None
        if feed.source_kind == "ical" and batch.changes:
            feed.remote_etag = batch.changes[0].etag
        feed.initialized = True
        await get_db().commit()
        progress.data.calendar_changed |= calendar_changed
        progress.data.applied = progress.data.apply_total = applied
        progress.data.deleted = deleted
        stage = "push"
        await progress.stage(stage)
        if feed.source_kind not in ("internal", "ical") and transport is not None:
            with monitor_calendar_sync(progress.on_progress):
                count = await _push(feed, token, revision, username, password, run_id, progress, transport)
        else:
            progress.data.upload_total = 0
        feed = await _fence(calendar_id, token, revision)
        checked_at = datetime.now(timezone.utc)
        feed.last_checked_at = checked_at
        feed.last_synced_at, feed.last_error, feed.sync_requested = checked_at, None, False
        feed.failure_count, feed.next_sync_at = 0, checked_at + timedelta(hours=feed.sync_interval_hours)
        pending = await get_db().scalar(select(CalendarSyncOperation.id).where(CalendarSyncOperation.calendar_id == calendar_id,
            CalendarSyncOperation.state.in_(("pending", "error"))).limit(1))
        feed.sync_requested = pending is not None
        conflict = len((await get_db().scalars(select(CalendarEvent.id).where(CalendarEvent.calendar_id == calendar_id,
            CalendarEvent.conflict.is_(True)).execution_options(include_historized=True))).all())
        progress.data.conflicts = conflict
        if conflict:
            feed.last_error = "conflict: RemoteConflictError"
        await get_db().commit()
        await progress.finish()
        run = (await get_db().scalars(select(CalendarSyncRun).where(CalendarSyncRun.id == run_id))).one()
        run.state, run.stage, run.finished_at = "conflict" if conflict else "success", "complete", datetime.now(timezone.utc)
        run.progress = historical_progress(progress.data.model_dump(mode="json"))
        await get_db().commit()
    except asyncio.CancelledError:
        release = False
        await get_db().rollback()
        await get_db().execute(update(CalendarSyncRun).where(CalendarSyncRun.id == run_id, CalendarSyncRun.state == "running")
            .values(state="interrupted", stage=stage, error_category="CancelledError", finished_at=datetime.now(timezone.utc),
                    progress=historical_progress(progress.data.model_dump(mode="json"))))
        await get_db().commit()
        logger.warning("Calendar sync interrupted calendar_id={} run_id={} stage={}", calendar_id, run_id, stage)
        raise
    except Exception as exc:
        category = type(exc).__name__
        frames = traceback.extract_tb(exc.__traceback__)
        location = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}:{frames[-1].name}" if frames else None
        if isinstance(exc, CalendarCalculationError):
            category = f"CalendarCalculationError:{exc.code}"
            location = exc.location or location
        http_status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.bind(calendar_id=calendar_id, run_id=str(run_id), stage=stage, error_category=category,
                    http_status=http_status, error_location=location).error(
            "Calendar sync failed calendar_id={} run_id={} stage={} error_category={} http_status={}",
            calendar_id, run_id, stage, category, http_status)
        await get_db().rollback()
        if http_status == 401 and bearer is not None:
            await invalidate_calendar_token(connection_id, bearer)
        await get_db().execute(update(CalendarSyncRun).where(CalendarSyncRun.id == run_id, CalendarSyncRun.state == "running")
            .values(state="error", stage=stage, error_category=category, http_status=http_status,
                    error_location=location, finished_at=datetime.now(timezone.utc), progress=historical_progress(progress.data.model_dump(mode="json"))))
        operation_id = await get_db().scalar(select(CalendarSyncRun.operation_id).where(CalendarSyncRun.id == run_id))
        if operation_id is not None:
            await get_db().execute(update(CalendarSyncOperation).where(CalendarSyncOperation.id == operation_id,
                CalendarSyncOperation.state.in_(("pending", "error"))).values(state="error", error_message=category))
        interval_hours = await get_db().scalar(select(CalendarFeed.sync_interval_hours).where(CalendarFeed.id == calendar_id))
        checked_at = datetime.now(timezone.utc)
        await get_db().execute(update(CalendarFeed).where(CalendarFeed.id == calendar_id, CalendarFeed.lease_token == token,
            CalendarFeed.source_revision == revision)
            .values(last_error=f"{stage}: {category}", sync_requested=True, failure_count=CalendarFeed.failure_count + 1,
                    last_checked_at=checked_at, next_sync_at=checked_at + timedelta(hours=interval_hours or 2)))
        await get_db().commit()
    finally:
        # Cancellation keeps the lease until expiry: a late network outcome must
        # be reconciled before another worker can mutate the same provider.
        if release:
            await get_db().execute(update(CalendarFeed).where(CalendarFeed.id == calendar_id, CalendarFeed.lease_token == token)
                .values(lease_token=None, lease_expires_at=None))
            await get_db().commit()
    return count
