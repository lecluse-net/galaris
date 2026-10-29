"""Conversational follow-ups keep their subject through the actual context pipeline."""

import asyncio
from dataclasses import replace
import random
import string

import pytest

from app.agent import context as agent_context
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.agent.models import Agent, Title
from app.memory import bootstrap, context, retrieval, service
from app.memory.embedding import MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryContactItem
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.database import get_db_session
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize('message', ["Elle l'a validé.", 'She approved it.',
                                   'Et la contrainte ?', 'What about the constraint?'])
async def test_follow_up_recalls_the_prior_subject_without_an_embedding_provider(agents, memory_storage, monkeypatch, message):
    owner, peer = agents
    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError('controlled lexical fallback')
    monkeypatch.setattr(retrieval, 'resolve_embedding_model', unavailable)
    monkeypatch.setattr(agent_context, '_providers', {})
    agent_context.register_context_provider('long_term_memory', bootstrap.memory_context_provider, priority=20)
    wanted, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title='Ariane Velo — projet Solstice',
        payload=MemoryPayload(text='<p>Ariane Velo dirige le projet Solstice. Son enveloppe est de 17 unités.</p>')))
    hidden, _ = await service.create_item(MemoryItemCreate(owner_agent_id=peer.id,
        title='Ariane Velo — données privées',
        payload=MemoryPayload(text='<p>Ariane Velo utilise un accès confidentiel de 83 unités.</p>')))
    request = AgentContextRequest(task_id=None,
        agent=AgentSnapshot(owner.id, owner.code, 'Synthetic', 'Agent', 'internal'),
        label='Conversation', objective=message,
        fallback_history=({'role': 'user', 'text': 'Nous parlions du projet Solstice avec Ariane Velo.'},
                          {'role': 'assistant', 'text': 'Quel point souhaitez-vous reprendre ?'}))
    prepared = await agent_context.build_agent_run_context(request)
    assert str(wanted.id) in prepared.metadata.get('memory_context_ids', [])
    assert str(hidden.id) not in prepared.metadata.get('memory_context_ids', [])
    assert '17' in prepared.memory_context


@pytest.mark.parametrize('message', [
    'Autre sujet : et sa limite ?', 'Nouveau sujet : quelle est sa limite ?',
    'On change de dossier : quelle est sa limite ?', 'Bon, changeons de sujet : et elle ?',
    'New topic: what about her limit?', 'Different topic: what about it?',
    "Now, let's change the topic: what about her?", 'Switch topic: what about it?',
])
def test_explicit_topic_reset_excludes_the_former_subject_from_both_queries(message):
    history = ({'role': 'user', 'text': 'Ancienne affaire avec CassiopeeInconnue.'},)
    for builder in (context.memory_context_query, context.memory_context_semantic_query):
        assert builder(label='Conversation', objective=message, conversation_history=history) == builder(
            label='Conversation', objective=message)


@pytest.mark.parametrize('role', ['assistant', 'system', 'tool', '', None])
def test_lexical_follow_up_does_not_promote_machine_messages_to_human_subjects(role):
    query = context.memory_context_query(label='Conversation', objective='Et sa limite ?',
        conversation_history=({'role': 'user', 'text': '[Utilisateur] Projet Solstice avec Ariane.'},
                              {'role': role, 'text': 'InventedMachineSubject'},
                              {'role': 'user', 'text': 'Et sa limite ?'}))
    assert 'Solstice' in query
    assert '[Utilisateur]' not in query
    assert 'InventedMachineSubject' not in query


def test_lexical_follow_up_prefers_the_last_human_subject_and_ignores_invalid_messages():
    query = context.memory_context_query(label='Conversation', objective='And her limit?',
        conversation_history=({'role': 'user', 'text': 'FormerObsoleteSubject'},
                              {'role': ' HUMAN ', 'text': 'CurrentSubject'},
                              {'role': 'user', 'text': 17}, {'role': 'user', 'text': '  '}))
    assert 'CurrentSubject' in query
    assert 'FormerObsoleteSubject' not in query


def test_history_outside_the_recent_window_cannot_resurrect_an_old_subject():
    recent = tuple({'role': 'assistant', 'text': f'Explanation {i}'} for i in range(6))
    query = context.memory_context_query(label='Conversation', objective='Et elle ?',
        conversation_history=({'role': 'user', 'text': 'ExpiredSubject'}, *recent))
    assert 'ExpiredSubject' not in query


