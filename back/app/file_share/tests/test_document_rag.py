"""Real uploaded-file authorization, index reuse and deletion, including late workers."""

import asyncio
import json
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.agent.contracts import TaskMessage
from app.chat.tests.test_native_facade import _scope
from app.file_share import ResourceContext, resource_create, resource_delete
from app.harness.media import prepare_native_inputs
from app.llm import LLM, document_rag
from app.llm.embedding_facade import ConfiguredEmbeddingModel
from core.database import get_db_session
from core.storage import StoredFileDerivative


@pytest.mark.asyncio
@pytest.mark.parametrize('runtime', ['internal', 'hermes'])
async def test_mcp_search_can_requery_uploaded_file_without_creating_memories(committed_database, monkeypatch, runtime):
    from app.file_share import mcp
    from app.memory.models import MemoryItem, MemoryRevision
    from app.tools.mcp_loader import McpToolContext

    source = ('Synthetic background. ' * 2500 + '\nQUARTZ cancellation deadline is 47 days.\n'
              + 'Other synthetic details. ' * 100 + '\nNEBULA warranty is 83 months.').encode()
    async with get_db_session() as db:
        agent, _, _ = await _scope(db)
        stranger, _, _ = await _scope(db)
        owner_id, stranger_id = agent.id, stranger.id
        created = await resource_create(ResourceContext(owner_id, runtime), 'file://', source, name='Synthetic searchable.txt')
        memories = await db.scalar(select(func.count()).select_from(MemoryItem))
        revisions = await db.scalar(select(func.count()).select_from(MemoryRevision))
    model = ConfiguredEmbeddingModel(key='synthetic-search-vector', code='synthetic', model_name='synthetic', base_url='http://unused.invalid')
    calls = []
    async def embed(self, texts, **kwargs):
        calls.append(list(texts))
        return [[1., 0.] if '47 days' in text or 'cancellation' in text else [0., 1.] for text in texts]
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', embed)

    async with get_db_session():
        metadata = json.loads(await mcp.file_info(McpToolContext(agent_id=owner_id, runtime=runtime), created.uri))
        assert 'search' in metadata['capabilities']
        assert metadata['metadata']['content_search'] == {'tool': 'file_search', 'uri': created.uri,
            'modes': ['text', 'semantic'], 'exhaustive': False}
        assert not calls

    async def search(query, *, agent_id=owner_id, mode='semantic'):
        async with get_db_session():
            return json.loads(await mcp.search_files(McpToolContext(agent_id=agent_id, runtime=runtime),
                created.uri, query, mode=mode, max_results=1))

    first = await search('QUARTZ cancellation deadline')
    assert first['hits'][0]['resource']['uri'] == created.uri
    assert '47 days' in str(first['hits'][0]['passages'])
    initial = len(calls)
    second = await search('NEBULA warranty')
    assert '83 months' in str(second['hits'][0]['passages']) and len(calls) == initial + 1
    assert second['index_coverage']['exhaustive'] is False
    for passage in second['hits'][0]['passages']:
        assert source.decode()[passage['start']:passage['end']] == passage['text']
        assert passage['page'] == 1
    missing = await search('zzxyy-absent-needle', mode='text')
    assert missing['hits'] == [] and missing['relevance_status'] == 'no_sufficient_evidence'
    assert len(calls) == initial + 1
    with pytest.raises(PermissionError):
        await search('QUARTZ cancellation deadline', agent_id=stranger_id)
    async with get_db_session() as db:
        assert await db.scalar(select(func.count()).select_from(MemoryItem)) == memories
        assert await db.scalar(select(func.count()).select_from(MemoryRevision)) == revisions
        await resource_delete(ResourceContext(owner_id, runtime), created.uri)
        assert await db.scalar(select(StoredFileDerivative.id)) is None
    with pytest.raises(FileNotFoundError):
        await search('QUARTZ cancellation deadline')


@pytest.mark.asyncio
async def test_shared_document_attachment_reuses_rag_and_rechecks_revoked_access(committed_database, monkeypatch):
    from app.document import DocumentPermissionError
    from app.document.item_sharing import update_agent_sharing
    from app.file_share import resource_search

    async with get_db_session() as db:
        owner, _, _ = await _scope(db)
        reader, _, _ = await _scope(db)
        owner_id, reader_id = owner.id, reader.id
        ctx = ResourceContext(owner_id, 'internal')
        document = await resource_create(ctx, 'document://', b'<p>Synthetic shared sources.</p>', name='Synthetic research')
        attachment = await resource_create(ctx, document.uri + '/attachments/',
            b'Synthetic background. ' * 2500 + b'\nQUARTZ cancellation deadline is 47 days.', name='Synthetic shared.txt')
        await update_agent_sharing(UUID(document.uri.removeprefix('document://')), agent_id=owner_id,
            kind='agent', target_id=reader_id, access='read')
    calls = []
    async def embed(self, texts, **kwargs):
        calls.append(list(texts))
        return [[1., 0.] for text in texts]
    model = ConfiguredEmbeddingModel(key='synthetic-shared-vector', code='synthetic', model_name='synthetic', base_url='http://unused.invalid')
    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', embed)
    directories = []
    async with get_db_session():
        from app.file_share import prepared_resource
        async with prepared_resource(ctx, attachment.uri) as (_, directory):
            directories.append(directory)
        first = await resource_search(ctx, attachment.uri, 'QUARTZ cancellation deadline', mode='semantic')
        assert '47 days' in str(first.hits[0].passages)
    initial = len(calls)
    async with get_db_session():
        async with prepared_resource(ResourceContext(reader_id, 'hermes'), attachment.uri) as (_, directory):
            directories.append(directory)
        shared = await resource_search(ResourceContext(reader_id, 'hermes'), attachment.uri,
            'QUARTZ cancellation deadline', mode='semantic')
        assert shared.hits[0].passages == first.hits[0].passages and len(calls) == initial + 1
        await update_agent_sharing(UUID(document.uri.removeprefix('document://')), agent_id=owner_id,
            kind='agent', target_id=reader_id, access='none')
    async with get_db_session():
        with pytest.raises(DocumentPermissionError):
            await resource_search(ResourceContext(reader_id, 'hermes'), attachment.uri,
                'QUARTZ cancellation deadline', mode='semantic')
        assert len(calls) == initial + 1
        # Removing the current attachment retains its source for document history.
        await resource_delete(ctx, attachment.uri)
    async with get_db_session() as db:
        assert await db.scalar(select(StoredFileDerivative.id)) is not None
        from app.document.resource_service import delete_document
        await delete_document(UUID(document.uri.removeprefix('document://')), actor_agent_id=owner_id)
        assert await db.scalar(select(StoredFileDerivative.id)) is None
        assert all(not directory.exists() for directory in directories)


