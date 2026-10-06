"""Calendar facts survive acquisition and reach context independently of the query."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.memory import acquisition_service, context, service
from app.memory.schemas import MemoryAcquisitionCreate, MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemoryRecallRequest
from app.memory.retrieval import temporal_hits
from app.memory.temporal import MemoryTemporalAnchor, MemoryTemporalFilter, next_match
from app.memory.schemas import MemorySearchRequest
from app.memory import bootstrap, observe_messenger_contact, MessengerContactObservation, ensure_contact_memory_scope
from app.agent import AgentContextRequest, AgentSnapshot


@pytest.fixture(autouse=True)
def global_timezone(monkeypatch):
    monkeypatch.setenv('TZ', 'UTC')


@pytest.mark.parametrize(('parts', 'start', 'end', 'expected'), [
    ({'month': 9, 'day': 27}, '2026-09-26T23:00:00+00:00', '2026-09-27T01:00:00+00:00', '2026-09-27T00:00:00+00:00'),
    ({'year': 2027, 'month': 9, 'day': 27}, '2026-09-27T00:00:00+00:00', '2026-09-28T00:00:00+00:00', None),
    ({'hour': 9}, '2026-09-27T09:42:53+00:00', '2026-09-27T09:42:53+00:00', '2026-09-27T09:42:53+00:00'),
    ({'minute': 30}, '2026-09-27T09:31:00+00:00', '2026-09-27T10:30:00+00:00', '2026-09-27T10:30:00+00:00'),
    ({'hour': 0, 'minute': 0}, '2026-12-31T23:59:00+00:00', '2027-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00'),
    ({'month': 2, 'day': 29}, '2027-02-28T00:00:00+00:00', '2027-03-01T00:00:00+00:00', None),
    ({'month': 2, 'day': 29}, '2028-02-28T23:00:00+00:00', '2028-03-01T00:00:00+00:00', '2028-02-29T00:00:00+00:00'),
    ({'weekday': 1, 'hour': 9, 'minute': 30}, '2026-09-27T10:00:00+00:00', '2026-09-28T10:00:00+00:00', '2026-09-28T09:30:00+00:00'),
    ({'hour': 9, 'minute': 30, 'timezone': 'Europe/Paris'}, '2026-03-29T00:00:00+00:00', '2026-03-29T10:00:00+00:00', '2026-03-29T07:30:00+00:00'),
    ({'hour': 2, 'minute': 30, 'timezone': 'Europe/Paris'}, '2026-03-29T00:00:00+00:00', '2026-03-29T22:00:00+00:00', None),
    ({'hour': 2, 'minute': 30, 'timezone': 'Europe/Paris'}, '2026-10-25T00:45:00+00:00', '2026-10-25T02:00:00+00:00', '2026-10-25T01:30:00+00:00'),
])
def test_partial_calendar_matches(parts, start, end, expected, monkeypatch):
    parts = dict(parts)
    monkeypatch.setenv('TZ', parts.pop('timezone', 'UTC'))
    anchor = MemoryTemporalAnchor.model_validate(parts)
    assert 'timezone' not in anchor.model_dump()
    result = next_match(anchor, datetime.fromisoformat(start), datetime.fromisoformat(end))
    assert result == (datetime.fromisoformat(expected) if expected else None)


@pytest.mark.parametrize('parts', [
    {}, {'day': 31, 'month': 2}, {'year': 2027, 'month': 2, 'day': 29},
    {'year': 2026, 'month': 9, 'day': 27, 'weekday': 1},
    {'hour': 24}, {'minute': 60}, {'second': 0}, {'day': True}, {'hour': 9.5},
    {'day': 1, 'timezone': 'Invalid/Zone'}, {'day': 1, 'timezone': 'UTC'},
])
def test_impossible_or_empty_constraints_are_rejected(parts):
    with pytest.raises(ValidationError):
        MemoryTemporalAnchor.model_validate(parts)


@pytest.mark.asyncio
async def test_global_timezone_upgrade_preserves_dates_history_and_acquisitions(agents, memory_storage, db):
    from sqlalchemy import select, text

    from app.memory.dbadmin import _reconcile_temporal_timezone
    from app.memory.models import MemoryAcquisition, MemoryItem, MemoryRevision, MemorySource

    owner, _ = agents
    acquired = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
        agent_id=owner.id, title='Synthetic calendar migration', content='<p>Preserved evidence.</p>',
        source_ref='manual:timezone-upgrade', temporal=MemoryTemporalAnchor(month=9, day=27, hour=9),
    ))
    item = await db.get(MemoryItem, acquired.memory_id)
    original_revision = item.revision
    await service.update_item(item.id, MemoryItemUpdate(
        expected_revision=original_revision, temporal=MemoryTemporalAnchor(month=9, day=28, hour=9),
    ), actor_agent_id=owner.id)
    for table in ('memory_items', 'memory_revisions'):
        await db.execute(text(
            f"UPDATE {table} SET temporal = temporal || '{{\"timezone\":\"America/Toronto\"}}'::jsonb "
            "WHERE temporal IS NOT NULL"
        ))
    for table in ('memory_candidates', 'memory_sources'):
        await db.execute(text(
            f"UPDATE {table} SET metadata = jsonb_set(metadata, '{{temporal}}', "
            "(metadata -> 'temporal') || '{\"timezone\":\"America/Toronto\"}'::jsonb) "
            "WHERE jsonb_typeof(metadata -> 'temporal') = 'object'"
        ))
    async with db.begin_nested() as savepoint:
        await _reconcile_temporal_timezone(db)
        await savepoint.rollback()
    assert await db.scalar(select(MemoryItem.temporal['timezone'].as_string()).where(MemoryItem.id == item.id)) == 'America/Toronto'
    for _ in range(2):
        await _reconcile_temporal_timezone(db)
    await db.refresh(item)
    assert item.temporal == MemoryTemporalAnchor(month=9, day=28, hour=9).model_dump(mode='json')
    assert item.revision == original_revision + 1
    revisions = list(await db.scalars(select(MemoryRevision.temporal).where(
        MemoryRevision.item_id == item.id,
    ).order_by(MemoryRevision.revision)))
    assert [value['day'] for value in revisions] == [27, 28]
    assert all('timezone' not in value for value in revisions)
    record = await db.get(MemoryAcquisition, acquired.acquisition_id)
    await db.refresh(record)
    assert record.metadata_['temporal'] == MemoryTemporalAnchor(month=9, day=27, hour=9).model_dump(mode='json')
    source_metadata = await db.scalar(select(MemorySource.metadata_).where(MemorySource.item_id == item.id))
    assert source_metadata['temporal'] == record.metadata_['temporal']
    assert 'Preserved evidence.' in (await service.get_item(item.id, agent_id=owner.id))[1].decode()


@pytest.mark.asyncio
async def test_calendar_memory_round_trip_context_acl_revision_and_removal(agents, memory_storage, monkeypatch):
    owner, peer = agents
    now = datetime.now(timezone.utc)
    anchor = MemoryTemporalAnchor(month=now.month, day=now.day)
    data = MemoryAcquisitionCreate(agent_id=owner.id, title='Annual observation',
        content='<p>A synthetic anniversary.</p>', source_ref='manual:calendar',
        temporal=anchor, metadata={'media_type': 'text/html'})
    first = await acquisition_service.acquire_memory(data)
    repeated = await acquisition_service.acquire_memory(data)
    assert first.memory_id == repeated.memory_id
    item_id = first.memory_id
    assert item_id is not None
    item, content, access, content_type, media_type = await service.get_item(item_id, agent_id=owner.id)
    original_revision = item.revision
    assert item.temporal == anchor.model_dump(mode='json')
    assert item.valid_from is None and item.valid_until is None
    # No search query and no embedding provider are needed for temporal context.
    brief = await context.build_memory_brief(agent_id=owner.id, query='')
    assert [entry.memory_id for entry in brief.items] == [str(item_id)]
    assert 'temporal_match=' in brief.rendered
    assert not (await context.build_memory_brief(agent_id=peer.id, query='')).items
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(item_id, MemoryItemUpdate(temporal=None), actor_agent_id=peer.id)
    changed = await service.update_item(item_id, MemoryItemUpdate(expected_revision=original_revision,
        temporal=MemoryTemporalAnchor(year=now.year + 1, month=now.month, day=now.day)),
        actor_agent_id=owner.id)
    assert changed.revision == original_revision + 1
    old = await service.item_to_detail(changed, content, access, content_type=content_type,
        media_type=media_type, revision=original_revision)
    assert old.temporal == anchor
    assert not (await context.build_memory_brief(agent_id=owner.id, query='')).items
    update = MemoryAcquisitionCreate(agent_id=owner.id, action='update', target_item_id=item_id,
        title=data.title, content=data.content, source_ref='manual:calendar-update')
    await acquisition_service.acquire_memory(update)
    assert (await service.get_item(item_id, agent_id=owner.id))[0].temporal is not None
    clear = update.model_copy(update={'temporal': None})
    cleared = await acquisition_service.acquire_memory(clear)
    replay = await acquisition_service.acquire_memory(clear)
    assert cleared.acquisition_id == replay.acquisition_id and not replay.applied
    assert (await service.get_item(item_id, agent_id=owner.id))[0].temporal is None


@pytest.mark.asyncio
async def test_same_content_different_dates_remains_distinct_and_upcoming_is_paginated(agents, memory_storage, monkeypatch):
    owner, _ = agents
    now = datetime(2026, 9, 27, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_TEMPORAL_LOOKAHEAD_HOURS', 24)
    ids: list[UUID] = []
    for hour in (9, 10, 11):
        data = MemoryItemCreate(owner_agent_id=owner.id,
            title='Appointment', payload=MemoryPayload(text='Synthetic appointment'),
            temporal=MemoryTemporalAnchor(hour=hour))
        item = await acquisition_service.create_manual_item(data)
        assert item.temporal == data.temporal.model_dump(mode='json')
        repeated, created = await service.create_item(data)
        assert repeated.id == item.id and not created
        ids.append(item.id)
    plain, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title='Ordinary fact', payload=MemoryPayload(text='Synthetic appointment')))
    assert plain.temporal is None and plain.id not in ids
    request = MemoryRecallRequest(agent_id=owner.id)
    first, has_more = await temporal_hits(request, limit=2, now=now)
    second, more = await temporal_hits(request, limit=2, offset=2, now=now)
    assert [hit.item.id for hit in first + second] == ids
    assert has_more and not more
    assert first[0].temporal_match_at == now + timedelta(hours=1)
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_TEMPORAL_LOOKAHEAD_HOURS', 0)
    assert await temporal_hits(request, limit=50, now=now) == ([], False)


@pytest.mark.asyncio
async def test_temporal_contact_context_preserves_attribution_and_budget(agents, memory_storage, monkeypatch):
    owner, _ = agents
    alice = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id='synthetic', user_id='alice', display_name='Alice'))
    bob = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id='synthetic', user_id='bob', display_name='Bob'))
    now = datetime.now(timezone.utc)
    ids = []
    for contact_id, title in ((alice, 'Alice birthday'), (bob, 'Bob private anniversary'), (None, 'Public observation')):
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title=title,
            payload=MemoryPayload(text=title), temporal=MemoryTemporalAnchor(year=now.year)))
        ids.append(item.id)
        if contact_id:
            await ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=contact_id,
                memory_item_id=item.id, source_kind='manual', source_ref='manual:temporal-scope')
    contribution = await bootstrap.memory_context_provider(AgentContextRequest(
        task_id=None,
        agent=AgentSnapshot(id=owner.id, code='synthetic', first_name='Test', last_name='Agent', driver_code='internal'),
        objective='', label='', contact_memory_item_id=alice))
    assert {candidate.reference for candidate in contribution.candidates} == {str(ids[0]), str(ids[2])}
    assert all('temporal_match=' in candidate.excerpt for candidate in contribution.candidates)
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_CONTEXT_MAX_ITEMS', 1)
    brief = await context.build_memory_brief(agent_id=owner.id, query='', contact_item_id=alice)
    assert len(brief.items) == 1 and brief.truncated
    assert 'memory_upcoming' in brief.rendered


@pytest.mark.asyncio
async def test_dream_create_persists_optional_calendar(agents, memory_storage):
    from app.dream.contracts import MemoryCreateOperation, MemoryExtractionDecision, MemoryExtractionPrepared
    from app.dream.mechanisms.memory_extraction import apply_memory_extraction

    owner, _ = agents
    anchor = MemoryTemporalAnchor(month=9, day=27)
    prepared = MemoryExtractionPrepared(decision=MemoryExtractionDecision(operations=[MemoryCreateOperation(
        title='Birthday', content='<p>The synthetic contact celebrates on September 27.</p>',
        temporal=anchor, retention_reason='stable_personal_fact', future_utility='high',
    )]), candidate_memory_ids=[])
    await apply_memory_extraction(prepared, agent_id=owner.id, source_kind='task',
        source_ref='task:synthetic-birthday', source_excerpt='September 27',
        memory_created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), metadata={},
        contact_item_id=None, topic_item_id=None, idempotency_prefix='test-calendar-extraction')
    from sqlalchemy import select
    from core.database import get_db
    from app.memory.models import MemoryItem
    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.owner_agent_id == owner.id,
        MemoryItem.title == 'Birthday'))
    assert item is not None and item.temporal == anchor.model_dump(mode='json')


@pytest.mark.parametrize('target,expected', [
    ('2026-09-27T09:30', '2026-09-27T07:30:00+00:00'),
    ('2026-10-25T02:30:00+01:00', '2026-10-25T01:30:00+00:00'),
    ('2026-10-25T02:30:00+02:00', '2026-10-25T00:30:00+00:00'),
])
def test_target_date_resolves_in_global_timezone(target, expected, monkeypatch):
    monkeypatch.setenv('TZ', 'Europe/Paris')
    assert MemoryTemporalFilter(target_at=target).target_at == datetime.fromisoformat(expected)


@pytest.mark.parametrize('data', [
    {'target_at': '2026-03-29T02:30'}, {'target_at': '2026-10-25T02:30'},
    {'target_at': '2026-02-30T09:30'}, {'timezone': 'Invalid/Zone'}, {'timezone': 'UTC'},
    {'lookahead_hours': -1}, {'lookahead_hours': 745}, {'lookahead_hours': True},
])
def test_target_date_rejects_invalid_or_ambiguous_inputs(data, monkeypatch):
    monkeypatch.setenv('TZ', 'Europe/Paris')
    with pytest.raises(ValidationError):
        MemoryTemporalFilter.model_validate(data)


@pytest.mark.asyncio
async def test_browse_combines_target_date_filters_acl_and_pagination(agents, memory_storage, monkeypatch):
    monkeypatch.setenv('TZ', 'Europe/Paris')
    owner, peer = agents
    contact = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=owner.id,
        messaging_id='synthetic-calendar', user_id='calendar-contact', display_name='Calendar contact'))
    definitions = [
        ('A annual', owner.id, 'semantic', {'month': 9, 'day': 27}),
        ('B appointment', owner.id, 'semantic', {'year': 2026, 'month': 9, 'day': 27, 'hour': 10}),
        ('C next year', owner.id, 'semantic', {'year': 2027, 'month': 9, 'day': 27}),
        ('D other type', owner.id, 'working', {'month': 9, 'day': 27}),
        ('E private', peer.id, 'semantic', {'month': 9, 'day': 27}),
        ('F untimed', owner.id, 'semantic', None),
        ('G other contact', owner.id, 'semantic', {'month': 9, 'day': 27}),
        ('H expired', owner.id, 'semantic', {'month': 9, 'day': 27}),
    ]
    for title, agent_id, memory_type, parts in definitions:
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent_id, title=title,
            memory_type=memory_type, payload=MemoryPayload(text=f'Synthetic calendar evidence for {title}'),
            valid_until=datetime.now(timezone.utc) - timedelta(days=1) if title.startswith('H') else None,
            temporal=MemoryTemporalAnchor(**parts) if parts else None))
        if title[0] in 'ABCD':
            await ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=contact,
                memory_item_id=item.id, source_kind='manual', source_ref='manual:calendar-search')
    request = MemorySearchRequest(agent_id=owner.id, query='calendar', memory_types=['semantic'],
        filter_contact_item_id=contact, sort_by='title', sort_desc=False, limit=1,
        temporal=MemoryTemporalFilter(target_at='2026-09-27T09:00', lookahead_hours=1))
    first = await service.search_items(request)
    second = await service.search_items(request.model_copy(update={'offset': 1}))
    assert first.total == second.total == 2 and first.has_more and not second.has_more
    assert [hit.item.title for hit in first.hits + second.hits] == ['A annual', 'B appointment']
    assert first.hits[0].temporal_match_at == datetime(2026, 9, 27, 7, tzinfo=timezone.utc)
    assert second.hits[0].temporal_match_at == datetime(2026, 9, 27, 8, tzinfo=timezone.utc)
    assert first.temporal_window.start == request.temporal.target_at
    visible = await service.search_items(request.model_copy(update={'filter_contact_item_id': None, 'limit': 50}))
    assert [hit.item.title for hit in visible.hits] == ['A annual', 'B appointment', 'G other contact']
    for target, titles in [('2027-09-27T09:00', ['A annual', 'C next year']), ('2026-09-28T09:00', [])]:
        page = await service.search_items(request.model_copy(update={'limit': 50,
            'temporal': MemoryTemporalFilter(target_at=target, lookahead_hours=0)}))
        assert [hit.item.title for hit in page.hits] == titles
    assert not (await service.search_items(request.model_copy(update={'query': 'absentword'}))).hits
    # Removing the calendar filter restores ordinary memories and all dated years.
    unfiltered = await service.search_items(request.model_copy(update={'temporal': None, 'limit': 50}))
    assert [hit.item.title for hit in unfiltered.hits] == ['A annual', 'B appointment', 'C next year']
    assert unfiltered.temporal_window is None


@pytest.mark.asyncio
async def test_empty_target_uses_current_server_time_and_configured_window(agents, memory_storage, monkeypatch):
    owner, _ = agents
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_TEMPORAL_LOOKAHEAD_HOURS', 3)
    before = datetime.now(timezone.utc)
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title='Current annual date',
        payload=MemoryPayload(text='Synthetic real time memory'),
        temporal=MemoryTemporalAnchor(year=before.year)))
    result = await service.search_items(MemorySearchRequest(agent_id=owner.id,
        temporal=MemoryTemporalFilter()))
    assert [hit.item.id for hit in result.hits] == [item.id]
    assert before <= result.temporal_window.start <= datetime.now(timezone.utc)
    assert result.temporal_window.end - result.temporal_window.start == timedelta(hours=3)
    assert result.hits[0].temporal_match_at == result.temporal_window.start


@pytest.mark.asyncio
async def test_calendar_browse_http_round_trip_and_authorization(client, memory_storage, monkeypatch):
    monkeypatch.setenv('TZ', 'Europe/Paris')
    from core.database import get_db_session
    from core.authorize import Assignment, Privilege, Role
    from sqlalchemy import select

    path = '/api/memory/browse'
    payload = {'agent_id': 1, 'temporal': {'target_at': '2027-09-27T09:30', 'lookahead_hours': 0}}
    assert (await client.post(path, json=payload)).status_code == 401
    credentials = {'email': 'calendar-admin@example.com', 'password': 'Calendar-test-password-123'}
    assert (await client.post('/api/auth/register', json=credentials)).status_code == 201
    login = await client.post('/api/auth/login-json', json=credentials)
    admin = {'Authorization': 'Bearer ' + login.json()['access_token'], 'X-Editorial-Profile-Version': '1'}
    agents = (await client.get('/api/agents/selection', headers=admin)).json()
    agent_id = agents[0]['id']
    payload['agent_id'] = agent_id
    created = await client.post('/api/memory/items', headers=admin, json={
        'owner_agent_id': agent_id, 'title': 'Synthetic anniversary', 'payload': {'text': '<p>Annual calendar fact.</p>'},
        'temporal': {'month': 9, 'day': 27},
    })
    assert created.status_code == 201, created.text
    assert 'timezone' not in created.json()['temporal']
    ordinary = await client.post('/api/memory/items', headers=admin, json={
        'owner_agent_id': agent_id, 'title': 'Synthetic ordinary preference',
        'payload': {'text': '<p>Prefer concise replies.</p>'},
    })
    assert ordinary.status_code == 201, ordinary.text
    response = await client.post(path, headers=admin, json=payload)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page['temporal_window']['timezone'] == 'Europe/Paris'
    by_id = {hit['item']['id']: hit for hit in page['hits']}
    assert ordinary.json()['id'] in by_id
    assert by_id[ordinary.json()['id']]['temporal_match_at'] is None
    assert datetime.fromisoformat(by_id[created.json()['id']]['temporal_match_at']) == datetime(2027, 9, 27, 7, 30, tzinfo=timezone.utc)
    invalid = {**payload, 'temporal': {**payload['temporal'], 'target_at': '2026-03-29T02:30'}}
    assert (await client.post(path, headers=admin, json=invalid)).status_code == 422
    credentials = {'email': 'calendar-reader@example.com', 'password': 'Calendar-test-password-123'}
    user = (await client.post('/api/auth/users', headers=admin, json=credentials)).json()
    client.cookies.clear()
    login = await client.post('/api/auth/login-json', json=credentials)
    reader = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert (await client.post(path, headers=reader, json=payload)).status_code == 403
    async with get_db_session() as db:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == 'MEMORY_ACCESS'))
        role = Role(code='calendar-reader', display_name='Calendar reader', privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user['id'], role_id=role.id, is_default=True))
    # A memory privilege does not grant management of another user's agent.
    assert (await client.post(path, headers=reader, json=payload)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('include_experience', [False, True])
async def test_context_separates_dated_recall_from_ordinary_relevance(agents, memory_storage, monkeypatch, include_experience):
    from app.memory import retrieval
    from app.memory.embedding import MemoryEmbeddingNotConfiguredError

    owner, peer = agents
    now = datetime.now(timezone.utc)
    async def missing_model():
        raise MemoryEmbeddingNotConfiguredError('not configured')
    monkeypatch.setattr(retrieval, 'resolve_embedding_model', missing_model)
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_CONTEXT_MAX_ITEMS', 5)
    ids = []
    for title, words, anchor, agent_id, memory_type in [
        ('Ordinary preference', 'needle', None, owner.id, 'semantic'),
        ('Unrelated appointment', 'birthday gathering', MemoryTemporalAnchor(year=now.year), owner.id, 'working'),
        ('Out of period', 'needle', MemoryTemporalAnchor(year=now.year+2), owner.id, 'semantic'),
        ('Private appointment', 'birthday gathering', MemoryTemporalAnchor(year=now.year), peer.id, 'working'),
    ]:
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent_id, title=title,
            memory_type=memory_type, payload=MemoryPayload(text=words), temporal=anchor))
        ids.append(str(item.id))
    experience, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title='Prior lesson', memory_type='procedural', payload=MemoryPayload(text='needle ' * 300),
        metadata={'memory_role': 'experience'}))
    brief = await context.build_memory_brief(agent_id=owner.id, query='needle', include_experience=include_experience)
    assert [item.memory_id for item in brief.items] == [ids[1], ids[0], *([str(experience.id)] if include_experience else [])]
    monkeypatch.setattr(context.runtime_settings, 'MEMORY_CONTEXT_MAX_ITEMS', 1)
    brief = await context.build_memory_brief(agent_id=owner.id, query='needle', include_experience=include_experience)
    assert [item.memory_id for item in brief.items] == [ids[1]]
    assert brief.truncated
