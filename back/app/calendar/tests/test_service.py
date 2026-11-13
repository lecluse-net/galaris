"""CalDAV provider boundary and local replica integration, with synthetic data."""
from __future__ import annotations

import json
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.calendar import ical, service
from app.calendar.crypto import decrypt
from app.calendar.models import CalendarEvent, CalendarFeed, CalendarSyncOperation, CalendarSyncRun
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarEventDelete
from app.calendar.synchronization import synchronize_calendar
from bridge.calendar import transport

URL = "https://calendar.example.test/dav/calendars/synthetic/main/"
NOW = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)


def event_content(uid="synthetic@example.test", summary="Synthetic event", start=NOW, **kwargs):
    return ical.create_event(ical.EMPTY_CALENDAR, CalendarEventCreate(uid=uid, summary=summary,
        start=start, end=start + timedelta(hours=1), **kwargs))[0]


class DavServer:
    """Stateful HTTP boundary: actual adapter XML and conditional requests run."""
    def __init__(self):
        self.objects = {}
        self.version = 0
        self.history = []
        self.calls = []
        self.fail = False
        self.lose_write = False
        self.expired = False
        self.writable = True
        self.race = False
        self.malformed = False
        self.report_started = None
        self.report_release = None
        self.page_size = None

    def write(self, href, content):
        self.version += 1
        self.objects[href] = (content, f'"v{self.version}"')
        self.history.append((self.version, href, False))

    def delete(self, href):
        self.version += 1
        self.objects.pop(href, None)
        self.history.append((self.version, href, True))

    async def __call__(self, request):
        if request.method == 'REPORT' and self.report_started is not None:
            self.report_started.set()
            await self.report_release.wait()
        return self.handle(request)

    def handle(self, request):
        method, path = request.method, urlsplit(str(request.url)).path
        self.calls.append((method, path, dict(request.headers)))
        if self.fail:
            raise httpx.ConnectError("Synthetic provider unavailable", request=request)
        base = urlsplit(URL).path
        href = "https://calendar.example.test" + path
        if method == "PROPFIND":
            privilege = '<d:privilege><d:write/></d:privilege>' if self.writable else ''
            body = f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>{base}</d:href><d:propstat><d:status>HTTP/1.1 200 OK</d:status><d:prop><d:resourcetype><c:calendar/></d:resourcetype><d:displayname>Synthetic agenda</d:displayname><d:current-user-privilege-set>{privilege}</d:current-user-privilege-set></d:prop></d:propstat></d:response></d:multistatus>'
            return httpx.Response(207, text=body)
        if method == "REPORT":
            if self.malformed:
                return httpx.Response(207, text='<error/>')
            root = ET.fromstring(request.content)
            requested = {"https://calendar.example.test" + (node.text or '') for node in root.findall('{DAV:}href')}
            include_data = root.find('.//{urn:ietf:params:xml:ns:caldav}calendar-data') is not None
            token = root.findtext('{DAV:}sync-token') or ''
            if self.expired and token:
                self.expired = False
                return httpx.Response(403, text='<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>')
            since = int(token) if token else None
            changes = {href: (version, deleted) for version, href, deleted in self.history if since is None or version > since}
            truncated = self.page_size is not None and root.tag == '{DAV:}sync-collection' and len(changes) > self.page_size
            if truncated:
                changes = dict(sorted(changes.items(), key=lambda item: item[1][0])[:self.page_size])
            next_token = max(version for version, _ in changes.values()) if truncated else self.version
            parts = []
            for current, (_, deleted) in changes.items():
                if requested and current not in requested:
                    continue
                if deleted:
                    if since is not None:
                        parts.append(f'<d:response><d:href>{current}</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response>')
                else:
                    content, etag = self.objects[current]
                    payload = f'<c:calendar-data>{escape(content.decode())}</c:calendar-data>' if include_data else ''
                    parts.append(f'<d:response><d:href>{current}</d:href><d:propstat><d:status>HTTP/1.1 200 OK</d:status><d:prop><d:getetag>{escape(etag)}</d:getetag>{payload}</d:prop></d:propstat></d:response>')
            if truncated:
                parts.append(f'<d:response><d:href>{base}</d:href><d:status>HTTP/1.1 507 Insufficient Storage</d:status></d:response>')
            return httpx.Response(207, text='<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">' + ''.join(parts) + f'<d:sync-token>{next_token}</d:sync-token></d:multistatus>')
        if method == "GET":
            if href not in self.objects:
                return httpx.Response(404)
            content, etag = self.objects[href]
            if request.headers.get('if-none-match') == etag:
                return httpx.Response(304, headers={'ETag': etag})
            return httpx.Response(200, content=content, headers={"ETag": etag})
        if method in ("PUT", "DELETE"):
            if not self.writable:
                return httpx.Response(403)
            if self.race:
                self.race = False
                self.write(href, event_content(summary='Synthetic concurrent change'))
            current = self.objects.get(href)
            if request.headers.get('if-none-match') == '*' and current or request.headers.get('if-match') and (not current or request.headers['if-match'] != current[1]):
                return httpx.Response(412)
            if method == "DELETE":
                if not current:
                    return httpx.Response(404)
                self.delete(href)
                return httpx.Response(204)
            self.write(href, request.content)
            if self.lose_write:
                self.lose_write = False
                raise httpx.ReadError("Synthetic acknowledgement loss", request=request)
            return httpx.Response(201 if current is None else 204, headers={"ETag": self.objects[href][1]})
        raise AssertionError(method)


