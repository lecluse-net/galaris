"""Synthetic provider HTTP contracts, canonical persistence and safe retries."""
import asyncio
import copy
import json
import socket
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import httpx
import httpx2
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.calendar import ical, service
from app.calendar.models import CalendarEvent, CalendarFeed
from app.calendar.crypto import decrypt
from app.calendar.schemas import CalendarEventCreate, CalendarEventUpdate, CalendarEventDelete
from app.calendar.synchronization import synchronize_calendar
from app.connection import connection_service, oauth_service
from app.tools import tool_service
from app.tools.schemas import ToolCreate
from bridge.calendar import transport
from bridge.calendar.rest import RestCalendarProvider, LOCAL_PROPERTY
from bridge.calendar.rest_codec import decode, encode

NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


class ProviderServer:
    def __init__(self, kind):
        self.google = kind == 'google'
        self.objects = {}
        self.version = 0
        self.calls = []
        self.lost = False
        self.fail_page = False
        self.readonly = False
        self.conflict = False
        self.authorizations = []

    def save(self, identity, data):
        self.version += 1
        data = copy.deepcopy(data)
        data.update(id=identity)
        data['etag' if self.google else '@odata.etag'] = f'"v{self.version}"'
        if not self.google:
            data.setdefault('type', 'singleInstance')
        self.objects[identity] = data
        return data

    def handle(self, request):
        path = unquote(request.url.path)
        self.calls.append((request.method, path))
        self.authorizations.append(request.headers.get('authorization'))
        if path.endswith('/calendarList') or path.endswith('/calendars'):
            calendars = [dict(id='synthetic-main', summary='Synthetic Google', accessRole='reader' if self.readonly else 'owner'),
                         dict(id='synthetic-other', summary='Synthetic shared', accessRole='reader')] if self.google else [
                         dict(id='synthetic-main', name='Synthetic Outlook', canEdit=not self.readonly),
                         dict(id='synthetic-other', name='Synthetic shared', canEdit=False)]
            return httpx.Response(200, json={'items' if self.google else 'value': calendars})
        if '/synthetic-other/' in path:
            return httpx.Response(200, json={'items' if self.google else 'value': []})
        base = path.endswith('/events')
        if base and request.method == 'GET':
            if self.fail_page:
                return httpx.Response(200, json={'unexpected': []})
            values = list(self.objects.values())
            query = parse_qs(request.url.query.decode())
            if '$filter' in query:
                key = query['$filter'][0].split("ep/value eq '")[1].split("'")[0]
                values = [item for item in values if any(prop.get('id') == LOCAL_PROPERTY and prop.get('value') == key for prop in item.get('singleValueExtendedProperties', []))]
            return httpx.Response(200, json={'items' if self.google else 'value': values})
        identity = path.rsplit('/', 1)[-1]
        if request.method == 'POST':
            data = json.loads(request.content)
            identity = data.get('id') if self.google else 'synthetic-' + data['transactionId']
            if identity in self.objects:
                return httpx.Response(409)
            result = self.save(identity, data)
            if self.lost:
                self.lost = False
                raise httpx.ReadError('Synthetic lost acknowledgement', request=request)
            return httpx.Response(201, json=result)
        if request.method == 'GET':
            return httpx.Response(200, json=self.objects[identity]) if identity in self.objects else httpx.Response(404)
        current = self.objects.get(identity)
        if current is None:
            return httpx.Response(404)
        if request.headers.get('if-match') != current['etag' if self.google else '@odata.etag'] or self.conflict:
            return httpx.Response(412)
        if request.method == 'DELETE':
            self.objects.pop(identity)
            return httpx.Response(204)
        assert request.method == 'PATCH'
        current.update(json.loads(request.content))
        return httpx.Response(200, json=self.save(identity, current))


