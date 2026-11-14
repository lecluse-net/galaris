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
from app.tools import sync_integrated_tool_connections


async def remember(agent, title, **parts):
    return (await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, title=title, media_type='text/html',
        payload=MemoryPayload(text=f'<p>{title}</p>'), temporal=MemoryTemporalAnchor(**parts))))[0]


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
    await sync_integrated_tool_connections(owner.id)
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
    from app.connection.facade import set_tool_function_state
    from app.tools import tool_service
    tool = await tool_service.get_tool_record('memory')
    await set_tool_function_state(tool.id, 'memory_upcoming', 'disabled')
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
    from app.tools import McpToolContext
    owner, _ = agents
    await sync_integrated_tool_connections(owner.id)
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
