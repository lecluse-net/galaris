"""Documents stay findable, addressable and covered through canonical search."""

import math
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_service import resource_search, resource_read
from app.memory import bootstrap, retrieval, semantic_index, service
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.memory.embedding import EmbeddingModel, MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryAutomationJob, MemoryContactItem, MemoryEmbeddingChunk, MemoryEmbeddingManifest, MemoryLink
from app.memory.passages import document_passages
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryLinkCreate, MemoryPayload, MemoryRecallRequest, MemorySearchRequest


@pytest.fixture
def vectors(monkeypatch):
    model = EmbeddingModel(key="configured", code="configured", model_name="configured",
                           base_url="http://unused.invalid", api_key=None)
    async def resolve():
        return model
    async def embed(texts, **kwargs):
        assert kwargs["model"] == model
        return [[1.0, 0.0] if "QUARTZ" in text else [0.0, 1.0] for text in texts]
    async def query(*args, **kwargs):
        assert kwargs["model"] == model
        return [1.0, 0.0]
    monkeypatch.setattr(semantic_index, "resolve_embedding_model", resolve)
    monkeypatch.setattr(retrieval, "resolve_embedding_model", resolve)
    monkeypatch.setattr(semantic_index, "embed_many", embed)
    monkeypatch.setattr(retrieval, "embed_query", query)
    return model


@pytest.mark.asyncio
async def test_document_search_returns_readable_passages_and_rejects_partial_index(db, agents, memory_storage, vectors):
    owner, peer = agents
    filler = "<p>" + "Historique sans rapport. " * 100 + "</p>"
    html = "<h1>Compte rendu</h1>" + filler * 5 + "<h2>Restauration</h2><p>QUARTZ exige une sauvegarde vérifiée.</p>"
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind="document",  title="Procédure technique",
        media_type="text/html", payload=MemoryPayload(text=html),
    ))
    await semantic_index.process_embedding_job({"item_id": str(document.id)})
    manifest = await db.get(MemoryEmbeddingManifest, document.id)
    assert manifest.chunk_count > 1
    assert manifest.indexed_word_count == manifest.source_word_count
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    for scheme in ("memory", "document"):
        result = await resource_search(ctx, f"{scheme}://", "QUARTZ", mode="semantic")
        assert result.retrieval_mode == "hybrid"
        hit = result.hits[0]
        assert hit.resource.uri == f"document://{document.id}"
        assert "sauvegarde vérifiée" in hit.excerpt
        assert hit.passages[0]["section_path"] == ["Compte rendu", "Restauration"]
        page = await resource_read(ctx, hit.resource.uri, offset=hit.passages[0]["block_start"])
        assert "QUARTZ" in page.content
    denied = await resource_search(ResourceContext(agent_id=peer.id, runtime="internal"), "memory://", "QUARTZ")
    assert denied.hits == []
    await db.execute(delete(MemoryEmbeddingChunk).where(
        MemoryEmbeddingChunk.item_id == document.id, MemoryEmbeddingChunk.chunk_index == 0,
    ))
    await db.commit()
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="QUARTZ"))
    assert result.mode == "lexical" and result.degraded
    assert result.index_coverage.indexed_items == 0
    assert "QUARTZ" in result.hits[0].excerpt
    repair = await semantic_index.reconcile_embedding_index()
    assert repair.current == 0 and repair.queued == 1
    await semantic_index.process_embedding_job({"item_id": str(document.id)})
    healthy = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="QUARTZ"))
    assert healthy.mode == "hybrid" and not healthy.degraded


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "passage", "evidence"), [
    ("QUARTZ-729", "Ticket QUARTZ-729 : vérification finale.", "QUARTZ-729"),
    (
        "Quelle durée prévoir pour assembler le robot de démonstration ?",
        "Pièces câbles vis écrous roues capteurs piles moteurs boîtier boutons écran connecteurs supports. "
        "Assemblage du robot de démonstration : prévoir 25 à 35 min.",
        "25 à 35 min",
    ),
])
async def test_lexical_search_finds_late_document_passage_without_embeddings(agents, memory_storage, monkeypatch, query, passage, evidence):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind="document",  title="Documentation",
        media_type="text/html", payload=MemoryPayload(text="<p>" + "Contexte général. " * 1000 +
                                                     f"</p><p>{passage}</p>"),
    ))
    result = await resource_search(ResourceContext(agent_id=owner.id, runtime="internal"), "memory://", query)
    assert result.hits[0].resource.uri == f"document://{document.id}"
    assert evidence in result.hits[0].excerpt
    assert result.retrieval_mode == "lexical" and result.degraded
    for exact in (str(document.id), f"document://{document.id}"):
        located = await resource_search(ResourceContext(agent_id=owner.id, runtime="internal"), "memory://", exact)
        assert located.hits[0].resource.uri == f"document://{document.id}"


