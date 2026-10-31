"""Source-owned extraction cleanup and measured, access-checked immutable reuse."""

import asyncio
import json
import statistics
import time

import pytest

from app.chat.tests.test_native_facade import _scope
from app.file_share import ResourceContext, prepared_resource, resource_create, resource_delete
from app.file_share import document_facade
from core.database import get_db_session


@pytest.mark.asyncio
async def test_immutable_preparation_reuse_and_source_deletion_purge(committed_database, monkeypatch):
    async with get_db_session() as db:
        owner, _, _ = await _scope(db)
        stranger, _, _ = await _scope(db)
        ctx = ResourceContext(owner.id, 'internal')
        created = await resource_create(ctx, 'file://', b'Synthetic stable contents. ' * 40_000, name='Synthetic large.txt')
        owner_id, stranger_id = owner.id, stranger.id
    original = document_facade.materialize_resource
    materializations = []
    async def materialize(*args, **kwargs):
        source = await original(*args, **kwargs)
        materializations.append(source.size)
        return source
    monkeypatch.setattr(document_facade, 'materialize_resource', materialize)
    durations = []
    async with get_db_session():
        async with prepared_resource(ctx, created.uri) as (initial, directory):
            assert initial.text().endswith('Synthetic stable contents. ')
        for _ in range(5):
            started = time.perf_counter()
            async with prepared_resource(ctx, created.uri) as (again, reopened):
                assert again == initial and reopened == directory
            durations.append(time.perf_counter() - started)
        print('PREPARATION_MEASUREMENT ' + json.dumps({'source_bytes': len(b'Synthetic stable contents. ' * 40_000),
            'warm_queries': len(durations), 'materializations': len(materializations),
            'materialized_bytes': sum(materializations), 'warm_median_ms': round(statistics.median(durations) * 1000, 3)}))
    async with get_db_session():
        with pytest.raises(PermissionError):
            async with prepared_resource(ResourceContext(stranger_id, 'internal'), created.uri):
                pytest.fail('A cached extraction granted access')
        await resource_delete(ResourceContext(owner_id, 'internal'), created.uri)
        assert not directory.exists()
    assert len(materializations) == 1


@pytest.mark.asyncio
async def test_deleting_a_source_stops_conversion_and_discards_late_extraction(committed_database, monkeypatch):
    async with get_db_session() as db:
        owner, _, _ = await _scope(db)
        ctx = ResourceContext(owner.id, 'internal')
        created = await resource_create(ctx, 'file://', b'Synthetic source.', name='Synthetic conversion.txt')
    entered, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    directories = []
    original = document_facade.prepare_document
    async def prepare(path, name, media_type, directory):
        directories.append(directory)
        entered.set()
        try:
            await release.wait()
            return await original(path, name, media_type, directory)
        except asyncio.CancelledError:
            stopped.set()
            raise
    monkeypatch.setattr(document_facade, 'prepare_document', prepare)
    async def read():
        async with get_db_session():
            try:
                async with prepared_resource(ctx, created.uri):
                    return 'prepared'
            except FileNotFoundError:
                return 'source-deleted'
    worker = asyncio.create_task(read())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        async with get_db_session():
            await resource_delete(ctx, created.uri)
        assert stopped.is_set()
        assert await asyncio.wait_for(worker, 5) == 'source-deleted'
        assert directories and all(not directory.exists() for directory in directories)
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_confirmed_external_delete_reports_cleanup_failure_without_inviting_replay(db, tmp_path, monkeypatch):
    from app.file_share import resource_service
    from .local_file_transport import TemporaryFileTransport
    transport = TemporaryFileTransport(tmp_path / 'provider')
    source = transport.root_path() / 'Synthetic.txt'
    source.write_text('Synthetic remote document.')
    async def console(_ctx):
        return transport
    monkeypatch.setattr(resource_service, '_console_transport', console)
    ctx = ResourceContext(0, 'internal')
    async with prepared_resource(ctx, 'console://Synthetic.txt') as (_, directory):
        assert directory.exists()
    original = document_facade._remove
    def failed_cleanup(path):
        raise OSError('Synthetic cleanup failure')
    with monkeypatch.context() as patch:
        patch.setattr(document_facade, '_remove', failed_cleanup)
        result = await resource_delete(ctx, 'console://Synthetic.txt')
    assert result.state == 'deleted' and result.indexing_status == 'failed'
    assert not source.exists()
    assert directory.exists()
    assert document_facade._remove is original
    await document_facade.purge_prepared_uri(0, 'console://Synthetic.txt')
    assert not directory.exists()


@pytest.mark.asyncio
async def test_quota_never_evicts_active_reader_and_recovers_when_it_closes(committed_database, monkeypatch):
    async with get_db_session() as db:
        owner, _, _ = await _scope(db)
        ctx = ResourceContext(owner.id, 'internal')
        first = await resource_create(ctx, 'file://', b'Synthetic first source.', name='Synthetic first.txt')
        second = await resource_create(ctx, 'file://', b'Synthetic second source.', name='Synthetic second.txt')
    monkeypatch.setattr(document_facade, 'CACHE_ENTRIES', 1)
    async with get_db_session():
        async with prepared_resource(ctx, first.uri) as (document, directory):
            with pytest.raises(ValueError, match='quota'):
                async with prepared_resource(ctx, second.uri):
                    pytest.fail('Quota allowed eviction of the active reader')
            assert directory.is_dir() and 'first source' in document.text()
        async with prepared_resource(ctx, second.uri) as (document, other):
            assert other.is_dir() and 'second source' in document.text()
            assert not directory.exists()