@pytest.fixture
def dav(monkeypatch):
    server = DavServer()
    original = httpx.AsyncClient
    monkeypatch.setattr(transport.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(server), **kwargs))
    async def resolve(url):
        transport.validate_calendar_url(url)
        return transport._Target(url, 'calendar.example.test', 'calendar.example.test', ('93.184.216.34',))
    monkeypatch.setattr(transport, '_resolve', resolve)
    return server


@pytest_asyncio.fixture
async def external(db, agent, dav):
    from app.connection import connection_service
    from app.tools import tool_service
    from app.tools.schemas import ToolCreate
    tool = await tool_service.create_tool(ToolCreate.model_validate({
        "code": "synthetic-caldav-provider", "label": "Synthetic external", "capabilities": ["caldav.calendar"],
        "connection_schema": {"params": {"url": {"type": "password", "required": True},
            "login": {"type": "string"}, "password": {"type": "password"}}},
        "calendar_config": {"settings": {"timezone": "Europe/Paris", "source_kind": "caldav"},
            "param_map": {"url": "url", "username": "login", "password": "password"}}}))
    connection = await connection_service.get_or_create_connection(tool.id, agent.id)
    await connection_service.set_params_bulk(connection.id, {"url": URL, "login": "synthetic-login", "password": "synthetic-secret"})
    read = (await service.list_feeds(connection_id=connection.id))[0]
    return await service.get_feed(read.id)


@pytest.mark.asyncio
async def test_caldav_continuation_collects_all_changes_before_advancing_the_cursor(db, agent, external, dav):
    dav.page_size = 1
    for index in range(3):
        dav.write(URL + f'part-{index}.ics', event_content(uid=f'synthetic-part-{index}@example.test'))
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert decrypt(external.sync_token_encrypted) == str(dav.version)
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == 3
    dav.delete(URL + 'part-0.ics')
    dav.write(URL + 'part-1.ics', event_content(uid='synthetic-part-1@example.test', summary='Synthetic changed'))
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert decrypt(external.sync_token_encrypted) == str(dav.version)
    window = await service.event_window(agent.id, NOW, NOW + timedelta(days=1))
    assert window.total == 2 and any(row.summary == 'Synthetic changed' for row in window.items)