@pytest.mark.asyncio
async def test_hybrid_search_preserves_stronger_lexical_passage(db, agents, memory_storage, vectors, monkeypatch):
    async def embed(texts, **_kwargs):
        return [[0.9, 0.1] if "UnrealBloomPass" in text else [1.0, 0.0] for text in texts]

    monkeypatch.setattr(semantic_index, "embed_many", embed)
    owner, _ = agents
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind="document",  title="Atelier 3D",
        media_type="text/html", payload=MemoryPayload(text=
            "<h1>Présentation</h1><p>Une scène de démonstration en trois dimensions.</p>"
            "<h2>Réglages</h2><p>UnrealBloomPass : strength 0,3 ; radius 0,5 ; threshold 0,1.</p>"),
    ))
    await semantic_index.process_embedding_job({"item_id": str(document.id)})
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query="UnrealBloomPass strength radius threshold",
    ))
    assert result.mode == "hybrid"
    assert result.hits[0].item.id == document.id
    assert "strength 0,3" in result.hits[0].excerpt
    assert "threshold 0,1" in result.hits[0].excerpt
    assert result.hits[0].passages[0].block_start == 2
    page = await resource_read(ResourceContext(agent_id=owner.id, runtime="internal"),
                               f"document://{document.id}", offset=result.hits[0].passages[0].block_start)
    assert "threshold 0,1" in page.content


@pytest.mark.asyncio
@pytest.mark.parametrize("best_similarity", [0.75, 0.35])
async def test_semantic_recall_returns_best_candidates_without_a_threshold(agents, memory_storage, vectors, monkeypatch, best_similarity):
    """Return the best available items even for low scores or a dense shortlist."""
    owner, _ = agents
    monkeypatch.setattr(retrieval.runtime_settings, "MEMORY_RECALL_CANDIDATE_LIMIT", 8)

    async def embed(texts, **_kwargs):
        def vector(text):
            similarity = best_similarity if "Facturation" in text else best_similarity - 0.07 if "Modèles" in text else 0.10
            return [similarity, math.sqrt(1.0 - similarity ** 2)]
        return [vector(text) for text in texts]

    monkeypatch.setattr(semantic_index, "embed_many", embed)
    expected = None
    for index in range(20):
        title = "Facturation du fournisseur" if index == 0 else f"Modèles disponibles {index}" if index < 9 else f"Jardinage {index}"
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=title,
            payload=MemoryPayload(text="<p>Crédit annuel et tarif avantageux.</p>" if index == 0 else f"<p>Fiche de référence {index}.</p>"),
        ), deduplicate=False)
        await semantic_index.process_embedding_job({"item_id": str(item.id)})
        if index == 0:
            expected = item.id
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query="Nos échanges restent abordables", limit=4,
        semantic_query="Le prix de la communication quotidienne est raisonnable.",
    ))
    assert result.mode == "hybrid" and not result.degraded
    assert len(result.hits) == 4
    assert result.hits[0].item.id == expected


