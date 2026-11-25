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


@pytest.mark.parametrize("question", [
    "Quel est le mail de Nina Fiction ?", "Ouvre mon carnet d'adresses.",
    "What is my invoice number?", "What is my number of invoices?", "Open my address book.",
    "Quel est mon numéro de facture ?",
])
def test_other_people_and_business_identifiers_do_not_select_the_sender_contact(question):
    from app.memory.passages import query_is_contact_self_reference
    assert not query_is_contact_self_reference(question)


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["Tu connais mon email ?", "What is my email address?", "Tu as mon mail ?", "Mon téléphone ?"])
@pytest.mark.parametrize("strict", [False, True])
async def test_current_contact_is_retrieved_without_its_name_among_other_contact_cards(
    db, agents, memory_storage, monkeypatch, question, strict,
):
    from app.memory import create_address_book_contact
    owner, peer = agents
    wanted = await create_address_book_contact(owner_agent_id=owner.id,
        display_name="Éloi Fiction", email="eloi-current@example.org")
    foreign = await create_address_book_contact(owner_agent_id=peer.id,
        display_name="Éloi Fiction", email="eloi-private@example.org")
    for index in range(16):
        await create_address_book_contact(owner_agent_id=owner.id,
            display_name="Éloi Fiction" if index % 2 else f"Synthetic Correspondent {index}",
            email=f"noise-{index}@example.org")
    resolutions = []
    async def unavailable():
        resolutions.append(True)
        raise MemoryEmbeddingNotConfiguredError("Synthetic provider outage")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    result = await retrieval.recall_items(retrieval.MemoryRecallRequest(
        agent_id=owner.id, contact_item_id=wanted.memory_item_id, query=question, limit=3,
        strict_contact_scope=strict))
    assert result.hits[0].item.id == wanted.memory_item_id
    assert foreign.memory_item_id not in {hit.item.id for hit in result.hits}
    assert "eloi-current@example.org" in result.hits[0].excerpt
    assert resolutions == []


@pytest.mark.parametrize("question", ["Est-ce que Nina connaît mon email ?", "My email and the QUARTZ procedure?",
    "Quel est mon numéro de facture ?", "Open my address book."])
def test_a_contact_shortcut_cannot_hide_another_subject_or_a_business_question(question):
    from app.memory.passages import query_is_direct_contact_lookup
    assert not query_is_direct_contact_lookup(question)


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", ["Oui.", "Merci !", "Yes.", "Thanks!"])
async def test_contact_follow_up_keeps_the_named_person_across_short_acknowledgements(
    db, agents, memory_storage, monkeypatch, ack,
):
    from app.memory import create_address_book_contact
    owner, _ = agents
    wanted = await create_address_book_contact(owner_agent_id=owner.id,
        display_name="Éloi Fiction", email="eloi-followup@example.org")
    await create_address_book_contact(owner_agent_id=owner.id,
        display_name="Nina Fiction", email="nina-distractor@example.org")
    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Synthetic provider outage")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    monkeypatch.setattr(agent_context, "_providers", {})
    agent_context.register_context_provider("long_term_memory", bootstrap.memory_context_provider, priority=20)
    prepared = await agent_context.build_agent_run_context(AgentContextRequest(
        task_id=None, agent=AgentSnapshot(owner.id, owner.code, "Synthetic", "Agent", "internal"),
        label="Conversation", objective="Et son email ?",
        fallback_history=({"role": "user", "text": "Retrouvons la fiche de Éloi Fiction."},
            {"role": "assistant", "text": "Je vérifie. Nina Fiction est une autre personne."},
            {"role": "user", "text": ack})))
    assert str(wanted.memory_item_id) in prepared.metadata.get("memory_context_ids", [])
    assert "eloi-followup@example.org" in prepared.memory_context


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