@pytest.mark.asyncio
async def test_caldav_bidirectional_diff_and_offline_commands_are_idempotent(db, agent, external, dav):
    feed = external
    href = URL + 'existing.ics'
    dav.write(href, event_content())
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert feed.initialized and feed.writable
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == 1
    calls = len(dav.calls)
    created = await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary="Synthetic local event",
        start=NOW + timedelta(hours=2), end=NOW + timedelta(hours=3)))
    assert len(dav.calls) == calls
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == 2
    assert len(dav.calls) == calls
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert len(dav.objects) == 2
    assert len([call for call in dav.calls if call[0] == 'PUT']) == 1
    assert [call for call in dav.calls if call[0] == 'PUT'][0][2]['if-none-match'] == '*'
    updated = await service.update_calendar_event(feed.id, agent.id, created.uid, CalendarEventUpdate(expected_revision=1, summary="Synthetic edited"))
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert 'if-match' in [call for call in dav.calls if call[0] == 'PUT'][-1][2]
    await service.delete_calendar_event(feed.id, agent.id, created.uid, CalendarEventDelete(expected_revision=updated.revision))
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert len(dav.objects) == 1
    dav.delete(href)
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == 0
    reports = [call for call in dav.calls if call[0] == 'REPORT']
    assert len(reports) >= 5
    assert all(row.state == 'success' for row in (await db.scalars(select(CalendarSyncOperation))).all())
    serialized = service.serialize_feed(feed, agent.id).model_dump_json()
    assert 'synthetic-secret' not in serialized and 'synthetic-login' not in serialized


@pytest.mark.asyncio
async def test_remote_conflict_preserves_local_event_and_remote_evidence(db, agent, external, dav):
    href = URL + 'existing.ics'
    dav.write(href, event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    event = (await db.scalars(select(CalendarEvent))).one()
    await service.update_calendar_event(external.id, agent.id, event.uid, CalendarEventUpdate(expected_revision=1, summary="Synthetic local choice"))
    dav.write(href, event_content(summary="Synthetic remote choice"))
    await synchronize_calendar(external.id, agent_id=agent.id)
    await db.refresh(event)
    assert event.conflict
    assert 'Synthetic remote choice' in decrypt(event.remote_content_encrypted)
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).items[0].summary == 'Synthetic local choice'
    assert not [call for call in dav.calls if call[0] == 'PUT']
    assert (await db.scalars(select(CalendarSyncOperation))).one().state == 'conflict'


@pytest.mark.asyncio
async def test_lost_write_acknowledgement_and_expired_token_reconcile_without_duplicate(db, agent, external, dav):
    await synchronize_calendar(external.id, agent_id=agent.id)
    created = await service.create_calendar_event(external.id, agent.id, CalendarEventCreate(summary="Synthetic replay",
        start=NOW, end=NOW + timedelta(hours=1)))
    dav.lose_write = True
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert len(dav.objects) == 1 and external.last_error
    dav.expired = True
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert len(dav.objects) == 1
    assert (await db.scalars(select(CalendarSyncOperation))).one().state == 'success'
    assert (await db.scalars(select(CalendarEvent))).one().id == created.event_id


@pytest.mark.asyncio
async def test_failed_sync_is_logged_persisted_and_does_not_erase_local_data_or_advance_token(db, agent, external, dav):
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    token = external.sync_token_encrypted
    dav.fail = True
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert external.sync_token_encrypted == token and external.last_error
    page = await service.event_window(agent.id, NOW, NOW + timedelta(days=1))
    assert page.total == 1 and not page.complete
    assert (await service.availability_for_agent(agent.id, NOW, NOW + timedelta(hours=1))).available is None
    runs = list((await db.scalars(select(CalendarSyncRun).order_by(CalendarSyncRun.started_at))).all())
    assert runs[-1].state == 'error' and runs[-1].stage == 'read' and runs[-1].error_category == 'ConnectError'
    assert 'synthetic-secret' not in json.dumps([run.error_category for run in runs])