@pytest_asyncio.fixture(params=['google', 'microsoft'])
async def provider(db, agent, monkeypatch, request):
    kind = request.param
    server = ProviderServer(kind)
    original = httpx.AsyncClient
    monkeypatch.setattr(transport.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(server.handle), **kwargs))
    async def resolve(host, port, **kwargs):
        assert host in ('www.googleapis.com', 'graph.microsoft.com')
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', port))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', resolve)
    tool = await tool_service.create_tool(ToolCreate.model_validate({
        'code': 'synthetic-' + kind, 'label': 'Synthetic provider', 'capabilities': ['caldav.calendar'],
        'calendar_config': {'settings': {'source_kind': kind}, 'param_map': {'client_id': 'client_id', 'client_secret': 'client_secret'}},
        'connection_schema': {'params': {'client_id': {'type': 'string'}, 'client_secret': {'type': 'password'}}}}))
    connection = await connection_service.get_or_create_connection(tool.id, agent.id)
    await connection_service.set_params_bulk(connection.id, {'client_id': 'synthetic-app', 'client_secret': 'synthetic-secret'})
    async def oauth_client(url, server_url):
        return httpx2.AsyncClient(transport=httpx2.MockTransport(lambda req: httpx2.Response(200, json={
            'access_token': 'synthetic-calendar-access', 'token_type': 'Bearer', 'refresh_token': 'synthetic-refresh', 'expires_in': 3600})))
    monkeypatch.setattr(oauth_service, '_client', oauth_client)
    started = await oauth_service.start(connection, agent.user_id, purpose='calendar')
    state = parse_qs(urlsplit(started.authorization_url).query)['state'][0]
    await oauth_service.complete(connection, oauth_service.OAuthCallback(state=state, code='synthetic-code'), agent.user_id)
    feed = (await service.list_feeds(connection_id=connection.id))[0]
    return server, await service.get_feed(feed.id), connection


@pytest.mark.asyncio
async def test_native_provider_roundtrip_permissions_and_lost_creation(db, agent, provider):
    server, feed, connection = provider
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await db.refresh(feed)
    assert feed.writable and feed.initialized and feed.last_error is None and feed.sync_interval_hours == 2
    feeds = (await db.scalars(select(CalendarFeed).where(CalendarFeed.connection_id == connection.id))).all()
    shared = next(item for item in feeds if item.id != feed.id)
    assert not shared.writable and shared.sync_interval_hours == 2
    with pytest.raises(PermissionError):
        await service.create_calendar_event(shared.id, agent.id, CalendarEventCreate(summary='Denied', start=NOW, end=NOW + timedelta(hours=1)))
    await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary='Synthetic native event',
        start=NOW, end=NOW + timedelta(hours=1)))
    server.lost = True
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert len(server.objects) == 1
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await db.refresh(feed)
    assert len(server.objects) == 1 and feed.last_error is None
    event = (await db.scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id))).one()
    assert event.synced_revision == event.revision and not event.conflict
    assert not decrypt(event.remote_href_encrypted).endswith('.ics')
    if not server.google:
        next(iter(server.objects.values()))['body']['contentType'] = 'html'
    await service.update_calendar_event(feed.id, agent.id, event.uid, CalendarEventUpdate(expected_revision=event.revision, summary='Changed locally'))
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await db.refresh(event)
    assert event.synced_revision == event.revision and not event.conflict
    assert next(iter(server.objects.values()))['summary' if server.google else 'subject'] == 'Changed locally'
    if not server.google:
        assert next(iter(server.objects.values()))['body']['contentType'] == 'html'
    server.fail_page = True
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await db.refresh(event)
    assert event.deleted_at is None
    server.fail_page = False
    await service.delete_calendar_event(feed.id, agent.id, event.uid, CalendarEventDelete(expected_revision=event.revision))
    await synchronize_calendar(feed.id, agent_id=agent.id)
    assert server.objects == {}
    assert all(value == 'Bearer synthetic-calendar-access' for value in server.authorizations)
    revision = feed.source_revision
    feed.lease_token, feed.lease_expires_at = uuid4(), NOW + timedelta(days=365)
    await db.commit()
    await oauth_service.disconnect(connection, 'calendar')
    await db.refresh(feed)
    assert feed.source_revision == revision + 1 and feed.lease_token is None and feed.next_sync_at is None


@pytest.mark.asyncio
async def test_native_conditional_conflict_preserves_both_versions(db, agent, provider):
    server, feed, _ = provider
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await service.create_calendar_event(feed.id, agent.id, CalendarEventCreate(summary='Remote original', start=NOW, end=NOW + timedelta(hours=1)))
    await synchronize_calendar(feed.id, agent_id=agent.id)
    event = (await db.scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == feed.id))).one()
    await service.update_calendar_event(feed.id, agent.id, event.uid, CalendarEventUpdate(expected_revision=event.revision, summary='Local proposal'))
    server.conflict = True
    await synchronize_calendar(feed.id, agent_id=agent.id)
    await db.refresh(event)
    assert event.conflict and event.synced_revision < event.revision
    assert 'Local proposal' in decrypt(event.content_encrypted)
    assert next(iter(server.objects.values()))['summary' if server.google else 'subject'] == 'Remote original'