def test_spoken_preamble_and_previous_turn_do_not_displace_the_final_question():
    history = ({"role": "assistant", "text": "Les navettes maritimes sont suspendues."},)
    objective = ("Je vais commencer par te raconter en quelques mots où nous en sommes "
                 "avant de passer à ma question de ce matin. Quel tamis pour les pigments ?")
    query = context.memory_context_query(label="Conversation", objective=objective, conversation_history=history)
    assert "tamis" in query and "pigments" in query
    assert context.memory_context_semantic_query(label="Conversation", objective=objective,
        conversation_history=history) == objective


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


@pytest.mark.asyncio
async def test_conversation_requires_evidence_for_the_requested_detail(agents, memory_storage, monkeypatch):
    owner, _ = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical retrieval")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    ids = {}
    for title, body in (
        ("Maison Luciole — accueil", "Les visiteurs de Maison Luciole apportent leur invitation."),
        ("Maison Luciole — rendez-vous", "The meeting point for Maison Luciole is the east pavilion."),
        ("Villa Sureau — accueil", "Le code d’entrée de Villa Sureau est indiqué au guichet."),
        ("Maison Muguet — gardien", "Le code d’entrée est disponible à la loge de Maison Muguet."),
        ("Villa Sureau — rendez-vous", "Le lieu de rencontre de Villa Sureau est le port."),
        ("Carnet du groupe", "Les membres du groupe préparent une exposition."),
        ("Portrait", "Inès Castor anime le groupe de dessin."),
    ):
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title=title,
            payload=MemoryPayload(text=f"<p>{body}</p>")))
        ids[title] = str(item.id)

    for question, expected in (
        ("Quel est le code d’entrée de Maison Luciole ?", set()),
        ("quel est le code d’entrée de maison luciole ?", set()),
        ("Quel est le lieu de rencontre de Maison Luciole ?", {ids["Maison Luciole — rendez-vous"]}),
        ("What is the entry code for Villa Sureau?", {ids["Villa Sureau — accueil"]}),
        ("Qui est Basile Sauge dans le groupe ?", set()),
        ("Who is Inès Castor in our group?", {ids["Portrait"]}),
    ):
        brief = await context.build_memory_brief(agent_id=owner.id, query=question, conversational=True)
        assert {row.memory_id for row in brief.items} == expected, question

    for question in ("Quel est le code d’entrée et le lieu de rencontre de Maison Luciole ?",
                     "Je ne demande pas le code d’entrée. Où est le rendez-vous de Maison Luciole ?"):
        brief = await context.build_memory_brief(agent_id=owner.id, query=question, conversational=True)
        assert ids["Maison Luciole — rendez-vous"] in {row.memory_id for row in brief.items}


@pytest.mark.asyncio
async def test_procedural_recall_combines_steps_and_prerequisites(agents, memory_storage, monkeypatch):
    owner, _ = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Synthetic lexical run")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    wanted = set()
    for title, body, relevant in (
        ("Montage", "Pour Velin Boréal, poser les deux supports puis régler la lentille.", True),
        ("Assembly", "Velin Boréal requires a calibrated gauge before assembly.", True),
        ("Fête", "La fête de clôture de Velin Boréal a rassemblé vingt personnes.", False),
        ("Pliage", "Pour Velin Corail, ranger le châssis puis fermer la housse.", False),
    ):
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title=title, media_type="text/html",
            payload=MemoryPayload(text=f"<p>{body}</p>")))
        if relevant:
            wanted.add(str(item.id))
    for question in ("Quelles étapes pour Velin Boréal ?", "How do we resume Velin Boréal?"):
        result = await context.search_memory_detailed(question, agent_id=owner.id)
        assert wanted <= {str(hit.item.id) for hit in result.hits}, (result.relevance_status, result.evidence_status,
            [(hit.item.title, hit.excerpt) for hit in result.hits])
        brief = await context.build_memory_brief(agent_id=owner.id, query=question, conversational=True)
        assert {item.memory_id for item in brief.items} == wanted, question


