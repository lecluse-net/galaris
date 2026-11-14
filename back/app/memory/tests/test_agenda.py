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