@pytest.mark.asyncio
async def test_recall_prioritizes_exact_entity_without_excluding_other_candidates(agents, memory_storage, vectors, monkeypatch):
    async def embed(texts, **_kwargs):
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic_index, "embed_many", embed)
    owner, _ = agents
    expected = None
    for name, preference in (("Vega", "une clé hexagonale"), ("Orion", "un tournevis plat")):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Outil préféré de {name}",
            payload=MemoryPayload(text=f"{name} utilise {preference}."),
        ))
        await semantic_index.process_embedding_job({"item_id": str(item.id)})
        if name == "Vega":
            expected = item.id
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="Outil préféré de Vega"))
    assert len(result.hits) == 2
    assert result.hits[0].item.id == expected
    missing = await resource_search(ResourceContext(agent_id=owner.id, runtime="internal"), "memory://", "INV-UNKNOWN-99271")
    # An unknown identifier no longer suppresses the nearest available memories.
    assert len(missing.hits) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "title", "body"), [
    ("Quel fichier Word contient les instructions de montage du robot ?",
     "Manuel de montage", "Le fichier Montage.docx contient les instructions de montage du robot."),
    ("Comment Orion organise-t-il les notices avec Aster ?",
     "Classement des notices", "L’utilisateur organise les notices par catégorie avec Aster."),
])
async def test_recall_keeps_implicit_subjects_and_capitalized_formats(agents, memory_storage, vectors, query, title, body):
    owner, _ = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title=title, payload=MemoryPayload(text=body),
    ))
    await semantic_index.process_embedding_job({"item_id": str(item.id)})
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query=query))
    assert result.hits[0].item.id == item.id


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Réglages du moteur", "Quels réglages du moteur faut-il vérifier ?"])
@pytest.mark.parametrize("facts", [
    ("Seuil : 10.", "Seuil : 20."),
    ("Seuil : -10.", "Seuil : 10."),
    ("Contrôle : 2028-04-02.", "Contrôle : 2028-04-03."),
    ("Le moteur est autorisé.", "Le moteur n'est pas autorisé."),
    ("Le moteur est autorisé.", "Le moteur est autorisé ?"),
    ("Référence : Cote.", "Référence : Côte."),
])
async def test_similar_documents_keep_complementary_facts(agents, memory_storage, vectors, facts, query):
    owner, _ = agents
    identities = set()
    for fact in facts:
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, node_kind="document",  title="Réglages du moteur",
            payload=MemoryPayload(text="<p>Présentation commune du moteur, fonctionnement, maintenance et contrôles.</p>"
                                 f"<p>{fact}</p>"), media_type="text/html",
        ), deduplicate=False)
        identities.add(item.id)
        await semantic_index.process_embedding_job({"item_id": str(item.id)})
    await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind="document",  title="Notes du moteur",
        payload=MemoryPayload(text="<p>Le moteur nécessite une maintenance régulière.</p>"), media_type="text/html",
    ))
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query=query, limit=2))
    assert {hit.item.id for hit in result.hits} == identities


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "query"), [
    ("Mésange", "Mesange"), ("Mésange", "Mésange"), ("Mésange", "Me\u0301sange"),
    ("Straße", "Strasse"), ("Σίσυφος", "σισυφοσ"), ("Ｌｉｏｒａ", "Liora"),
])
async def test_lexical_recall_normalizes_names_before_candidate_selection(agents, memory_storage, monkeypatch, name, query):
    owner, peer = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    expected, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title=name,
         payload=MemoryPayload(text=f"<p>{name} est le surnom de Liora Varel.</p>"),
    ))
    await service.create_item(MemoryItemCreate(
        owner_agent_id=peer.id, title=f"{name} privée", payload=MemoryPayload(text=f"<p>{name} est un autre surnom privé.</p>"),
    ))
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query=query, limit=2))
    assert result.hits and result.hits[0].item.id == expected.id
    assert all(hit.item.owner_agent_id == owner.id for hit in result.hits)
    assert name in result.hits[0].excerpt
    explicit = await service.search_items(MemorySearchRequest(agent_id=owner.id, query=query))
    assert [hit.item.id for hit in explicit.hits] == [expected.id]
    await service.update_item(expected.id, MemoryItemUpdate(
        title="Églantine", payload=MemoryPayload(text="<p>Églantine est le nouveau surnom.</p>"),
    ), actor_agent_id=owner.id)
    renamed = await service.search_items(MemorySearchRequest(agent_id=owner.id, query="Eglantine"))
    assert [hit.item.id for hit in renamed.hits] == [expected.id]
    stale = await service.search_items(MemorySearchRequest(agent_id=owner.id, query=query))
    assert stale.hits == []


