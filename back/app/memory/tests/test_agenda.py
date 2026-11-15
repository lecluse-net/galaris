"""Memory remains the owner of informational calendar projections and their access."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.memory import service, ensure_contact_memory_scope, observe_messenger_contact, MessengerContactObservation
from app.memory.agenda import memory_agenda
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload
from app.memory.temporal import MemoryTemporalAnchor
from app.calendar import context as calendar_context, dispatch
from app.calendar.models import CalendarEvent, CalendarTrigger
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.services import sync_integrated_service_connections


async def remember(agent, title, **parts):
    return (await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, title=title, media_type='text/html',
        payload=MemoryPayload(text=f'<p>{title}</p>'), temporal=MemoryTemporalAnchor(**parts))))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('recurring', [False, True])
async def test_dense_memory_agenda_reads_bounded_metadata_without_loading_content(agents, db, monkeypatch, recurring):
    import json
    from pathlib import Path
    from time import perf_counter
    from uuid import uuid4
    from sqlalchemy import event
    from app.memory.models import MemoryItem

    owner, peer = agents
    agent_id = owner.id
    monkeypatch.setenv('TZ', 'Europe/Paris')
    rows = [dict(id=uuid4(), owner_agent_id=agent_id if index % 2 else peer.id,
        resource_id=f'synthetic-dense-agenda-{index}', title=f'Synthetic observation {index}',
        content_hash=f'{index:064x}', content='<p>' + 'Synthetic content. ' * 1000 + '</p>',
        search_text='Synthetic evidence. ' * 1000,
        metadata={'synthetic': 'Synthetic metadata. ' * 1000},
        temporal=dict(minute=30) if recurring else dict(month=11, day=1 + index % 28)) for index in range(1200)]
    await db.execute(MemoryItem.__table__.insert(), rows)
    await db.commit()
    db.expunge_all()
    queries, loaded = [], []
    connection = await db.connection()

    def observe_sql(_connection, _cursor, statement, _parameters, context, _many):
        context._agenda_started = perf_counter()

    def finish_sql(_connection, _cursor, statement, _parameters, context, _many):
        queries.append({'seconds': perf_counter() - context._agenda_started, 'sql': statement})

    def observe_item(item, _context):
        loaded.append('memory_content' in item.__dict__ or 'metadata_' in item.__dict__)

    event.listen(connection.sync_connection, 'before_cursor_execute', observe_sql)
    event.listen(connection.sync_connection, 'after_cursor_execute', finish_sql)
    event.listen(MemoryItem, 'load', observe_item)
    samples = []
    try:
        for _ in range(1 if recurring else 3):
            started = perf_counter()
            page = await memory_agenda(agent_id, datetime(2026, 11, 1, tzinfo=timezone.utc),
                datetime(2026, 12, 1, tzinfo=timezone.utc), limit=50 if recurring else 10_000)
            samples.append(perf_counter() - started)
            assert len(page.items) == (50 if recurring else 600) and page.complete != recurring
            if recurring:
                from uuid import NAMESPACE_URL, uuid5
                lower = datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)
                expected = sorted((uuid5(NAMESPACE_URL, f"memory://{row['id']}/occurrences/{lower.isoformat()}"), row['id'])
                    for row in rows if row['owner_agent_id'] == agent_id)[:50]
                assert [(item.id, item.memory_id) for item in page.items] == expected
            else:
                assert {item.memory_id for item in page.items} == {row['id'] for row in rows if row['owner_agent_id'] == agent_id}
            assert all(len(item.excerpt) == 1200 for item in page.items)
    finally:
        event.remove(connection.sync_connection, 'before_cursor_execute', observe_sql)
        event.remove(connection.sync_connection, 'after_cursor_execute', finish_sql)
        event.remove(MemoryItem, 'load', observe_item)
    report = {'total_items': len(rows), 'visible_items': len(page.items), 'samples_seconds': samples,
        'query_count': len(queries), 'queries': queries}
    compact = await memory_agenda(agent_id, datetime(2026, 11, 1, tzinfo=timezone.utc),
        datetime(2026, 12, 1, tzinfo=timezone.utc), limit=50 if recurring else 10_000, include_excerpt=False)
    assert compact.items == [item.model_copy(update={'excerpt': ''}) for item in page.items]
    report['response_bytes'] = len(page.model_dump_json().encode())
    report['compact_response_bytes'] = len(compact.model_dump_json().encode())
    destination = Path('../artifacts/memory-agenda-benchmark' + ('-recurring' if recurring else '') + '.json')
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2))
    print({key: value for key, value in report.items() if key != 'queries'})
    assert not any(loaded), 'Agenda must not hydrate memory content or arbitrary metadata'
    assert len(queries) <= 36, 'Agenda queries must remain batched for a dense month'


@pytest.mark.asyncio
async def test_memory_agenda_rechecks_live_scope_and_reads_current_values_after_source_admission(agents, memory_storage, db, monkeypatch):
    from app.memory import agenda
    from app.memory.models import MemoryItem
    from sqlalchemy import update
    owner, peer = agents
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    moved, expired, erased, edited = [await remember(owner, f'Synthetic concurrent date {index}', month=11, day=14)
        for index in range(4)]
    stable = await remember(owner, 'Synthetic unchanged date', month=11, day=12)
    stable_id = stable.id
    moved_id, expired_id, erased_id, edited_id = moved.id, expired.id, erased.id, edited.id
    original = agenda.readable_source_ids

    async def admit(identities, agent_id):
        result = await original(identities, agent_id)
        await db.execute(update(MemoryItem).where(MemoryItem.id == moved_id).values(owner_agent_id=peer.id))
        await db.execute(update(MemoryItem).where(MemoryItem.id == expired_id).values(valid_until=datetime(2020, 1, 1, tzinfo=timezone.utc)))
        await db.execute(update(MemoryItem).where(MemoryItem.id == erased_id).values(temporal=None))
        await db.execute(update(MemoryItem).where(MemoryItem.id == edited_id).values(
            search_title='Synthetic current title', memory_revision=2, temporal={'month': 11, 'day': 11}))
        await db.flush()
        return result

    monkeypatch.setattr(agenda, 'readable_source_ids', admit)
    page = await memory_agenda(owner.id, start, start + timedelta(days=30))
    assert [item.memory_id for item in page.items] == [edited_id, stable_id]
    assert page.items[0].title == 'Synthetic current title' and page.items[0].revision == 2
    assert page.items[0].temporal.day == 11


@pytest.mark.asyncio
async def test_memory_agenda_refreshes_validity_time_between_ranking_and_admission(agents, memory_storage, db, monkeypatch):
    from app.memory import agenda
    owner, _ = agents
    reference = datetime.now(timezone.utc)
    item = await remember(owner, 'Synthetic expiring context', year=reference.year)
    item.valid_until = reference + timedelta(seconds=1)
    await db.commit()
    clock = {'now': reference}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock['now'].astimezone(tz or timezone.utc)

    original = agenda.readable_source_ids

    async def admit(identities, agent_id):
        result = await original(identities, agent_id)
        clock['now'] = reference + timedelta(seconds=2)
        return result

    monkeypatch.setattr(agenda, 'datetime', Clock)
    monkeypatch.setattr(agenda, 'readable_source_ids', admit)
    assert not (await memory_agenda(owner.id, reference, reference + timedelta(days=1))).items


@pytest.mark.asyncio
async def test_memory_agenda_date_expansion_keeps_other_async_work_responsive(agents, memory_storage, monkeypatch):
    import asyncio
    from threading import Event
    from app.memory import agenda
    owner, _ = agents
    await remember(owner, 'Synthetic expensive date', hour=9)
    entered, release = Event(), Event()
    original = agenda.next_match

    def slow_match(*args):
        entered.set()
        assert release.wait(5), 'Date expansion prevented another asynchronous round from running'
        return original(*args)

    monkeypatch.setattr(agenda, 'next_match', slow_match)
    start = datetime(2026, 11, 14, tzinfo=timezone.utc)
    reading = asyncio.create_task(memory_agenda(owner.id, start, start + timedelta(days=1)))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        release.set()
        assert (await asyncio.wait_for(reading, 5)).items
    finally:
        release.set()
        await asyncio.gather(reading, return_exceptions=True)


@pytest.mark.asyncio
async def test_memory_agenda_limits_chronologically_across_candidate_pages(agents, db, monkeypatch):
    from uuid import NAMESPACE_URL, uuid4, uuid5
    from app.memory.models import MemoryItem
    owner, _ = agents
    monkeypatch.setenv('TZ', 'UTC')
    identities = [uuid4() for _ in range(1001)]
    await db.execute(MemoryItem.__table__.insert(), [dict(id=identity, owner_agent_id=owner.id,
        resource_id=f'synthetic-paged-agenda-{index}', title='Synthetic paged date', content_hash=f'{index:064x}',
        temporal={'month': 11, 'day': 14}) for index, identity in enumerate(identities)])
    await db.commit()
    start = datetime(2026, 11, 14, tzinfo=timezone.utc)
    page = await memory_agenda(owner.id, start, start + timedelta(days=1), limit=5)
    expected = sorted((uuid5(NAMESPACE_URL, f'memory://{identity}/occurrences/{start.isoformat()}'), identity)
        for identity in identities)[:5]
    assert not page.complete and [(item.id, item.memory_id) for item in page.items] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('derived', [False, True])
async def test_memory_agenda_rechecks_source_owned_permissions_on_reopening(agents, memory_storage, db, monkeypatch, derived):
    from sqlalchemy import true
    from app.memory import source_access
    from app.memory.models import MemorySource
    owner, _ = agents
    item = await remember(owner, 'Synthetic source-owned date', month=11, day=14)
    ordinary = await remember(owner, 'Synthetic independent date', month=11, day=14)
    for name in ('_checks', '_batch_readers', '_evidence_checks', '_evidence_batch_readers'):
        monkeypatch.setattr(source_access, name, dict(getattr(source_access, name)))
    readable = True

    async def read_one(*_args):
        return readable

    async def read_many(records, _agent):
        return {record[0] if derived else record for record in records} if readable else set()

    if derived:
        item.metadata_ = {'evidence_validator': 'synthetic-agenda'}
        db.add(MemorySource(item_id=item.id, source_kind='synthetic', source_ref='synthetic:agenda:evidence',
            metadata_={'evidence_validator': 'synthetic-agenda'}))
        source_access.register_source_evidence_access('synthetic-agenda', lambda _column: true(),
            read_one, batch_reader=read_many)
    else:
        item.source_managed, item.read_only = True, True
        item.managed_source_kind, item.managed_source_ref = 'synthetic-agenda', 'synthetic:agenda:source'
        source_access.register_source_access('synthetic-agenda', lambda _column: true(), read_one, batch_reader=read_many)
    await db.commit()
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert {row.memory_id for row in (await memory_agenda(owner.id, start, start + timedelta(days=30))).items} == {item.id, ordinary.id}
    readable = False
    assert [row.memory_id for row in (await memory_agenda(owner.id, start, start + timedelta(days=30))).items] == [ordinary.id]


@pytest.mark.asyncio
async def test_memory_agenda_skips_a_large_revoked_prefix_without_tiny_repeated_admissions(agents, db, monkeypatch):
    from uuid import uuid4
    from sqlalchemy import true, update
    from app.memory import source_access
    from app.memory.models import MemoryItem
    owner, _ = agents
    monkeypatch.setattr(source_access, '_checks', dict(source_access._checks))
    monkeypatch.setattr(source_access, '_batch_readers', dict(source_access._batch_readers))
    batches = []

    async def denied_one(*_args):
        return False

    async def denied_many(identities, _agent):
        batches.append(len(identities))
        if len(batches) == 1:
            # A later admission batch must use the edited date and the final
            # result must remain chronological across the rejected prefix.
            await db.execute(update(MemoryItem).where(MemoryItem.id == visible_id)
                .values(temporal={'month': 11, 'day': 11}))
        return set()

    source_access.register_source_access('synthetic-revoked-agenda', lambda _column: true(),
        denied_one, batch_reader=denied_many)
    rows = [dict(id=uuid4(), owner_agent_id=owner.id, resource_id=f'synthetic-revoked-{index}',
        title='Synthetic revoked date', content_hash=f'{index:064x}', temporal={'month': 11, 'day': 14},
        source_managed=True, read_only=True, managed_source_kind='synthetic-revoked-agenda',
        managed_source_ref=f'synthetic:revoked:{index}') for index in range(300)]
    await db.execute(MemoryItem.__table__.insert(), rows)
    visible_id = uuid4()
    earlier_id = uuid4()
    await db.execute(MemoryItem.__table__.insert(), [dict(id=visible_id, owner_agent_id=owner.id,
        resource_id='synthetic-visible-after-revocation', title='Synthetic live date', content_hash='f' * 64,
        temporal={'month': 11, 'day': 15}), dict(id=earlier_id, owner_agent_id=owner.id,
        resource_id='synthetic-visible-before-revocation', title='Synthetic stable date', content_hash='e' * 64,
        temporal={'month': 11, 'day': 13})])
    await db.commit()
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    page = await memory_agenda(owner.id, start, start + timedelta(days=30), limit=10)
    assert page.complete and [item.memory_id for item in page.items] == [visible_id, earlier_id]
    assert len(batches) <= 5, 'Revoked candidates must be skipped in growing batches'


@pytest.mark.asyncio
async def test_memory_agenda_avoids_jit_compilation_even_in_a_fresh_transaction(agents, memory_storage, db):
    from sqlalchemy import event, text

    owner, _ = agents
    agent_id = owner.id
    await remember(owner, 'Synthetic interactive date', year=2026, month=11, day=14)
    await db.commit()
    # A fresh HTTP request does not inherit search/graph's transaction-local
    # planner policy. Force the expensive compiler on before opening Agenda.
    await db.execute(text('SET LOCAL jit = on'))
    connection = await db.connection()
    settings = []

    def observe(connection, cursor, statement, parameters, context, many):
        if 'SELECT' in statement.upper() and 'memory_items' in statement:
            settings.append(connection.exec_driver_sql('SHOW jit').scalar_one())

    event.listen(connection.sync_connection, 'before_cursor_execute', observe)
    try:
        page = await memory_agenda(agent_id, datetime(2026, 11, 1, tzinfo=timezone.utc),
            datetime(2026, 12, 1, tzinfo=timezone.utc))
        assert len(page.items) == 1
        assert settings and set(settings) == {'off'}
    finally:
        event.remove(connection.sync_connection, 'before_cursor_execute', observe)


@pytest.mark.asyncio
@pytest.mark.parametrize('zone', ['Pacific/Kiritimati', 'Europe/Paris', 'America/Los_Angeles'])
async def test_memory_agenda_keeps_partial_periods_across_local_year_and_month_boundaries(agents, memory_storage, monkeypatch, zone):
    from zoneinfo import ZoneInfo
    owner, _ = agents
    monkeypatch.setenv('TZ', zone)
    start = datetime(2026, 12, 31, 12, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    anchors = [dict(year=2026), dict(year=2027), dict(year=2028), dict(month=12), dict(month=1),
        dict(month=2), dict(year=2027, month=1, day=1), dict(weekday=5), dict(hour=9),
        dict(year=2026, month=1), dict(year=2027, month=12)]
    rows = [await remember(owner, f'Synthetic boundary observation {index}', **anchor) for index, anchor in enumerate(anchors)]
    expected = {rows[index].id for index in (1, 4, 6, 7, 8)}
    if start.astimezone(ZoneInfo(zone)).year == 2026:
        expected.update((rows[0].id, rows[3].id))
    page = await memory_agenda(owner.id, start, end)
    assert {item.memory_id for item in page.items} == expected and page.complete
    assert len([item for item in page.items if item.memory_id == rows[8].id]) == 2


@pytest.mark.asyncio
async def test_memory_agenda_does_not_materialize_unrelated_historical_or_annual_dates(agents, db, monkeypatch):
    from uuid import uuid4
    from sqlalchemy import event
    from app.memory.models import MemoryItem
    owner, _ = agents
    agent_id = owner.id
    monkeypatch.setenv('TZ', 'UTC')
    rows = [dict(id=uuid4(), owner_agent_id=agent_id, resource_id=f'synthetic-agenda-{index}',
        title=f'Synthetic observation {index}', content_hash=f'{index:064x}', search_text='Synthetic evidence',
        temporal=dict(year=2020, month=3) if index % 2 else dict(month=2)) for index in range(500)]
    visible = dict(id=uuid4(), owner_agent_id=agent_id, resource_id='synthetic-visible',
        title='Synthetic visible date', content_hash='f' * 64, search_text='Synthetic current evidence',
        temporal=dict(year=2027, month=3, day=28))
    await db.execute(MemoryItem.__table__.insert(), [*rows, visible])
    await db.commit()
    db.expunge_all()
    loaded = []
    def observed(item, context):
        loaded.append(item.id)
    event.listen(MemoryItem, 'load', observed)
    try:
        page = await memory_agenda(agent_id, datetime(2027, 3, 27, tzinfo=timezone.utc), datetime(2027, 3, 30, tzinfo=timezone.utc))
    finally:
        event.remove(MemoryItem, 'load', observed)
    assert [item.memory_id for item in page.items] == [visible['id']]
    assert len(loaded) <= 2


@pytest.mark.asyncio
async def test_memory_agenda_repeats_preserves_precision_identity_and_never_schedules(agents, memory_storage, db, monkeypatch):
    owner, peer = agents
    monkeypatch.setenv('TZ', 'Europe/Paris')
    start = datetime(2027, 3, 27, 12, tzinfo=timezone.utc)
    end = start + timedelta(days=3)
    day = await remember(owner, 'Synthetic annual observation', month=3, day=28)
    hour = await remember(owner, 'Synthetic daily habit', hour=9)
    await remember(peer, 'Synthetic private observation', month=3, day=28)
    page = await memory_agenda(owner.id, start, end)
    assert len(page.items) == 4 and page.complete
    annual = next(row for row in page.items if row.memory_id == day.id)
    assert annual.all_day and annual.end - annual.start == timedelta(hours=23)
    habits = [row for row in page.items if row.memory_id == hour.id]
    assert len(habits) == 3 and all(row.end - row.start == timedelta(hours=1) for row in habits)
    overlap = await memory_agenda(owner.id, start + timedelta(days=1), end)
    assert {row.id for row in overlap.items} <= {row.id for row in page.items}
    limited = await memory_agenda(owner.id, start, end, limit=2)
    assert limited.items == page.items[:2] and not limited.complete
    assert not (await memory_agenda(peer.id, start + timedelta(days=2), end)).items
    assert await dispatch.dispatch_due(now=start) == 0
    assert await db.scalar(select(func.count()).select_from(CalendarEvent)) == 0
    assert await db.scalar(select(func.count()).select_from(CalendarTrigger)) == 0
    await service.update_item(day.id, MemoryItemUpdate(expected_revision=day.revision, temporal=None), actor_agent_id=owner.id)
    assert all(row.memory_id != day.id for row in (await memory_agenda(owner.id, start, end)).items)
    assert (await service.get_item(day.id, agent_id=owner.id))[1]


@pytest.mark.asyncio
async def test_memory_agenda_keeps_contact_scope_and_current_validity(agents, memory_storage, db):
    owner, _ = agents
    now = datetime.now(timezone.utc)
    contacts = [await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id='synthetic-agenda', user_id=key, display_name=key)) for key in ('Synthetic A', 'Synthetic B')]
    a = await remember(owner, 'Synthetic A anniversary', year=now.year)
    b = await remember(owner, 'Synthetic B anniversary', year=now.year)
    global_fact = await remember(owner, 'Synthetic unscoped period', year=now.year)
    for contact, item in zip(contacts, (a, b), strict=True):
        await ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=contact,
            memory_item_id=item.id, source_kind='manual', source_ref=f'manual:{item.id}')
    expired = await remember(owner, 'Synthetic expired period', year=now.year)
    expired.valid_until = now - timedelta(days=1)
    await db.commit()
    page = await memory_agenda(owner.id, now, now + timedelta(days=1), contact_item_id=contacts[0])
    assert {row.memory_id for row in page.items} == {a.id, global_fact.id}
    assert (await memory_agenda(owner.id, now, now + timedelta(days=1))).items


@pytest.mark.asyncio
async def test_calendar_context_contains_memory_once_with_live_preferences(agents, memory_storage, monkeypatch, db):
    import json
    from app.memory.context import build_memory_brief
    from core.params import runtime_settings
    owner, _ = agents
    await sync_integrated_service_connections(owner.id)
    now = datetime.now(timezone.utc)
    item = await remember(owner, 'Synthetic period for agent awareness', year=now.year)
    request = AgentContextRequest(task_id=None,
        agent=AgentSnapshot(owner.id, owner.code, 'Synthetic', 'Agenda', 'internal'), objective='')
    monkeypatch.setattr(runtime_settings, 'AGENDA_CONTEXT_DAYS', 4)
    monkeypatch.setattr(runtime_settings, 'AGENDA_CONTEXT_MAX_EVENTS', 3)
    contribution = await calendar_context.calendar_context_provider(request)
    snapshot = json.loads(contribution.system_instructions.split('<upcoming_calendar_events>\n')[1].split('\n</upcoming_calendar_events>')[0])
    assert len(snapshot['items']) == 1
    projected = snapshot['items'][0]
    assert projected['source_uri'] == f'memory://{item.id}' and projected['informational']
    assert projected['temporal']['year'] == now.year
    from app.memory.models import MemoryUsage
    assert await db.scalar(select(func.count()).select_from(MemoryUsage).where(
        MemoryUsage.item_id == item.id, MemoryUsage.access_kind == 'context')) == 1
    assert datetime.fromisoformat(snapshot['until']) - datetime.fromisoformat(snapshot['as_of']) == timedelta(days=4)
    assert not (await build_memory_brief(agent_id=owner.id, query='')).items
    from app.connection.facade import set_service_function_state
    from app.services import service
    tool = await service.get_service_record('memory')
    await set_service_function_state(tool.id, 'memory_upcoming', 'disabled')
    contribution = await calendar_context.calendar_context_provider(request)
    assert contribution.metadata['calendar_context_count'] == 0


@pytest.mark.asyncio
async def test_memory_agenda_http_requires_management_and_memory_rights(client, memory_storage, monkeypatch):
    from app.agent import AgentManagementScope
    from app.memory import router
    now = datetime.now(timezone.utc)
    params = {'agent_id': 1, 'start': now.isoformat(), 'end': (now + timedelta(days=1)).isoformat()}
    path = '/api/memory/agenda'
    assert (await client.get(path, params=params)).status_code == 401
    credentials = {'email': 'synthetic-memory-agenda@example.com', 'password': 'Synthetic-memory-agenda-123'}
    assert (await client.post('/api/auth/register', json=credentials)).status_code == 201
    login = await client.post('/api/auth/login-json', json=credentials)
    headers = {'Authorization': 'Bearer ' + login.json()['access_token'], 'X-Editorial-Profile-Version': '1'}
    agent_id = (await client.get('/api/agents/selection', headers=headers)).json()[0]['id']
    params['agent_id'] = agent_id
    created = await client.post('/api/memory/items', headers=headers, json={
        'owner_agent_id': agent_id, 'title': 'Synthetic HTTP observation',
        'payload': {'text': '<p>Synthetic HTTP evidence.</p>'}, 'temporal': {'year': now.year}})
    assert created.status_code == 201, created.text
    async def management():
        return AgentManagementScope(user_id=1, agent_ids=frozenset({agent_id}))
    monkeypatch.setattr(router, 'current_management_scope', management)
    response = await client.get(path, params=params, headers=headers)
    assert response.status_code == 200 and len(response.json()['items']) == 1
    assert response.json()['items'][0]['excerpt']
    compact = await client.get(path, params={**params, 'include_excerpt': False}, headers=headers)
    assert compact.status_code == 200
    assert compact.json()['items'] == [{**response.json()['items'][0], 'excerpt': ''}]
    assert (await client.get(path, params={**params, 'agent_id': agent_id + 10000}, headers=headers)).status_code == 404
    assert (await client.get(path, params={**params, 'end': now.isoformat()}, headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_calendar_tools_share_informational_memory_projection(agents, memory_storage):
    from app.calendar import mcp
    from app.services import McpToolContext
    owner, _ = agents
    await sync_integrated_service_connections(owner.id)
    now = datetime.now(timezone.utc)
    item = await remember(owner, 'Synthetic tool calendar evidence', year=now.year)
    ctx = McpToolContext(agent_id=owner.id, runtime='internal')
    calendars = await mcp.calendar_list(ctx)
    assert any(row.get('source_kind') == 'memory' and not row['actions_enabled'] for row in calendars)
    page = await mcp.calendar_events(ctx, start=now.isoformat(), end=(now + timedelta(days=1)).isoformat())
    assert len(page['items']) == 1 and page['items'][0]['source_uri'] == f'memory://{item.id}'
    assert page['items'][0]['informational'] and page['items'][0]['transparent']
    assert not (await mcp.calendar_events(ctx, start=now.isoformat(), end=(now + timedelta(days=1)).isoformat(), include_memory=False))['items']
    assert (await mcp.calendar_is_available(ctx, start=now.isoformat(), end=(now + timedelta(days=1)).isoformat()))['available']
