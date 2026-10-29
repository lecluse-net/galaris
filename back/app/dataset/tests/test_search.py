"""Native Dataset discovery must find evidence, not just the start of the JSON."""

import json

import pytest

from app.dataset import service
from app.file_share import ResourceContext, resource_search


@pytest.fixture
def vectors(monkeypatch):
    from app.llm import ConfiguredEmbeddingModel
    from app.dataset import search, search_index

    model = ConfiguredEmbeddingModel(key="a" * 64, code="synthetic", model_name="synthetic", base_url="http://unused.invalid")
    async def resolve():
        return model
    async def embed(self, texts, **kwargs):
        return [[1.0, 0.0] if any(word in text.casefold() for word in ("quartz", "minerals", "minéraux")) else [0.0, 1.0] for text in texts]
    monkeypatch.setattr(search, "require_configured_embedding_model", resolve)
    monkeypatch.setattr(search_index, "require_configured_embedding_model", resolve)
    monkeypatch.setattr(ConfiguredEmbeddingModel, "embed", embed)
    return model


async def index_dataset(dataset, model):
    from app.dataset import search_index
    subject = f"{dataset.id}:{dataset.lock_version}:{model.key}"
    snapshot = await search_index.source(subject)
    prepared = await search_index.prepare(snapshot, model)
    assert await search_index.apply(subject, prepared)
    return subject, prepared


@pytest.mark.asyncio
async def test_text_discovery_finds_separate_terms_and_returns_the_matching_json_pointer(db, agents):
    owner, peer = agents
    dataset = await service.create(owner.id, title="Synthetic stock", content=json.dumps({
        "rows": [{"label": "ordinary padding", "quantity": 1}] * 30
        + [{"label": "quartz", "warehouse": "northern", "quantity": 17}],
    }))
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    page = await resource_search(context, "data://", "quartz northern", mode="text")
    assert [hit.resource.uri for hit in page.hits] == [f"data://{dataset.id}"]
    assert "quartz" in page.hits[0].excerpt and "17" in page.hits[0].excerpt
    assert page.hits[0].passages[0]["json_pointer"] == "/rows/30"
    assert page.hits[0].passages[0]["source_revision"] == dataset.revision
    library = await service.list_datasets(owner.id, query="quartz northern")
    assert [item["id"] for item in library["items"]] == [str(dataset.id)]
    assert (await service.list_datasets(peer.id, query="quartz northern"))["total"] == 0
    denied = await resource_search(ResourceContext(agent_id=peer.id, runtime="internal"),
        "data://", "quartz northern", mode="text")
    assert denied.hits == []


@pytest.mark.asyncio
async def test_semantic_discovery_preserves_evidence_and_rejects_stale_or_partial_generations(db, agents, vectors):
    from sqlalchemy import delete, select
    from app.dataset.models import DatasetSearchChunk, DatasetSearchIndex
    owner, peer = agents
    dataset = await service.create(owner.id, title="Synthetic minerals", content='{"rows":[{"name":"quartz","n":17},{"name":"granite","n":4}]}')
    await index_dataset(dataset, vectors)
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    result = await resource_search(context, "data://", "minéraux", mode="semantic")
    assert result.retrieval_mode == "hybrid" and not result.degraded
    assert result.hits[0].resource.uri == f"data://{dataset.id}"
    assert "quartz" in result.hits[0].excerpt
    assert result.hits[0].passages[0]["json_pointer"] == "/rows/0"
    assert result.index_coverage["indexed_items"] == 1
    denied = await resource_search(ResourceContext(agent_id=peer.id, runtime="internal"), "data://", "minéraux", mode="semantic")
    assert denied.hits == []
    index = await db.scalar(select(DatasetSearchIndex).where(DatasetSearchIndex.dataset_id == dataset.id))
    chunk = await db.scalar(select(DatasetSearchChunk.id).where(DatasetSearchChunk.index_id == index.id))
    await db.execute(delete(DatasetSearchChunk).where(DatasetSearchChunk.id == chunk))
    partial = await resource_search(context, "data://", "quartz", mode="semantic")
    assert partial.retrieval_mode == "lexical" and partial.degraded
    assert partial.hits[0].resource.uri == f"data://{dataset.id}"
    await index_dataset(dataset, vectors)
    await service.replace(dataset.id, owner.id, content='[{"name":"replaced"}]', expected_revision=1)
    stale = await resource_search(context, "data://", "quartz", mode="semantic")
    assert stale.hits == [] and stale.degraded


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["content", "metadata", "revoked"])
async def test_late_embedding_response_never_leaks_old_evidence(db, agents, vectors, monkeypatch, change):
    from app.llm import ConfiguredEmbeddingModel
    owner, peer = agents
    dataset = await service.create(owner.id, title="Synthetic minerals", content='[{"name":"quartz"}]')
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=peer.id,
        can_write=False, expected_lock_version=dataset.lock_version)
    await index_dataset(dataset, vectors)
    async def delayed(self, texts, **kwargs):
        if change == "content":
            await service.replace(dataset.id, owner.id, content='[{"name":"different"}]', expected_revision=1)
        elif change == "metadata":
            await service.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version,
                values={"title": "Changed title"})
        else:
            await service.set_grant(dataset.id, owner.id, kind="agent", principal=peer.id,
                can_write=None, expected_lock_version=dataset.lock_version)
        return [[1.0, 0.0]]
    monkeypatch.setattr(ConfiguredEmbeddingModel, "embed", delayed)
    result = await resource_search(ResourceContext(agent_id=peer.id, runtime="internal"), "data://", "minéraux", mode="semantic")
    assert result.hits == []