@pytest.mark.asyncio
async def test_named_person_and_complementary_event_survive_a_small_recall_budget(agents, memory_storage, monkeypatch):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    identity, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Liora Varel",
        payload=MemoryPayload(text="<p>Liora Varel est ma cousine et anime un atelier de dessin.</p>"),
    ))
    event, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Cadeau de Liora Varel",
        payload=MemoryPayload(text="<p>Liora Varel m'a offert un carnet le 2028-04-02.</p>"),
    ))
    for index in range(8):
        await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Cadeau offert hier {index}",
            payload=MemoryPayload(text=f"<p>Liora Delis m'a offert un carnet hier, remis par Mina Varel ; dossier {index}.</p>"),
        ))
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query="C'est Liora Varel qui me l'a offert hier", limit=2,
    ))
    assert {hit.item.id for hit in result.hits} == {identity.id, event.id}
    monkeypatch.setattr(bootstrap.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(bootstrap.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 2)
    contribution = await bootstrap.memory_context_provider(AgentContextRequest(
        task_id=None, objective="C'est Liora Varel qui me l'a offert hier",
        agent=AgentSnapshot(id=owner.id, code=owner.code, first_name=owner.first_name,
                            last_name=owner.last_name, driver_code="internal"),
    ))
    assert "ma cousine" in contribution.shared_context
    assert "2028-04-02" in contribution.shared_context


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "Liora Varel et Neris Delis, qui fait quoi ?",
    "Rappelle-moi les rôles de Liora Varel et Neris Delis et leur échange.",
])
async def test_multiple_names_keep_distinct_roles_despite_shared_event_matches(agents, memory_storage, monkeypatch, query):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    identities = set()
    for name, role in (("Liora Varel", "coordonne l'atelier"), ("Neris Delis", "gère les inscriptions")):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=name,
            payload=MemoryPayload(text=f"<p>{name} {role}.</p>"),
        ))
        identities.add(item.id)
    for index in range(8):
        await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Échange {index}",
            payload=MemoryPayload(text=f"<p>Liora Varel et Neris Delis ont échangé ; séance {index}.</p>"),
        ))
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query=query, limit=3,
    ))
    assert identities <= {hit.item.id for hit in result.hits}