@pytest.mark.parametrize('seed', [19, 139, 1877])
def test_query_bounds_and_explicit_task_independence_for_generated_histories(seed):
    """Deterministic metamorphic checks: history must not redefine an explicit task.

    Generate 120 histories per seed, including empty values, unicode, long messages,
    speaker markup and instruction-shaped data. No provider or test dependency needed.
    """
    rng = random.Random(seed)
    alphabet = string.ascii_letters + ' éàñΩ中🙂\n\t[]:?!'
    objectives = ('Et sa limite ?', 'What about it?', 'Autre sujet : et elle ?')
    for _ in range(120):
        history = tuple({'role': rng.choice(('user', 'human', 'assistant', 'tool', 'system')),
                         'text': ''.join(rng.choices(alphabet, k=rng.randrange(0, 1800)))}
                        for _ in range(rng.randrange(0, 18)))
        objective = rng.choice(objectives)
        for builder in (context.memory_context_query, context.memory_context_semantic_query):
            assert builder(label='Audit Solstice', objective=objective, conversation_history=history) == builder(
                label='Audit Solstice', objective=objective)
            goal = 'GOAL TITLE:\nAudit Solstice\n\nGOAL INSTRUCTIONS:\nEt sa limite ?'
            if builder is context.memory_context_query:
                assert builder(label='Conversation', objective=goal, conversation_history=history) == 'Audit Solstice'
        query = context.memory_context_query(label='Conversation', objective=objective,
            contact_terms=('CurrentContact',), conversation_history=history)
        assert len(query) <= 240
        assert len(query.split()) <= 18
        assert query.startswith('CurrentContact ')
        assert len(context.memory_context_semantic_query(label='Conversation', objective=objective,
                   conversation_history=history)) <= 4000


@pytest.mark.asyncio
async def test_overlapping_follow_ups_and_reopened_capsules_keep_agent_and_contact_isolation(
    committed_database, memory_storage, monkeypatch,
):
    """Independent committed sessions overlap; neither identity nor history is global."""
    monkeypatch.setattr(agent_context, '_providers', {})
    agent_context.register_context_provider('long_term_memory', bootstrap.memory_context_provider,
        priority=20, refreshes_frozen_kinds=frozenset({'memory'}))
    fixtures = []
    async with get_db_session() as db:
        user = UserModel(email='continuity@example.invalid', hashed_password='unused', language='fr')
        title = Title(label='Synthetic continuity', gender='X')
        db.add_all([user, title])
        await db.flush()
        for actor in range(2):
            agent = Agent(title_id=title.id, user_id=user.id, first_name='Synthetic',
                          last_name='Continuity', code=f'continuity-{actor}', agent_driver='internal')
            db.add(agent)
            await db.flush()
            for contact_number in range(2):
                contact, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id,
                    title=f'Contact synthétique {contact_number}',
                    payload=MemoryPayload(text=f'<p>Contact distinct {contact_number}.</p>')),
                    deduplicate=False)
                marker = f'CONFIDENTIAL_{actor}_{contact_number}'
                fact, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id,
                    title='Solstice avec Ariane Velo',
                    payload=MemoryPayload(text=f'<p>Ariane Velo a choisi {marker} pour Solstice.</p>')))
                db.add(MemoryContactItem(owner_agent_id=agent.id, contact_item_id=contact.id,
                    item_id=fact.id, source_kind='synthetic', source_ref=marker))
                await db.flush()
                fixtures.append((AgentSnapshot(agent.id, agent.code, 'Synthetic', 'Continuity', 'internal'),
                                 contact.id, fact.id, marker))
    arrived = set()
    gate = asyncio.Event()

    async def delayed_unavailable():
        arrived.add(asyncio.current_task())
        if len(arrived) >= 4:
            gate.set()
        await asyncio.wait_for(gate.wait(), timeout=10)
        raise MemoryEmbeddingNotConfiguredError('controlled overlapping lexical fallback')

    monkeypatch.setattr(retrieval, 'resolve_embedding_model', delayed_unavailable)

    async def recall(fixture):
        agent, contact, fact, marker = fixture
        request = AgentContextRequest(task_id=None, agent=agent, label='Conversation',
            objective='Et son choix ?', contact_memory_item_id=contact,
            messenger_connection_id=1, task_data={'sender_is_ai': False},
            fallback_history=({'role': 'user', 'text': 'Ariane Velo pour Solstice.'},))
        async with get_db_session():
            first = await agent_context.build_agent_run_context(request)
        async with get_db_session():
            reopened = await agent_context.build_agent_run_context(replace(request,
                frozen_capsule=first.context_capsule.model_dump(mode='json')))
        for prepared in (first, reopened):
            ids = {entry.reference for entry in prepared.context_capsule.entries if entry.kind == 'memory'}
            assert str(fact) in ids
            assert marker in prepared.context_capsule.rendered
            for _, _, other_fact, other_marker in fixtures:
                if other_fact != fact:
                    assert str(other_fact) not in ids
                    assert other_marker not in prepared.context_capsule.rendered

    results = await asyncio.wait_for(asyncio.gather(*(recall(fixture) for fixture in reversed(fixtures)),
        return_exceptions=True), timeout=30)
    assert not [result for result in results if isinstance(result, BaseException)], results