@pytest.mark.parametrize(("query", "supports", "distractors"), [
    ("Quelle quantité pour le vernis nacré ?", (
        "Pour le vernis nacré, le lot comporte 18 flacons.",
        "Vernis nacré — 2,5 litres par couche.",
    ), (
        "Pour le vernis mat, le lot comporte 18 flacons.",
        "Vernis nacré : contrôle du 2027-08-24 à 14:30.",
        "Quantité de vernis nacré à déterminer.",
        "Vernis nacré en attente. Le vernis mat utilise 30 flacons.",
    )),
    ("What did we include or rule out for the frosted lens?", (
        "Frosted lens: brass is included but zinc is excluded.",
        "Frosted lens — use brass, not zinc.",
        "Frosted lens: the drawings stay internal; only the signed plans are circulated.",
    ), (
        "Frosted lens: the prototype was delivered yesterday.",
        "Clear lens: brass is included but zinc is excluded.",
        "The frosted lens is not ready today.",
    )),
    ("Combien de temps pour le tissage satiné ?", (
        "Le tissage satiné prend trente minutes.",
        "Tissage satiné — 45 min par pièce.",
    ), (
        "Le tissage satiné utilise 45 bobines.",
        "Tissage satiné : rendez-vous à 15:45.",
    )),
    ("How many crates for the cobalt samples?", (
        "The cobalt samples need five crates.",
    ), (
        "Cobalt samples: reserve 15 labels for the crates.",
        "Crates for the amber samples: reserve 15 crates.",
    )),
])
def test_factual_passages_bind_the_requested_detail_to_its_subject(query, supports, distractors):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence(query)
    assert evidence is not None
    assert all(evidence.supports("", passage) for passage in supports)
    assert not any(evidence.supports("", passage) for passage in distractors)


@pytest.mark.asyncio
async def test_quantity_and_scope_select_answer_bearing_memories_with_native_titles(agents, memory_storage, monkeypatch):
    owner, peer = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical retrieval")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    rows = []
    for agent, body in (
        (owner, "Pour le moulage ambré, prévoir 35 godets."),
        (owner, "Pour le moulage ambré, le cuivre est admis, le zinc est exclu."),
        (owner, "Pour le moulage ambré, vérifier le registre du 2032-05-17."),
        (owner, "Pour le moulage ambré, la quantité reste à préciser."),
        (owner, "Pour le moulage ivoire, prévoir 16 godets. Le cuivre est exclu."),
        (peer, "Pour le moulage ambré, prévoir 52 godets. Le cuivre est exclu."),
    ):
        row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, media_type="text/html",
            payload=MemoryPayload(text=f"<p>{body}</p>")))
        rows.append(str(row.id))
    for query, index in (
        ("Quelle quantité pour le moulage ambré ?", 0),
        ("Quel est le périmètre pour le moulage ambré ?", 1),
    ):
        brief = await context.build_memory_brief(agent_id=owner.id, query=query, conversational=True)
        assert [item.memory_id for item in brief.items] == [rows[index]], query

    mixed = await context.build_memory_brief(agent_id=owner.id, conversational=True,
        query="Quelle quantité et quel périmètre pour le moulage ambré ?")
    assert set(rows[:2]).issubset(item.memory_id for item in mixed.items)