@pytest.mark.asyncio
async def test_complementary_event_is_not_crowded_out_by_person_profiles(agents, memory_storage, monkeypatch):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    for index in range(5):
        await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Liora Varel — repère {index}",
            payload=MemoryPayload(text=f"<p>Liora Varel est la référente de l'atelier {index}.</p>"),
        ))
    event, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Carnet reçu",
        payload=MemoryPayload(text="<p>Liora Varel m'a offert un carnet le 2028-04-02.</p>"),
    ))
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query="Liora Varel m'a offert ce carnet", limit=2,
    ))
    assert event.id in {hit.item.id for hit in result.hits}


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize(("query", "bridge", "role"), [
    ("Qui coordonne les échanges du collègue de Liora Varel ?",
     "Neris Delis travaille avec Liora Varel sur les ateliers.", "Neris Delis coordonne les échanges."),
    ("Who coordinates communication for Liora Varel's colleague?",
     "Neris Delis works with Liora Varel on the workshops.", "Neris Delis coordinates communication."),
    ("La personne qui travaille avec Liora Varel, elle fait quoi ?",
     "Neris Delis travaille avec Liora Varel sur les ateliers.", "Neris Delis restaure les violons."),
    ("Que fait la cousine de Liora Varel ?",
     "Neris Delis est la cousine de Liora Varel.", "Neris Delis restaure les violons."),
])
async def test_indirect_person_query_keeps_relation_and_target_role(agents, memory_storage, vectors, monkeypatch, query, bridge, role, semantic):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    if not semantic:
        monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    for index in range(6):
        await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Liora Varel — profil {index}",
            payload=MemoryPayload(text=f"<p>Liora Varel coordonne les échanges de son atelier {index}.</p>"),
            media_type="text/html",
        ))
    relation, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Collaboration",
        payload=MemoryPayload(text=f"<p>{bridge}</p>"), media_type="text/html",
    ))
    target, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Neris Delis",
        payload=MemoryPayload(text=f"<p>{role}</p>"), media_type="text/html",
    ))
    # A confirmed neighbour supplies the role even when it shares no query word.
    await service.create_link(MemoryLinkCreate(
        source_item_id=relation.id, target_item_id=target.id, relation_type="related_to",
    ), actor_agent_id=owner.id)
    if semantic:
        for item in (relation, target):
            await semantic_index.process_embedding_job({"item_id": str(item.id)})
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query=query, limit=2))
    assert {hit.item.id for hit in result.hits} == {relation.id, target.id}
    assert result.mode == ("hybrid" if semantic else "lexical")
    monkeypatch.setattr(bootstrap.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(bootstrap.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 2)
    contribution = await bootstrap.memory_context_provider(AgentContextRequest(
        task_id=None, objective=query,
        agent=AgentSnapshot(id=owner.id, code=owner.code, first_name=owner.first_name,
                            last_name=owner.last_name, driver_code="internal"),
    ))
    assert str(target.id) in contribution.shared_context
    assert str(relation.id) in contribution.shared_context


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["private", "expired", "forgotten", "contact", "temporal", "negated", "quoted", "curly_quoted", "contracted", "hypothesis", "uncertain", "wrong_relation", "reversed", "ambiguous", "direct_reference", "weak", "suggested"])
async def test_indirect_relation_never_bypasses_evidence_or_scope(db, agents, memory_storage, monkeypatch, boundary):
    owner, peer = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    statements = {
        "negated": "Neris Delis ne travaille pas avec Liora Varel.",
        "quoted": 'La citation est : "Neris Delis travaille avec Liora Varel".',
        "uncertain": "Neris Delis pourrait travailler avec Liora Varel.",
        "reversed": "Liora Varel est l'oncle de Neris Delis.",
        "curly_quoted": "“Neris Delis works with Liora Varel”.",
        "contracted": "Neris Delis doesn't work with Liora Varel.",
        "hypothesis": "hypothesis: Neris Delis works with Liora Varel.",
    }
    bridge, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Collaboration",
        payload=MemoryPayload(text=f"<p>{statements.get(boundary, 'Neris Delis travaille avec Liora Varel.')}</p>"),
        media_type="text/html",
    ))
    target, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=peer.id if boundary == "private" else owner.id,
        title="Neris Delis",
        payload=MemoryPayload(text="<p>Neris Delis restaure les violons.</p>"), media_type="text/html",
        valid_until=datetime(2001, 1, 1, tzinfo=timezone.utc) if boundary == "expired" else None,
        temporal={"year": 2001, "month": 1, "day": 1} if boundary == "temporal" else None,
    ))
    db.add(MemoryLink(source_item_id=bridge.id, target_item_id=target.id, relation_type="related_to",
                      confidence=0.5 if boundary == "weak" else 1.0, suggested=boundary == "suggested"))
    contact_id = None
    if boundary == "contact":
        contacts = []
        for title in ("Interlocuteur A", "Interlocuteur B"):
            contact, _ = await service.create_item(MemoryItemCreate(
                owner_agent_id=owner.id, title=title,
                payload=MemoryPayload(text=f"<p>Frontière synthétique : {title}.</p>"), media_type="text/html",
            ))
            contacts.append(contact.id)
        contact_id = contacts[0]
        assert len(set(contacts)) == 2
        for item, contact in ((bridge, contacts[0]), (target, contacts[1])):
            db.add(MemoryContactItem(owner_agent_id=owner.id, contact_item_id=contact, item_id=item.id,
                                    source_kind="synthetic-test", source_ref=str(item.id)))
    await db.flush()
    if boundary == "ambiguous":
        await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title="Autre collaboration",
            payload=MemoryPayload(text="<p>Mina Terel travaille avec Liora Varel.</p>"), media_type="text/html",
        ))
    if boundary == "forgotten":
        await service.forget_item(target.id, actor_agent_id=owner.id)
    direct_profile = None
    if boundary == "direct_reference":
        direct_profile, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title="Liora Varel",
            payload=MemoryPayload(text="<p>Liora Varel anime les ateliers.</p>"), media_type="text/html",
        ))
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id,
        query=("Que fait la tante de Liora Varel ?" if boundary == "wrong_relation" else
               "Que fait l'oncle de Liora Varel ?" if boundary == "reversed" else
               "Mon collègue Liora Varel, que fait-il ?" if boundary == "direct_reference" else
               "La personne qui travaille avec Liora Varel, elle fait quoi ?"),
        contact_item_id=contact_id, exclude_temporal=True, limit=2,
    ))
    assert target.id not in {hit.item.id for hit in result.hits}
    assert bridge.id in {hit.item.id for hit in result.hits}
    if direct_profile is not None:
        assert direct_profile.id in {hit.item.id for hit in result.hits}


