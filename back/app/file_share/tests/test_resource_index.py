import asyncio
from math import ceil
from time import perf_counter
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.document import document_service, resource_service as documents
from app.document.schemas import DocumentGrantUpdate, DocumentPayload, DocumentUpdate
from app.file_share import ResourceContext, resource_create, resource_search
from app.file_share import resource_index
from app.file_share.models import ResourceIndexContent, ResourceIndexSource
from app.file_share.resource_index_query import index_details, memory_index_graph, related_index_sources, search_resource_index
from app.memory import create_mail_contact
from app.memory import indexed_resources, service as memory
from app.memory.context import build_memory_brief
from app.memory.schemas import MemoryGraphExpandRequest
from app.memory.tests.conftest import agents, memory_storage  # noqa: F401
from app.memory.tests.document_fixtures import project_document


async def _document(owner, title, content, *, kind="text"):
    return await document_service.create_document(owner_agent_id=owner.id, title=title, content=content,
                                                   task_id=None, document_format=kind)


async def _index(document):
    return await resource_index.index_subject(resource_index.IndexSubject("document", document.id, document.content_hash))


@pytest.mark.asyncio
async def test_shared_document_analysis_reuses_passages_and_rechecks_access(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    raw = "<p>La balise synthétique quartzazur est dans la réponse courante.</p>"
    document = await _document(owner, "Source synthétique", raw)
    copy = await _document(reader, "Copie synthétique", raw)
    extraction = AsyncMock(wraps=resource_index._extract)
    monkeypatch.setattr(resource_index, "_extract", extraction)
    assert await _index(document)
    assert await _index(copy)
    assert await db.scalar(select(func.count()).select_from(ResourceIndexContent)) == 1
    assert await db.scalar(select(func.count()).select_from(ResourceIndexSource)) == 2
    assert extraction.await_count == 1

    uri = f"document://{document.id}"
    ctx = ResourceContext(reader.id, "internal")
    assert await search_resource_index(ctx, "quartzazur", mode="text", uri=uri) is None
    await documents.set_item_grant(document.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    found = await resource_search(ctx, uri, "quartzazur", mode="text")
    assert [hit.resource.uri for hit in found.hits] == [uri]
    assert "réponse courante" in found.hits[0].passages[0]["text"]
    await documents.update_summary(document.id, DocumentUpdate(payload=DocumentPayload(text="<p>Synthèse quartzmanuel.</p>")),
                                   actor_agent_id=owner.id)
    summary = await resource_search(ctx, uri, "quartzmanuel", mode="text")
    assert "quartzmanuel" in summary.hits[0].excerpt
    assert summary.hits[0].passages == []
    combined = await resource_search(ctx, "memory://", "quartzazur", mode="text")
    assert uri in {hit.resource.uri for hit in combined.hits}
    first_page = await resource_search(ctx, "memory://", "quartzazur", mode="text", max_results=1)
    assert first_page.next_cursor is not None
    second_page = await resource_search(ctx, "memory://", "quartzazur", mode="text", max_results=1, cursor=first_page.next_cursor)
    assert {page.hits[0].resource.uri for page in (first_page, second_page)} == {uri, f"document://{copy.id}"}
    from app.file_share.resource_index_query import memory_index_search

    monkeypatch.setattr(indexed_resources, "resource_search", memory_index_search)
    brief = await build_memory_brief(agent_id=reader.id, query="quartzazur")
    assert any(item.resource_uri == uri for item in brief.items)
    await documents.remove_item_grant(document.id, reader.id, actor_agent_id=owner.id)
    assert await search_resource_index(ctx, "quartzazur", mode="text", uri=uri) is None
    assert (await search_resource_index(ctx, "quartzazur", mode="text")).hits[0].resource.uri == f"document://{copy.id}"

    previous = resource_index.IndexSubject("document", document.id, document.content_hash)
    await documents.update_item(document.id, DocumentUpdate(payload=DocumentPayload(text="<p>Nouvelle balise quartzcarmin.</p>")),
                                actor_agent_id=owner.id)
    assert not await resource_index.index_subject(previous)
    assert await search_resource_index(ResourceContext(owner.id, "internal"), "quartzazur", mode="text", uri=uri) is None
    current, _access = await documents.get_item_metadata(document.id, agent_id=owner.id)
    assert await _index(current)
    assert (await resource_search(ResourceContext(owner.id, "internal"), uri, "quartzcarmin", mode="text")).hits
    await documents.delete_document(document.id, actor_agent_id=owner.id)
    await resource_index.prune_retired_index_sources()
    assert await db.scalar(select(func.count()).select_from(ResourceIndexContent)) == 1


@pytest.mark.asyncio
async def test_order_links_have_literal_evidence_and_both_sources_must_be_readable(db, agents, memory_storage, monkeypatch):
    owner, reader = agents
    def piece(title, order):
        return f"<p>{title}</p><p>Commande : {order}</p><p>SIRET fournisseur : 12345678901234</p>"

    quote = await _document(owner, "Devis", piece("Devis D-042", "C-318"))
    invoice = await _document(owner, "Facture", piece("Facture F-204", "C-318"))
    delivery = await _document(owner, "Livraison", piece("Bon de livraison BL-91", "C-318"))
    other = await _document(owner, "Autre livraison", piece("Bon de livraison BL-92", "C-319"))
    for document in (quote, invoice, delivery, other):
        assert await _index(document)
        await project_document(document.id)
    invoice_uri = f"document://{invoice.id}"
    assert {edge["uri"] for edge in await related_index_sources(ResourceContext(owner.id, "internal"), invoice_uri)} == {
        f"document://{quote.id}", f"document://{delivery.id}",
    }
    for document in (invoice, delivery):
        await documents.set_item_grant(document.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    edges = await related_index_sources(ResourceContext(reader.id, "internal"), invoice_uri)
    assert [edge["uri"] for edge in edges] == [f"document://{delivery.id}"]
    assert edges[0]["evidence"]["source"]["order"] == "C-318"
    graph = await memory_index_graph(reader.id, {quote.id, invoice.id, delivery.id, other.id}, None, 10)
    assert len(graph) == 1
    assert {graph[0].source_item_id, graph[0].target_item_id} == {invoice.id, delivery.id}
    monkeypatch.setattr(indexed_resources, "resource_graph", memory_index_graph)
    expanded = await memory.expand_graph_node(MemoryGraphExpandRequest(agent_id=reader.id, item_id=invoice.id))
    assert {node.id for node in expanded.nodes} == {delivery.id}
    assert len(expanded.edges) == 1 and expanded.edges[0].relation_type == "same_order"
    await documents.remove_item_grant(delivery.id, reader.id, actor_agent_id=owner.id)
    assert not await memory_index_graph(reader.id, {quote.id, invoice.id, delivery.id}, None, 10)


@pytest.mark.asyncio
async def test_dataset_passages_keep_json_pointers(db, agents, memory_storage):
    owner = agents[0]
    data = await _document(owner, "Données synthétiques", '{"commandes":[{"libellé":"saphirdelta"}]}', kind="data")
    assert await _index(data)
    actor = ResourceContext(owner.id, "internal")
    result = await resource_search(actor, "memory://", "saphirdelta", mode="text")
    assert result.hits[0].passages[0]["json_pointer"] == "/commandes/0/libellé"
    native = await resource_search(actor, f"data://{data.id}", "saphirdelta", mode="text")
    assert native.ranking_version == "dataset-hybrid/1"


@pytest.mark.asyncio
async def test_stored_file_and_completed_task_use_the_same_search_with_separate_access(db, agents, isolated_managed_files, monkeypatch):
    from app.agent import ExecutionResult
    from app.task import Task, TaskStatus

    owner, peer = agents
    monkeypatch.setattr(resource_index, "_embedding_model", None)
    actor = ResourceContext(owner.id, "internal")
    uploaded = await resource_create(actor, "file://", b"Synthetic results for quasartrack.", name="Report.txt")
    task = Task(agent_id=owner.id, label="Synthetic outcome", objective="<p>Check the synthetic report.</p>", status=TaskStatus.SUCCESS)
    task.set_execution_result(ExecutionResult(prompt="Synthetic request", success=True, result="Synthetic completion quasartrack."))
    conversation_task = Task(agent_id=owner.id, label="Synthetic conversation", objective="quasartrack transcript",
                             status=TaskStatus.SUCCESS, message_platform="internal")
    db.add(task)
    db.add(conversation_task)
    await db.flush()
    handled = select(ResourceIndexSource.source_kind).where(ResourceIndexSource.id.is_(None))
    pending = {subject.kind: subject for subject in await resource_index.pending_subjects(handled)}
    assert pending["stored"].key == UUID(uploaded.uri.removeprefix("file://"))
    assert pending["task"].key == task.id
    assert not await resource_index.index_subject(resource_index.IndexSubject("task", conversation_task.id,
        await db.scalar(select(resource_index.task_fingerprint()).where(Task.id == conversation_task.id))))
    assert await resource_index.index_subject(pending["stored"])
    assert await resource_index.index_subject(pending["task"])
    result = await search_resource_index(actor, "quasartrack", mode="text")
    assert {hit.resource.uri for hit in result.hits} == {uploaded.uri, f"galaris://task/{task.id}"}
    assert await search_resource_index(ResourceContext(peer.id, "internal"), "quasartrack", mode="text") is None


@pytest.mark.asyncio
async def test_semantic_passage_is_shared_with_readers(db, agents, memory_storage, monkeypatch):
    from types import SimpleNamespace
    from app.file_share import FileCatalogueEnrichmentPort

    owner, reader = agents
    embed = AsyncMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(resource_index, "_embedding_model", AsyncMock(return_value=SimpleNamespace(key="synthetic", embed=embed)))
    document = await _document(owner, "Synthetic evidence", "<p>Le délai confirmé du projet quartz est de six jours.</p>")
    await documents.set_item_grant(document.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert await _index(document)
    handled = select(ResourceIndexSource.source_kind).where(ResourceIndexSource.id.is_(None))
    subject = await resource_index.pending_vector_subject(handled)
    assert subject is not None and await FileCatalogueEnrichmentPort().index_resource(subject)
    uri = f"document://{document.id}"
    results = await resource_search(ResourceContext(reader.id, "internal"), uri, "calendrier opérationnel", mode="semantic")
    assert results.retrieval_mode == "hybrid"
    assert results.hits[0].resource.uri == uri
    assert "six jours" in results.hits[0].passages[0]["text"]
    assert embed.await_count == 2  # one indexed passage and one search vector
    replacement = AsyncMock(side_effect=lambda texts: [[0.0, 1.0, 0.0] for _ in texts])
    monkeypatch.setattr(resource_index, "_embedding_model",
        AsyncMock(return_value=SimpleNamespace(key="replacement", embed=replacement)))
    lexical = await resource_search(ResourceContext(reader.id, "internal"), uri, "quartz", mode="semantic")
    assert lexical.retrieval_mode == "lexical" and lexical.degraded
    assert replacement.await_count == 0
    subject = await resource_index.pending_vector_subject(handled)
    assert subject is not None
    assert await FileCatalogueEnrichmentPort().index_resource(subject)
    hybrid = await resource_search(ResourceContext(reader.id, "internal"), uri, "calendrier opérationnel", mode="semantic")
    assert hybrid.retrieval_mode == "hybrid"
    assert hybrid.hits[0].passages == results.hits[0].passages
    assert replacement.await_count == 2  # re-embed the stored passage, then search


@pytest.mark.asyncio
async def test_invoice_contact_requires_an_exact_visible_identity(db, agents, memory_storage):
    owner, reader = agents
    contact = await create_mail_contact(owner_agent_id=owner.id, display_name="M. Dupont", email="client@example.org")
    await create_mail_contact(owner_agent_id=reader.id, display_name="M. Dupont", email="other@example.org")
    complete = await _document(owner, "Synthetic invoice", "<p>Facture F-123</p><p>Client : M. Dupont &lt;client@example.org&gt;</p>")
    ambiguous = await _document(owner, "Synthetic invoice 2", "<p>Facture F-124</p><p>Client : M. Dupont</p>")
    for invoice in (complete, ambiguous):
        assert await _index(invoice)
        await documents.set_item_grant(invoice.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    uri = f"document://{complete.id}"
    owner_details = await index_details(ResourceContext(owner.id, "internal"), uri)
    assert owner_details["document_kind"] == "invoice"
    assert [item["contact_id"] for item in owner_details["contacts"]] == [str(contact.memory_item_id)]
    assert (await index_details(ResourceContext(reader.id, "internal"), uri))["contacts"] == []
    assert (await index_details(ResourceContext(owner.id, "internal"), f"document://{ambiguous.id}"))["contacts"] == []


@pytest.mark.asyncio
async def test_thirty_readers_reuse_one_indexed_analysis_with_concurrent_searches(committed_database, memory_storage, monkeypatch):
    from app.agent import Agent
    from app.chat.tests.test_native_facade import _scope
    from core.database import get_db_session

    extraction = AsyncMock(wraps=resource_index._extract)
    monkeypatch.setattr(resource_index, "_extract", extraction)
    async with get_db_session() as db:
        owner, manager, _ = await _scope(db)
        readers = [Agent(code=f"resource-index-reader-{ordinal}", user_id=manager.id, title_id=owner.title_id,
            first_name="Synthetic", last_name=f"Reader {ordinal}", agent_driver="internal") for ordinal in range(30)]
        db.add_all(readers)
        await db.flush()
        documents_by_group = [
            [await _document(owner, f"Synthetic record {group}-{number}", "<p>Identifiant voilierquartz.</p>")
             for number in range(2)] for group in range(2)
        ]
        for document in [item for items in documents_by_group for item in items]:
            assert await _index(document)
        for group, items in enumerate(documents_by_group):
            for reader in readers[group::2]:
                for item in items:
                    await documents.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
        assert extraction.await_count == 1
        assert await db.scalar(select(func.count()).select_from(ResourceIndexContent)) == 1

    async def lookup(reader_id, expected):
        started = perf_counter()
        async with get_db_session():
            result = await resource_search(ResourceContext(reader_id, "internal"), "memory://", "voilierquartz",
                                           mode="text", max_results=5)
        assert {hit.resource.uri for hit in result.hits} == expected
        return (perf_counter() - started) * 1000

    wall_start = perf_counter()
    latencies = await asyncio.gather(*(lookup(reader.id, {f"document://{item.id}" for item in documents_by_group[ordinal % 2]})
        for ordinal, reader in enumerate(readers)))
    print(f"FEDERATED_CONCURRENCY readers=30 p95_ms={sorted(latencies)[ceil(len(latencies) * .95) - 1]:.2f} "
          f"wall_ms={(perf_counter() - wall_start) * 1000:.2f}")