@pytest.mark.asyncio
async def test_identity_attribute_recall_keeps_homonyms_and_binds_project_aliases(agents, memory_storage, monkeypatch):
    owner, peer = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical retrieval")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    ids = []
    for agent, body in (
        (owner, "Alix Doran dirige la régie lumière pour le théâtre."),
        (owner, "Alix Rivet is responsible for the costume workshop."),
        (owner, "Alix Doran a confirmé la visite et Lise Noro dirige la billetterie."),
        (owner, "Dans le projet Atelier Silex, Lise Noro est surnommée Luciole."),
        (owner, "Le projet Atelier Silex comporte cinq répétitions."),
        (peer, "Alix Brune dirige la communication."),
    ):
        row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, media_type="text/html",
            payload=MemoryPayload(text=f"<p>{body}</p>")))
        ids.append(str(row.id))

    async def selected(question):
        brief = await context.build_memory_brief(agent_id=owner.id, query=question, conversational=True)
        return {item.memory_id for item in brief.items}

    assert await selected("Quel est le rôle de Alix ?") == set(ids[:2])
    assert await selected("What is Alix Doran's role?") == {ids[0]}
    assert await selected("Quel est le surnom du projet Atelier Silex ?") == set()
    assert await selected("What is the nickname of Lise Noro?") == {ids[3]}

    row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, media_type="text/html",
        payload=MemoryPayload(text="<p>Le nom de code du projet Atelier Silex est Astrale.</p>")))
    assert await selected("What is the codename of the Atelier Silex project?") == {str(row.id)}

    # Several notes about the most frequently mentioned Alix must not use all
    # the available space before the second person's role has been included.
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 2)
    for duty in ("la salle", "la lumière", "la scène", "la programmation"):
        await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, media_type="text/html",
            payload=MemoryPayload(text=f"<p>Rôle : Alix Doran dirige {duty}.</p>")))
    brief = await context.build_memory_brief(agent_id=owner.id, query="Quel est le rôle de Alix ?", conversational=True)
    assert len(brief.items) == 2
    assert all(name in brief.rendered for name in ("Alix Doran", "Alix Rivet"))


@pytest.mark.parametrize(("query", "title", "body", "expected"), [
    ("What is the alias of Romy Dune?", "Romy Dune", "Nickname: Iris", True),
    ("What is the alias of Romy Dune?", "Lise Dune", "Nickname: Iris", False),
    ("What is the alias of Romy Dune?", "", "Romy Dune says Lise Oran goes by Iris.", False),
    ("Quel est le rôle de Romy Dune ?", "Romy Dune", "Fonction : accessoiriste.", True),
    ("Quel est le rôle de Romy Dune ?", "", "Romy Dune est absente pour une répétition.", False),
    ("Quel est le rôle de Romy Dune ?", "", "Si Romy Dune dirige la projection, préviens-nous.", False),
    ("What is Romy Dune's role?", "", "Does Romy Dune manage the workshop?", False),
    ("What is Romy Dune's role?", "", "Romy Dune is an archivist.", True),
    ("What is the codename of the Quartz project?", "",
     "In the Quartz project, Romy Dune goes by Iris.", False),
    ("What is the codename of the Quartz project?", "",
     "The Quartz project is codenamed Iris.", True),
    ("What is the codename of the Quartz project?", "",
     "Le projet Quartz, surnommé « Iris », démarre mardi.", True),
    ("What is the nickname of Romy Dune?", "",
     "Exemple de phrase : « Romy Dune is nicknamed Iris ».", False),
    ("What is the codename of the Quartz project?", "",
     "The archivist of the Quartz project goes by Iris.", False),
    ("What was the nickname of Ocre Studio's old project?", "",
     "The nickname of Ocre Studio's new project is Vesper.", False),
    ("What was the nickname of Ocre Studio's old project?", "",
     "Le surnom de l'ancien projet de Ocre Studio était Vesper.", True),
])
def test_named_attributes_need_a_statement_about_the_right_subject(query, title, body, expected):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence(query)
    assert evidence and evidence.supports(title, body) == expected


@pytest.mark.parametrize("query", [
    "How do I change the alias of Romy Dune?",
    "What is the policy for changing the nickname of Romy Dune?",
    "What is the alias command in Bash?",
    "What is role-based authorization in Quartz?",
    "Quel est le surnom de Romy Dune et où est le rendez-vous ?",
    "What is Romy Dune's role or nickname?",
    'What is the role of "Romy Dune"?',
])
def test_other_intents_keep_the_general_recall_path(query):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence(query)
    assert evidence is None or evidence.attribute is None