@pytest.mark.parametrize('google', [True, False])
@pytest.mark.parametrize('all_day', [True, False])
def test_native_codec_preserves_local_resource_and_provider_changes(google, all_day):
    start = date(2026, 11, 15) if all_day else NOW
    content = ical.create_event(ical.EMPTY_CALENDAR, CalendarEventCreate(summary='Synthetic event', start=start,
        end=start + timedelta(days=1) if all_day else start + timedelta(hours=1), uid='synthetic@example.test'))[0]
    payload = encode(content, google)
    payload['id'] = 'synthetic-id'
    payload['iCalUID' if google else 'iCalUId'] = 'different-provider-uid'
    assert ical.resource_digest(decode(payload, google)) == ical.resource_digest(content)
    payload['summary' if google else 'subject'] = 'Changed remotely'
    resource = ical.split_resources(decode(payload, google))[0]
    assert resource.uid == 'synthetic@example.test' and 'Changed remotely' in resource.master


@pytest.mark.parametrize('google', [True, False])
def test_series_writes_fail_before_any_partial_provider_mutation(google):
    content = ical.create_event(ical.EMPTY_CALENDAR, CalendarEventCreate(summary='Synthetic series', start=NOW,
        end=NOW + timedelta(hours=1), rrule='FREQ=DAILY;COUNT=3'))[0]
    with pytest.raises(ValueError, match='Recurring series'):
        encode(content, google)


@pytest.mark.parametrize('google', [True, False])
def test_native_recurring_import_retains_dst_moved_and_cancelled_occurrences(google):
    if google:
        master = {'id': 'synthetic-series', 'iCalUID': 'series@example.test', 'summary': 'Synthetic series',
            'start': {'dateTime': '2026-10-24T09:00:00+02:00', 'timeZone': 'Europe/Paris'},
            'end': {'dateTime': '2026-10-24T10:00:00+02:00', 'timeZone': 'Europe/Paris'}, 'recurrence': ['RRULE:FREQ=DAILY;COUNT=4']}
        moved = {**master, 'recurrence': [], 'summary': 'Synthetic moved',
            'originalStartTime': {'dateTime': '2026-10-26T09:00:00+01:00', 'timeZone': 'Europe/Paris'},
            'start': {'dateTime': '2026-10-26T10:00:00+01:00', 'timeZone': 'Europe/Paris'},
            'end': {'dateTime': '2026-10-26T11:00:00+01:00', 'timeZone': 'Europe/Paris'}}
        cancelled = {'status': 'cancelled', 'originalStartTime': {'dateTime': '2026-10-25T09:00:00+01:00', 'timeZone': 'Europe/Paris'}}
        exceptions = [moved, cancelled]
    else:
        master = {'id': 'synthetic-series', 'iCalUId': 'series@example.test', 'subject': 'Synthetic series',
            'start': {'dateTime': '2026-10-24T09:00:00', 'timeZone': 'Romance Standard Time'},
            'end': {'dateTime': '2026-10-24T10:00:00', 'timeZone': 'Romance Standard Time'},
            'recurrence': {'pattern': {'type': 'daily', 'interval': 1}, 'range': {'type': 'numbered', 'numberOfOccurrences': 4}},
            'cancelledOccurrences': ['OID.synthetic.2026-10-25']}
        exceptions = [{**master, 'recurrence': None, 'subject': 'Synthetic moved', 'originalStart': '2026-10-26T08:00:00Z',
            'start': {'dateTime': '2026-10-26T10:00:00', 'timeZone': 'Romance Standard Time'},
            'end': {'dateTime': '2026-10-26T11:00:00', 'timeZone': 'Romance Standard Time'}}]
    content = decode(master, google, exceptions)
    events = ical.events_between(content, datetime(2026, 10, 24, tzinfo=timezone.utc), datetime(2026, 10, 28, tzinfo=timezone.utc))
    assert [(event.start.day, event.start.hour, event.summary) for event in events] == [
        (24, 7, 'Synthetic series'), (26, 9, 'Synthetic moved'), (27, 8, 'Synthetic series')]


@pytest.mark.asyncio
async def test_api_pagination_never_sends_tokens_to_another_origin(monkeypatch):
    calls = []
    async def response(method, url, **kwargs):
        calls.append(url)
        from app.calendar.contracts import CalendarHttpResponse
        return CalendarHttpResponse(json.dumps({'value': [], '@odata.nextLink': 'https://untrusted.example.test/capture'}).encode(), url, {})
    monkeypatch.setattr('bridge.calendar.rest.request_calendar', response)
    with pytest.raises(ValueError, match='escaped'):
        await RestCalendarProvider('microsoft', 'synthetic-token').discover('https://graph.microsoft.com/v1.0/me/calendars', username=None, password=None)
    assert len(calls) == 1