@pytest.mark.asyncio
async def test_readonly_provider_cannot_be_mutated_and_invalid_payload_never_deletes_existing_events(db, agent, external, dav):
    agent_id, calendar_id = agent.id, external.id
    dav.writable = False
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    with pytest.raises(PermissionError):
        await service.create_calendar_event(external.id, agent.id, CalendarEventCreate(summary="Forbidden", start=NOW, end=NOW + timedelta(hours=1)))
    dav.write(URL + 'invalid.ics', b'not a calendar')
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    assert (await service.event_window(agent_id, NOW, NOW + timedelta(days=1))).total == 1
    assert await db.scalar(select(func.count()).select_from(CalendarEvent)) == 1


@pytest.mark.parametrize('period,days', [('month',30), ('week',7), ('day',1), ('next30',30)])
def test_frontend_date_filters_use_local_calendar_boundaries(period, days):
    lower, upper = service.date_window(period, now=NOW)
    assert upper - lower == timedelta(days=days)
    if period != 'next30':
        assert lower.astimezone(service.ZoneInfo('Europe/Paris')).hour == 0


def test_day_and_month_filters_respect_daylight_saving():
    lower, upper = service.date_window('day', now=datetime(2026,3,29,12,tzinfo=timezone.utc))
    assert upper - lower == timedelta(hours=23)
    lower, upper = service.date_window('month', month='2026-10')
    assert upper - lower == timedelta(days=31,hours=1)


@pytest.mark.asyncio
async def test_conditional_write_catches_a_change_between_read_and_put(db, agent, external, dav):
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    event = (await db.scalars(select(CalendarEvent))).one()
    await service.update_calendar_event(external.id, agent.id, event.uid, CalendarEventUpdate(expected_revision=1, summary='Synthetic local edit'))
    dav.race = True
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert event.conflict
    assert 'Synthetic concurrent change' in decrypt(event.remote_content_encrypted)
    assert (await db.scalars(select(CalendarSyncOperation))).one().state == 'conflict'


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['local', 'remote'])
async def test_conflicts_require_a_revision_and_preserve_the_chosen_version(db, agent, external, dav, choice):
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    event = (await db.scalars(select(CalendarEvent))).one()
    await service.update_calendar_event(external.id, agent.id, event.uid, CalendarEventUpdate(expected_revision=1, summary='Synthetic local version'))
    dav.write(URL + 'existing.ics', event_content(summary='Synthetic remote version'))
    await synchronize_calendar(external.id, agent_id=agent.id)
    from app.calendar.store import CalendarConflictError
    with pytest.raises(CalendarConflictError):
        await service.resolve_conflict(external.id, agent.id, event.uid, 99, choice)
    await service.resolve_conflict(external.id, agent.id, event.uid, 2, choice)
    await synchronize_calendar(external.id, agent_id=agent.id)
    detail = await service.event_detail(external.id, event.uid)
    assert detail.summary == f'Synthetic {choice} version' and not event.conflict


@pytest.mark.asyncio
async def test_invalid_multistatus_preserves_replica_and_permission_changes_are_rechecked(db, agent, external, dav):
    calendar_id, agent_id = external.id, agent.id
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    dav.malformed = True
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    assert (await service.event_window(agent_id, NOW, NOW + timedelta(days=1))).total == 1
    dav.malformed = False
    dav.writable = False
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    feed = await service.get_feed(calendar_id)
    assert not feed.writable
    dav.writable = True
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    assert feed.writable


def test_caldav_paths_and_xml_entities_are_rejected():
    from bridge.calendar import caldav
    for href in ('https://other.example.test/event.ics', '/outside/event.ics', URL + '%2e%2e/outside.ics'):
        with pytest.raises(ValueError):
            caldav.resource_href(URL, href)
    with pytest.raises(ValueError):
        caldav._xml(b'<!DOCTYPE x [<!ENTITY value "private">]><x/>')


