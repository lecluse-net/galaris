"""Documents stay findable, addressable and covered through canonical search."""

import math

import pytest
from sqlalchemy import delete, select

from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_service import resource_search, resource_read
from app.memory import retrieval, semantic_index, service
from app.memory.embedding import EmbeddingModel, MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryAutomationJob, MemoryEmbeddingChunk, MemoryEmbeddingManifest
from app.memory.passages import document_passages
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemoryRecallRequest


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
        owner_agent_id=owner.id, node_kind="document", memory_type="working", title="Procédure technique",
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
        owner_agent_id=owner.id, node_kind="document", memory_type="working", title="Documentation",
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
        owner_agent_id=owner.id, node_kind="document", memory_type="working", title="Atelier 3D",
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
async def test_similar_documents_keep_complementary_facts(agents, memory_storage, vectors):
    owner, _ = agents
    identities = set()
    for threshold in (10, 20):
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner.id, node_kind="document", memory_type="working", title="Réglages du moteur",
            payload=MemoryPayload(text="<p>Présentation commune du moteur, fonctionnement, maintenance et contrôles.</p>"
                                 f"<p>Seuil spécifique de cette variante : {threshold}.</p>"), media_type="text/html",
        ), deduplicate=False)
        identities.add(item.id)
        await semantic_index.process_embedding_job({"item_id": str(item.id)})
    result = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="Réglages du moteur"))
    assert {hit.item.id for hit in result.hits} == identities


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
        owner_agent_id=owner.id, node_kind="document", memory_type="working", title="Archive",
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