@pytest.mark.asyncio
async def test_repeated_fact_does_not_displace_a_requested_complement(agents, memory_storage, monkeypatch):
    owner, _ = agents
    async def missing():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    repeated = set()
    for suffix, body in (("fiche", "<p>Liora Varel coordonne le prêt des carnets.</p>"),
                         ("copie", "<p><strong>Liora Varel</strong> coordonne le prêt des carnets !</p>")):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, title=f"Liora Varel — {suffix}",
            payload=MemoryPayload(text=body), media_type="text/html",
        ), deduplicate=False)
        repeated.add(item.id)
    event, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Remise des carnets",
        payload=MemoryPayload(text="<p>Liora Varel a offert les carnets le 2028-04-02.</p>"),
    ))
    result = await retrieval.recall_items(MemoryRecallRequest(
        agent_id=owner.id, query="Liora Varel : prêt et cadeau des carnets", limit=2,
    ))
    assert event.id in {hit.item.id for hit in result.hits}, [(hit.item.title, hit.excerpt) for hit in result.hits]
    assert len({hit.item.id for hit in result.hits} & repeated) == 1


@pytest.mark.asyncio
async def test_indexing_intent_survives_missing_configuration_and_rolls_back_with_source(db, agents, memory_storage):
    owner, _ = agents
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Durable intent", payload=MemoryPayload(text="Contenu initial."),
    ))
    assert await db.scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.payload["item_id"].as_string() == str(item.id),
        MemoryAutomationJob.kind == "semantic_index",
    )) is not None
    before = item.semantic_fingerprint
    transaction = await db.begin_nested()
    item.title = "Une nouvelle projection annulée"
    semantic_index.stage_embedding_refresh(item)
    new_fingerprint = item.semantic_fingerprint
    await db.flush()
    await transaction.rollback()
    assert await db.scalar(select(MemoryAutomationJob.id).where(
        MemoryAutomationJob.payload["source_fingerprint"].as_string() == new_fingerprint,
    )) is None
    await db.refresh(item)
    assert item.semantic_fingerprint == before


def test_document_passages_preserve_sections_tables_and_code():
    html = "<h1>Guide</h1><h2>Configuration</h2><table><tr><th>Clé</th><th>Valeur</th></tr><tr><td>QUARTZ</td><td>729</td></tr></table><pre><code>run --verify\nexit 0</code></pre>"
    selected = next(p for p in document_passages(html) if "QUARTZ" in p.text)
    assert selected.section_path == ("Guide", "Configuration")
    assert "Clé\tValeur" in selected.text
    assert "run --verify\nexit 0" in selected.text


@pytest.mark.asyncio
async def test_long_document_tail_is_indexed_and_configuration_change_rebuilds(db, agents, memory_storage, vectors, monkeypatch):
    owner, _ = agents
    document, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind="document",  title="Archive",
        media_type="text/html", payload=MemoryPayload(text="<p>" + "x " * 100_000 + "QUARTZ final</p>"),
    ))
    await semantic_index.process_embedding_job({"item_id": str(document.id)})
    manifest = await db.get(MemoryEmbeddingManifest, document.id)
    assert manifest.chunk_count > 256
    assert manifest.source_word_count == manifest.indexed_word_count
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="QUARTZ"))
    assert result.mode == "hybrid"
    assert "QUARTZ" in " ".join(p.excerpt for p in result.hits[0].passages)
    replacement = EmbeddingModel(key="replacement", code="replacement", model_name="replacement",
                                 base_url="http://unused.invalid", api_key=None)
    async def configured():
        return replacement
    calls = []
    async def embed(texts, **kwargs):
        calls.append(kwargs["model"].key)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(semantic_index, "resolve_embedding_model", configured)
    monkeypatch.setattr(retrieval, "resolve_embedding_model", configured)
    monkeypatch.setattr(semantic_index, "embed_many", embed)
    cold = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="QUARTZ"))
    assert cold.mode == "lexical" and cold.index_coverage.indexed_items == 0
    await semantic_index.process_embedding_job({"item_id": str(document.id)})
    await db.refresh(manifest)
    assert manifest.model_key == "replacement"
    assert calls and set(calls) == {"replacement"}