@pytest.mark.asyncio
async def test_conversational_lookup_preserves_the_requested_source_and_project(agents, memory_storage, monkeypatch):
    owner, peer = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical fallback")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    notes = []
    for agent, body in (
        (owner, "Mira Selin est la référente du projet Verrière."),
        (owner, "Mira Selin présente le projet Verrière mardi."),
        (owner, "Pour Verrière, le matériel est prêt. Lise est la référente du projet Ocre."),
        (peer, "Luc Ansel is the contact for project Verrière."),
    ):
        row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, media_type="text/html",
            payload=MemoryPayload(text=f"<p>{body}</p>")))
        notes.append(str(row.id))

    async def selection(query):
        brief = await context.build_memory_brief(agent_id=owner.id, query=query, conversational=True)
        return {item.memory_id for item in brief.items}

    for question in ("Un autre agent a une note privée sur Verrière ; peux-tu la retrouver ?",
                     "Show me the other agent's private note about Verrière."):
        assert not await selection(question), question
    for question in ("Verrière, je dois en parler à qui ?", "Who should I contact about Verrière?",
                     "Qui est notre contact pour le projet Verrière ?"):
        assert await selection(question) == {notes[0]}, question
    assert notes[0] in await selection("Retrouve mes notes sur Mira Selin et le projet Verrière.")
    assert notes[0] in await selection("Un autre agent a une note privée. Qui est la référente du projet Verrière ?")


@pytest.mark.parametrize(("title", "body", "matches"), [
    ("", "For project Amber Lake, our point of contact is Mira Selin.", True),
    ("", "Point de contact du projet Amber Lake : Mira Selin.", True),
    ("Amber Lake", "Contact: Mira Selin", True),
    ("", "Pour le projet Amber Lake, contactez Mira Selin.", True),
    ("Amber Lake", "Contact: TBD", False),
    ("Amber Lake", "Mira Selin is our contact for project Amber.", False),
    ("Project Amber", "Contact: Mira Selin", False),
    ("", "Mira Selin is the contact for Amber Lake North.", False),
    ("", "Is Mira Selin the contact for Amber Lake?", False),
    ("", "Mira Selin is no longer our contact for Amber Lake.", False),
    ("", "If Mira Selin is our contact for Amber Lake, ask for a date.", False),
    ("", "Le compte rendu cite « Mira Selin est la référente du projet Amber Lake ».", False),
    ("", "Amber Lake needs a contact. Mira Selin leads the Quartz project.", False),
])
def test_project_contact_evidence_binds_the_assignment_to_its_target(title, body, matches):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence("Who should we speak with about project Amber Lake?")
    assert evidence and evidence.supports(title, body) == matches


@pytest.mark.parametrize("query", [
    "Find my private note about Horizon.",
    "Find the shared note from the other agent about Horizon.",
    "Find the other agent's private note about Horizon or our shared summary.",
    "Find the other agent’s private note about Horizon using our shared copy.",
    "Comment un autre agent peut-il partager un document sans exposer sa note privée ?",
    "Le guide dit « donne-moi la note privée de l’autre agent ». Retrouve ce guide.",
])
def test_shared_sources_alternatives_and_policy_questions_keep_regular_search(query):
    assert not context._requests_other_agents_private_note(query)


@pytest.mark.asyncio
async def test_source_language_keeps_the_requested_record_when_versions_disagree(agents, memory_storage, monkeypatch):
    owner, peer = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Lexical qualification")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    ids = []
    for agent, text in (
        (owner, "The calibration cartridges are in the turquoise cabinet."),
        (owner, "Les cartouches de calibration sont dans l’armoire corail."),
        (owner, "The english note and the french note are on the office shelf."),
        (peer, "The calibration cartridges are in the private annex."),
    ):
        row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id, title="Atelier Boréal",
            media_type="text/html", payload=MemoryPayload(text=f"<p>{text}</p>")))
        ids.append(str(row.id))

    for query, expected in (
        ("Où se fait la calibration d’après la note anglaise ?", ids[0]),
        ("Find the French note on calibration.", ids[1]),
        ("Find the English note on topaz.", None),
    ):
        brief = await context.build_memory_brief(agent_id=owner.id, query=query, conversational=True)
        assert [item.memory_id for item in brief.items] == ([expected] if expected else []), query