@pytest.mark.asyncio
@pytest.mark.parametrize('delete_during_indexing', [False, True])
async def test_uploaded_document_rag_rechecks_access_and_purges_on_delete(committed_database, monkeypatch, delete_during_indexing):
    source = ('Synthetic irrelevant background. ' * 2500 + '\nQUARTZ cancellation deadline is 47 days.').encode()
    async with get_db_session() as db:
        agent, _, _ = await _scope(db)
        stranger, _, _ = await _scope(db)
        owner_id, stranger_id = agent.id, stranger.id
        ctx = ResourceContext(owner_id, 'internal')
        created = await resource_create(ctx, 'file://', source, name='Synthetic report.txt')
        uri = created.uri
    identity = UUID(uri.removeprefix('file://'))
    model = ConfiguredEmbeddingModel(key='synthetic-rag-vector', code='synthetic', model_name='synthetic', base_url='http://unused.invalid')
    calls = []
    entered, resume = asyncio.Event(), asyncio.Event()

    async def embed(self, texts, **kwargs):
        calls.append(list(texts))
        if delete_during_indexing and len(calls) == 1:
            entered.set()
            await resume.wait()
        return [[1., 0.] if '47 days' in text or 'termination' in text else [0., 1.] for text in texts]

    monkeypatch.setattr(document_rag, 'require_configured_embedding_model', AsyncMock(return_value=model))
    monkeypatch.setattr(ConfiguredEmbeddingModel, 'embed', embed)
    message = TaskMessage(text='What is the QUARTZ cancellation deadline?', resource_uris=[uri])
    llm = LLM(context_length=4096, input_file=True, input_image=False)

    async def read(agent_id=owner_id, selected_llm=llm):
        async with get_db_session():
            return (await prepare_native_inputs(selected_llm, ResourceContext(agent_id, 'internal'), [message], []))[uri]

    if delete_during_indexing:
        worker = asyncio.create_task(read())
        try:
            await asyncio.wait_for(entered.wait(), 10)
            async with get_db_session():
                await resource_delete(ctx, uri)
            resume.set()
            late = await asyncio.wait_for(worker, 10)
            assert not late.prepared_parts and 'unavailable' in late.reason
        finally:
            resume.set()
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
    else:
        first = await read()
        assert first.content is None and 'RAG' in first.reason
        assert 'file_search' in first.reason
        assert '47 days' in str(first.prepared_parts) and 'chars ' in str(first.prepared_parts)
        assert len(str(first.prepared_parts)) < len(source) // 2
        async with get_db_session() as db:
            stored = await db.scalar(select(StoredFileDerivative).where(StoredFileDerivative.file_id == identity))
            assert stored is not None and len(stored.payload['vectors']) == len(stored.payload['passages'])
            from app.agent import Agent
            from app.file_share import document_rag_cache
            from core.storage import StoredFile
            owner = await db.get(Agent, owner_id)
            original_name = owner.first_name
            owner.first_name = 'Synthetic pending business change'
            original = await db.get(StoredFile, identity)
            cache = await document_rag_cache(ctx, uri, original.sha256)
            await cache.save(stored.fingerprint, stored.payload)
            await db.rollback()
            await db.refresh(owner)
            assert owner.first_name == original_name
        initial = len(calls)
        second = await read()
        assert second.prepared_parts == first.prepared_parts and len(calls) == initial + 1
        denied = await read(stranger_id)
        assert not denied.prepared_parts and denied.content is None and 'access denied' in denied.reason
        assert len(calls) == initial + 1
        # The same bytes fit a larger model and are supplied completely without a vector call.
        complete = await read(selected_llm=LLM(context_length=128_000, input_file=False, input_image=False))
        assert 'RAG' not in complete.reason and source.decode() in '\n'.join(complete.prepared_parts)
        assert len(calls) == initial + 1
        async with get_db_session():
            await resource_delete(ctx, uri)
    async with get_db_session() as db:
        assert await db.scalar(select(StoredFileDerivative.id).where(StoredFileDerivative.file_id == identity)) is None
    deleted = await read()
    assert not deleted.prepared_parts and deleted.content is None