@pytest.mark.asyncio
async def test_sync_lease_prevents_parallel_provider_reads_and_fences_configuration_changes(committed_database, monkeypatch, dav):
    from app.connection import Connection
    from app.tools.models import Tool
    from app.agent.models import Agent, Title
    from core.database import get_db_session
    from core.user import UserModel
    async with get_db_session() as db:
        user = UserModel(email='synthetic-sync-owner@example.test', hashed_password='unused', display_name='Synthetic owner', is_active=True)
        title = Title(label='Synthetic', gender='M')
        db.add_all([user,title])
        await db.flush()
        agent = Agent(title_id=title.id, user_id=user.id, first_name='Synthetic', last_name='Sync', code='synthetic-concurrent-sync')
        tool = Tool(code='synthetic-caldav-concurrency', label='Synthetic CalDAV', calendar_config={})
        db.add_all([agent,tool])
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        feed = CalendarFeed(connection_id=connection.id, label='Synthetic calendar', source_kind='caldav',
            url_encrypted=service.encrypt(URL), source_root_encrypted=service.encrypt(URL))
        db.add(feed)
        await db.flush()
        calendar_id, agent_id = feed.id, agent.id
    dav.write(URL + 'existing.ics', event_content())
    dav.report_started, dav.report_release = asyncio.Event(), asyncio.Event()
    async def run():
        async with get_db_session():
            return await synchronize_calendar(calendar_id, agent_id=agent_id)
    first = asyncio.create_task(run())
    await asyncio.wait_for(dav.report_started.wait(), 3)
    assert await run() == 0
    async with get_db_session() as db:
        feed = await db.get(CalendarFeed, calendar_id)
        feed.source_revision += 1
    dav.report_release.set()
    await first
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(CalendarEvent)) == 0
        run_row = (await db.scalars(select(CalendarSyncRun))).one()
        assert run_row.state == 'error' and run_row.error_category == 'StaleSyncError'


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['not-a-calendar-url', 'https://other.example.test/changed/'])
async def test_invalid_source_configuration_keeps_reads_local_and_never_falls_back_to_the_old_provider(db, agent, external, dav, url):
    from app.connection import connection_service
    calendar_id, agent_id, connection_id = external.id, agent.id, external.connection_id
    dav.write(URL + 'existing.ics', event_content())
    await synchronize_calendar(calendar_id, agent_id=agent_id)
    await connection_service.set_params_bulk(connection_id, {'url': url})
    calls = len(dav.calls)
    await service.sync_calendars()
    assert len(dav.calls) == calls
    window = await service.event_window(agent_id, NOW, NOW + timedelta(days=1))
    assert window.total == 1 and not window.complete
    assert len(await service.list_feeds(connection_id=connection_id)) == 1
    assert (await service.sync_runs(calendar_id))[0].stage == 'configuration'


@pytest.mark.asyncio
async def test_ical_subscription_uses_conditional_reads_and_the_same_local_structure(db, agent, external, dav):
    from app.connection import connection_service
    from app.tools import tool_service
    from app.tools.schemas import ToolUpdate
    connection = await connection_service.get_connection(external.connection_id)
    await tool_service.update_tool(connection.tool_id, ToolUpdate(calendar_config={
        'settings': {'source_kind':'ical', 'timezone':'Europe/Paris'},
        'param_map': {'url':'url', 'username':'login', 'password':'password'}}))
    await service._refresh_parameter_feed(connection.id)
    dav.write(URL, event_content())
    await synchronize_calendar(external.id, agent_id=agent.id)
    before = await db.scalar(select(func.count()).select_from(CalendarEvent))
    await synchronize_calendar(external.id, agent_id=agent.id)
    assert (await service.event_window(agent.id, NOW, NOW + timedelta(days=1))).total == before == 1
    assert all(method == 'GET' for method,_,_ in dav.calls)
    assert 'if-none-match' in dav.calls[-1][2]
    with pytest.raises(PermissionError):
        await service.create_calendar_event(external.id, agent.id, CalendarEventCreate(summary='Forbidden subscription write', start=NOW, end=NOW+timedelta(hours=1)))