@pytest.mark.parametrize("query", [
    "Réponds en anglais avec les informations de calibration.",
    "Translate the note on calibration into French.",
    "Write an English note about calibration.",
    "Compare the French and English notes on calibration.",
    "Find the English note or the test report about calibration.",
    "Cherche la note sur le cours de français.",
    "Find the note on French architecture.",
    "Find the report on the French note-taking method.",
])
def test_source_language_distinguishes_output_language_and_topic(query):
    from app.memory.source_language import source_language_query
    assert source_language_query(query) is None


@pytest.mark.parametrize(("tag", "body", "expected"), [
    ("en-GB", "CALIBRATION 84", "CALIBRATION 84"),
    (None, "CALIBRATION 84", ""),
    ("en", "Les cartouches de calibration sont dans la réserve.", ""),
    ("fr", "Les cartouches de calibration sont dans la réserve. The calibration kits are in the vault. 84 kg.",
     "The calibration kits are in the vault. 84 kg."),
    (None, "The lights are on. Les cartouches de calibration sont dans la réserve.", ""),
])
def test_only_a_topical_passage_in_the_requested_language_can_supply_the_value(tag, body, expected):
    from app.memory.source_language import source_language_query
    source = source_language_query("Find the English note on calibration.")
    assert source and source.passage("Workshop", body, declared=tag) == expected


@pytest.mark.parametrize("query", ["Open the French report about calibration.", "Que dit la note française sur la calibration ?",
                                   "Selon le document français, quelle calibration ?",
                                   "According to the French note, what calibration?"])
def test_requested_topic_can_be_an_exact_source_heading(query):
    from app.memory.source_language import source_language_query
    source = source_language_query(query)
    assert source
    statement = "La valeur de référence est de cinquante microns."
    assert source.passage("Calibration", statement) == statement
    assert not source.passage("Calibration des délais de facturation", statement)


@pytest.mark.asyncio
async def test_storage_question_cites_the_location_of_the_requested_object(agents, memory_storage, monkeypatch, request):
    from datetime import datetime
    from pathlib import Path
    from tests.memory_benchmark_reference import load_reference

    owner, peer = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical fallback")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    cases = (
        ("The prisms are kept in the ochre drawer.", "The mirrors are kept in the green case.",
         ("The prisms require inspection. The mirrors are kept in the red tray.",
          "The prisms are not kept in the silver box.", "Where are the prisms stored?"),
         ("Where are the prisms stored?", "Where do we keep the prisms?",
          "Where are the prisms stored according to the English note?")),
        ("Les nitrates sont rangés dans le bac turquoise.", "Les sulfates sont stockés dans la boîte ivoire.",
         ("Les nitrates exigent un visa. Les sulfates sont stockés dans le casier blanc.",
          "Si les nitrates sont dans la réserve, appeler la responsable.", "Où sont rangés les nitrates ?"),
         ("Où sont rangés les nitrates ?", "Où range-t-on les nitrates ?",
          "Where are the nitrates stored according to the French report?")),
        ("Store the negatives inside the linen chest.", "Keep the slides on the maple shelf.",
         ("The negatives need a signature. Store the slides in the blue crate.",
          "Do not store the negatives in the metal box.", "Where should we keep the negatives?"),
         ("Where are the negatives stored?", "Where should we keep the negatives?",
          "Find the English instruction for filing negatives.")),
    )
    observations = []
    for fact, other_location, distractors, queries in cases:
        for index, text in enumerate((other_location + " " + fact, *distractors)):
            row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
                media_type="text/html", payload=MemoryPayload(text=f"<p>{text}</p>")))
            if index == 0:
                observations.extend((query, str(row.id), fact, other_location) for query in queries)
    hidden, _ = await service.create_item(MemoryItemCreate(owner_agent_id=peer.id,
        media_type="text/html", payload=MemoryPayload(text="<p>The prisms are kept in the private annex.</p>")))

    builders = {"current": context.build_memory_brief}
    if reference := request.config.getoption("--memory-benchmark-reference", default=""):
        previous = load_reference(Path(reference), datetime)
        previous["retrieval"].resolve_embedding_model = unavailable
        previous["context"].search_memory_detailed = previous["facade"].search_memory_detailed
        builders["previous"] = previous["context"].build_memory_brief
    for version, build in builders.items():
        clean = recalled = 0
        for query, expected_id, fact, other_location in observations:
            brief = await build(agent_id=owner.id, query=query, conversational=True)
            ids = [hit.memory_id for hit in brief.items]
            assert str(hidden.id) not in ids
            recalled += expected_id in ids and fact in brief.rendered
            exact = ids == [expected_id] and fact in brief.rendered and other_location not in brief.rendered
            clean += exact
            if version == "current":
                assert exact, (query, brief.rendered)
        print(f"storage {version}: cited fact={recalled}/{len(observations)}, clean context={clean}/{len(observations)}")