@pytest.mark.asyncio
async def test_index_publication_is_revision_guarded_idempotent_and_requeues_new_versions(db, agents, vectors):
    from sqlalchemy import select
    from app.dataset import search_index
    from app.dataset.models import DatasetSearchIndex
    owner, _ = agents
    dataset = await service.create(owner.id, title="Synthetic minerals", content='[{"name":"quartz"}]')
    unhandled = select(DatasetSearchIndex.model_key).where(False)
    subject = await search_index.claim_one(vectors.key, unhandled)
    assert subject == f"{dataset.id}:{dataset.lock_version}:{vectors.key}"
    payload = await search_index.prepare(await search_index.source(subject), vectors)
    await service.replace(dataset.id, owner.id, content='[{"name":"new quartz"}]', expected_revision=1)
    assert not await search_index.apply(subject, payload)
    fresh, payload = await index_dataset(dataset, vectors)
    assert await search_index.apply(fresh, payload)
    assert await search_index.count_pending(vectors.key, unhandled) == 0
    assert await search_index.count_pending("b" * 64, unhandled) == 1


@pytest.mark.asyncio
async def test_text_search_cursor_keeps_query_identity_and_all_ranked_results(db, agents):
    owner, _ = agents
    datasets = [await service.create(owner.id, title=f"Quartz stock {i}", content=json.dumps({"quartz": i})) for i in range(4)]
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    seen = []
    cursor = None
    while True:
        page = await resource_search(context, "data://", "quartz", mode="text", max_results=1, cursor=cursor)
        seen.extend(hit.resource.uri for hit in page.hits)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert len(seen) == len(set(seen)) == 4
    assert set(seen) == {f"data://{dataset.id}" for dataset in datasets}
    with pytest.raises(ValueError, match="cursor"):
        await resource_search(context, "data://", "other", mode="text", cursor=cursor)


def test_large_dataset_embedding_passages_keep_tail_and_escaped_locators():
    from app.dataset.passages import embedding_passages
    rows = [{"value": index} for index in range(1500)]
    chunks = embedding_passages(json.dumps({"a/b": rows}))
    assert len(chunks) < 100
    assert any('/a~1b/1499' in chunk.text and '1499' in chunk.text for chunk in chunks)
    assert all(chunk.json_pointer == '/a~1b' for chunk in chunks)


@pytest.mark.asyncio
async def test_search_rechecks_the_entire_page_after_descriptor_hydration(db, agents, monkeypatch):
    from app.dataset.provider import DatasetProvider
    owner, peer = agents
    datasets = [await service.create(owner.id, title=f'Quartz {i}', content='{"material":"quartz"}') for i in range(2)]
    for dataset in datasets:
        await service.set_grant(dataset.id, owner.id, kind='agent', principal=peer.id,
            can_write=False, expected_lock_version=dataset.lock_version)
    real_info = DatasetProvider.info
    calls = []
    async def info(self, ctx, uri):
        descriptor = await real_info(self, ctx, uri)
        calls.append(descriptor.uri)
        if len(calls) == 2:
            first = next(row for row in datasets if f'data://{row.id}' == calls[0])
            await service.set_grant(first.id, owner.id, kind='agent', principal=peer.id,
                can_write=None, expected_lock_version=first.lock_version)
        return descriptor
    monkeypatch.setattr(DatasetProvider, 'info', info)
    page = await resource_search(ResourceContext(agent_id=peer.id, runtime='internal'), 'data://', 'quartz', mode='text')
    assert [hit.resource.uri for hit in page.hits] == [calls[1]]
    assert page.degraded and page.degradation_reason == 'results_changed_during_search'