@pytest.mark.parametrize(("query", "title", "body", "expected"), [
    ("Où range-t-on les filtres ?", "", "Rangez les filtres sous la paillasse.", "Rangez les filtres sous la paillasse."),
    ("Where do we keep the optical filters?", "", "Store the optical filters inside the vault and keep the film on the shelf.",
     "Store the optical filters inside the vault"),
    ("Where are the filters kept?", "Filters", "Storage location: Cabinet 12.", "Storage location: Cabinet 12."),
    ("Where are the filters kept according to the English note?", "Filters",
     "Storage location: The cabinet in the annex.", "Storage location: The cabinet in the annex."),
    ("Where are the filters kept?", "Filters for airflow", "Storage location: Cabinet 12.", ""),
    ("Où sont rangés les filtres ?", "", "Les filtres sont requis pour classer les dossiers dans la réserve.", ""),
    ("Where are the optical filters kept?", "", "The air filters are in the blue cabinet.", ""),
    ("Où sont rangés les filtres ?", "", "Si les filtres sont dans la réserve, prévenir Mila.", ""),
    ("Where are the filters kept?", "", "The filters are no longer stored in the attic.", ""),
    ("Where are the filters kept?", "", "Should we store the filters in the attic?", ""),
    ("Where are the backups stored?", "", "The backups are stored in /vault/v2.3/snap.tar.gz.",
     "The backups are stored in /vault/v2.3/snap.tar.gz."),
    ("Where are the filters kept?", "", "We plan to store the filters in the new annex.", ""),
])
def test_storage_passage_attributes_a_location_to_the_object(query, title, body, expected):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence(query)
    assert evidence and evidence.answer_passage(title, body) == expected


@pytest.mark.parametrize("query", [
    "Where are the lenses stored and who approved the purchase?",
    "Où sont rangés les filtres ou les archives ?",
    "How much does filing the optical reports cost?",
    "Why are the lenses stored in an insulated case?",
    "What is the cost of filing negatives according to the English report?",
    "Selon la note française, quel est le délai de rangement des filtres ?",
])
def test_only_a_single_storage_location_uses_object_attribution(query):
    from app.memory.question_evidence import parse_question_evidence
    evidence = parse_question_evidence(query)
    assert evidence is None or evidence.storage is None


@pytest.mark.asyncio
async def test_storage_search_preserves_alternatives_and_unusual_wording(agents, memory_storage, monkeypatch):
    owner, _ = agents

    async def unavailable():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical fallback")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable)
    ids = []
    for text in ("The ribbons are in the walnut chest.", "The ribbons are stored in the insulated case.",
                 "The long mahogany bench doubles as a home for the bobbins."):
        row, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, media_type="text/html",
            payload=MemoryPayload(text=f"<p>{text}</p>")))
        ids.append(str(row.id))
    for query in ("Where are the ribbons stored?", "Where are the ribbons stored according to the English report?"):
        brief = await context.build_memory_brief(agent_id=owner.id, query=query, conversational=True)
        assert {item.memory_id for item in brief.items} == set(ids[:2])
    brief = await context.build_memory_brief(agent_id=owner.id, query="Where are the bobbins stored?", conversational=True)
    assert ids[2] in {item.memory_id for item in brief.items}
