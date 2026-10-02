"""Resource encounters become private lexical Memory without model calls."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import shutil

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.connection import Connection
from app.tools import ToolModel
from app.file_share import annotate_catalogue_entry, resource_service
from app.file_share import catalogue, resource_observation
from app.file_share.bridges import BRIDGES, FileShareBridge
from app.file_share.file_contracts import FileMutation
from app.file_share.models import FileCatalogEntry
from app.file_share.resource_contracts import ResourceContext
from app.file_share.tests.local_file_transport import TemporaryFileTransport
from app.memory import service
from app.memory.models import MemoryItem, MemoryLink
from app.memory.schemas import MemorySearchRequest, MemoryGraphRootsRequest, MemoryItemUpdate, MemoryPayload


class SyntheticShare(TemporaryFileTransport):
    async def resource_info(self, path, *, include_sha256=False):
        return await self.file_info(path, include_sha256=include_sha256)

    async def resource_list(self, path, *, recursive=False, limit=100):
        return await self.file_list(path, recursive=recursive, limit=limit)

    async def file_delete(self, path):
        target = self.resolve_path(path, create_parent=False)
        if target.is_dir():
            shutil.rmtree(target)
            return FileMutation(path=path, state="deleted")
        return await super().file_delete(path)

    async def file_move(self, source, destination):
        path = self.resolve_path(source, create_parent=False)
        if path.is_dir():
            target = self.resolve_path(destination)
            shutil.move(str(path), str(target))
            return FileMutation(path=destination, source=source, state="moved")
        return await super().file_move(source, destination)


@pytest_asyncio.fixture
async def console_catalogue(db, agents, memory_storage: Path, tmp_path: Path, monkeypatch):
    owner, peer = agents
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "console"))
    assert tool is not None
    tool.global_params = {**(tool.global_params or {}), "tools.fileindexing": {"value": "known_uris", "forced": False}}
    connection = Connection(agent_id=owner.id, tool_id=tool.id)
    db.add(connection)
    await db.flush()
    transport = SyntheticShare(tmp_path / "source")
    async def resolve(_ctx):
        return transport
    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    return ResourceContext(agent_id=owner.id, runtime="internal", console_resource=object()), transport, connection, peer


async def hits(agent_id, query):
    return (await service.search_items(MemorySearchRequest(agent_id=agent_id, query=query))).hits


@pytest.mark.asyncio
async def test_catalogue_content_is_editable_and_manual_changes_survive_observation(console_catalogue, db):
    ctx, _transport, _connection, peer = console_catalogue
    created = await resource_service.resource_write_text(ctx, "console://editable.txt", "source")
    hit = (await hits(ctx.agent_id, "editable"))[0]
    assert hit.item.access.can_write and not hit.item.read_only
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(hit.item.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Denied</p>")), actor_agent_id=peer.id)
    edited = await service.update_item(hit.item.id, MemoryItemUpdate(
        expected_revision=hit.item.revision, title="Personal title",
        payload=MemoryPayload(text="<p>Personally curated content</p>"), keywords=["curated"],
    ), actor_agent_id=ctx.agent_id)
    assert edited.metadata_["catalogue_manual_content"]
    assert edited.metadata_["catalogue_manual_title"]
    # A caller cannot clear ownership markers or replace the source identity.
    await service.update_item(edited.id, MemoryItemUpdate(metadata={"custom": "kept"}), actor_agent_id=ctx.agent_id)
    await resource_service.resource_write_text(ctx, created.uri, "new source bytes", overwrite=True)
    await resource_service.resource_move(ctx, created.uri, "console://renamed.txt")
    item, content, access, _type, _media = await service.get_item(edited.id, agent_id=ctx.agent_id)
    assert access.can_write and item.title == "Personal title"
    assert b"Personally curated content" in content
    assert item.keywords == ["curated"] and item.metadata_["custom"] == "kept"
    assert item.metadata_["resource_uri"] == "console://renamed.txt"
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(item.id, MemoryItemUpdate(visibility="public"), actor_agent_id=ctx.agent_id)


@pytest.mark.asyncio
async def test_existing_catalogue_fiches_become_editable_once(console_catalogue, db):
    from app.memory.dbadmin import _reconcile_catalogue_editability
    ctx, _transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://legacy.txt", "legacy")
    hit = (await hits(ctx.agent_id, "legacy"))[0]
    item = await db.get(MemoryItem, hit.item.id)
    item.read_only = True
    item.metadata_ = {key: value for key, value in item.metadata_.items() if key != "catalogue_editable"}
    await db.commit()
    await _reconcile_catalogue_editability(db)
    await db.commit()
    await db.refresh(item)
    assert not item.read_only and item.metadata_["catalogue_editable"]
    item.read_only = True  # An explicit later user choice must survive sync.
    await db.commit()
    await _reconcile_catalogue_editability(db)
    await db.commit()
    await db.refresh(item)
    assert item.read_only


@pytest.mark.asyncio
async def test_encounters_are_lexical_private_idempotent_and_notes_survive(console_catalogue, db):
    ctx, _transport, _connection, peer = console_catalogue
    written = await resource_service.resource_write_text(ctx, "console://reports/budget.csv", "a,b\n1,2")
    assert written.indexing_status == "indexed"
    found = await hits(ctx.agent_id, "budget")
    assert len(found) == 1 and found[0].item.node_kind == "file"
    identity, revision = found[0].item.id, found[0].item.revision
    assert await hits(peer.id, "budget") == []
    await resource_service.resource_info(ctx, written.uri)
    assert (await hits(ctx.agent_id, "budget"))[0].item.revision == revision
    assert await annotate_catalogue_entry(ctx, written.uri, "Annual planning") == identity
    db.add(Connection(agent_id=peer.id, tool_id=_connection.tool_id))
    await db.commit()
    peer_ctx = ResourceContext(agent_id=peer.id, runtime="internal", console_resource=object())
    await resource_service.resource_info(peer_ctx, written.uri)
    peer_found = await hits(peer.id, "budget")
    assert peer_found[0].item.id != identity
    assert await hits(peer.id, "planning") == []
    await resource_service.resource_write_text(ctx, written.uri, "a,b\n3,4", overwrite=True)
    assert (await hits(ctx.agent_id, "planning"))[0].item.id == identity
    moved = await resource_service.resource_move(ctx, written.uri, "console://reports/final.csv")
    assert moved.indexing_status == "indexed"
    found = await hits(ctx.agent_id, "planning")
    assert found[0].item.id == identity
    assert found[0].item.metadata["resource_uri"] == moved.uri
    await resource_service.resource_delete(ctx, moved.uri)
    assert await hits(ctx.agent_id, "planning") == []
    retained = await db.scalar(select(MemoryItem).where(MemoryItem.id == identity))
    assert retained is not None and "planning" in retained.search_text
    await resource_service.resource_write_text(ctx, moved.uri, "new occupant")
    replacement = await hits(ctx.agent_id, "final")
    assert replacement[0].item.id != identity
    assert await hits(ctx.agent_id, "planning") == []


@pytest.mark.asyncio
async def test_lists_are_partial_and_revocation_or_rebinding_hides_old_results(console_catalogue, db):
    ctx, transport, connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://alpha.txt", "a")
    await resource_service.resource_write_text(ctx, "console://beta.txt", "b")
    listing = await resource_service.resource_list(ctx, "console://", max_entries=1)
    assert listing.truncated
    assert await hits(ctx.agent_id, "beta")
    assert await db.scalar(select(MemoryLink.id).where(MemoryLink.projection_key == "file_catalogue"))
    connection.active = False
    await db.commit()
    assert await hits(ctx.agent_id, "beta") == []
    connection.active = True
    tool = await db.get(ToolModel, connection.tool_id)
    tool.global_params = {**tool.global_params, "account": {"value": "another-synthetic-account"}}
    await db.commit()
    assert await hits(ctx.agent_id, "beta") == []
    await resource_service.resource_info(ctx, "console://beta.txt")
    current = await hits(ctx.agent_id, "beta")
    assert current
    # Live provider access wins over a retained projection.
    transport.resolve_path("beta.txt", create_parent=False).unlink()
    assert await hits(ctx.agent_id, "beta") == []
    graph = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=ctx.agent_id))
    assert current[0].item.id not in {node.id for node in graph.nodes}
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(current[0].item.id, agent_id=ctx.agent_id)


@pytest.mark.asyncio
async def test_old_response_cannot_undo_delete_and_indexing_failure_does_not_fail_write(console_catalogue, db, monkeypatch):
    ctx, transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://old.txt", "old")
    with resource_observation.suspend_observations():
        scope = await catalogue.observation_scope(ctx, "console://old.txt")
        descriptor = await resource_service.resource_info(ctx, "console://old.txt")
    assert scope is not None
    await resource_service.resource_delete(ctx, descriptor.uri)
    await catalogue.observe_descriptors(replace(scope, started_at=scope.started_at - timedelta(seconds=1)), [descriptor])
    await db.commit()
    assert await hits(ctx.agent_id, "old") == []
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic catalogue outage")
    original = resource_observation.observe_result
    monkeypatch.setattr(resource_observation, "observe_result", fail)
    result = await resource_service.resource_write_text(ctx, "console://effect.txt", "external effect")
    assert result.indexing_status == "failed"
    from app.file_share.indexing import repair_tick
    from app.file_share.models import FileObservationRepair
    pending = await db.scalar(select(FileObservationRepair).where(FileObservationRepair.status == "pending"))
    assert pending is not None
    assert await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == result.uri)) is None
    monkeypatch.setattr(resource_observation, "observe_result", original)
    await repair_tick()
    assert pending.status == "success"
    assert transport.resolve_path("effect.txt", create_parent=False).read_text() == "external effect"
    assert await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == result.uri)) is not None


@pytest.mark.asyncio
async def test_deleting_unseen_directory_blocks_older_child_observation(console_catalogue, db):
    ctx, transport, _connection, _peer = console_catalogue
    with resource_observation.suspend_observations():
        await transport.file_write_text("unseen/child.txt", "source", overwrite=False)
        scope = await catalogue.observation_scope(ctx, "console://unseen/child.txt")
        descriptor = await resource_service.resource_info(ctx, "console://unseen/child.txt")
    assert scope is not None
    await resource_service.resource_delete(ctx, "console://unseen/")
    await catalogue.observe_descriptors(scope, [descriptor])
    await db.commit()
    assert await db.scalar(select(FileCatalogEntry.id).where(FileCatalogEntry.uri == descriptor.uri)) is None


@pytest.mark.asyncio
async def test_keyword_create_and_directory_move_preserve_notes_on_children(console_catalogue, db):
    ctx, _transport, _connection, _peer = console_catalogue
    result = await resource_service.resource_create(ctx=ctx, path="console://directory/child.txt", content=b"data")
    assert result.indexing_status == "indexed"
    identity = await annotate_catalogue_entry(ctx, result.uri, "Child note")
    await resource_service.resource_list(ctx, "console://directory/")
    moved = await resource_service.resource_move(ctx, "console://directory/", "console://renamed")
    assert moved.indexing_status == "indexed"
    found = await hits(ctx.agent_id, "Child note")
    assert found[0].item.id == identity
    assert found[0].item.metadata["resource_uri"] == "console://renamed/child.txt"


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["memory://", "document://", "galaris://task/", "https://example.org/file", "mail://attachment/a"])
async def test_excluded_resources_never_enter_catalogue(uri):
    assert await catalogue.observation_scope(ResourceContext(agent_id=1, runtime="internal"), uri) is None


@pytest.mark.asyncio
async def test_new_providers_use_common_facade_without_named_service_branches(db, agents, memory_storage, tmp_path, monkeypatch):
    owner, peer = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    for code in ("share-a", "share-b"):
        transport = SyntheticShare(tmp_path / code)
        await transport.file_write_text("specification.txt", "synthetic bytes", overwrite=False)
        monkeypatch.setitem(BRIDGES, code, FileShareBridge(service=code, label=code, params=(),
                                                        build=lambda _url, _params, transport=transport: transport))
        tool = ToolModel(code=code, label=code, file_share_config={"service": code, "base_url": "https://synthetic.invalid"},
                         global_params={"tools.fileindexing": {"value": "known_uris", "forced": False}})
        db.add(tool)
        await db.flush()
        db.add(Connection(tool_id=tool.id, agent_id=owner.id))
        await db.commit()
        result = await resource_service.resource_info(ctx, f"{code}://specification.txt")
        assert result.indexing_status == "indexed"
    found = await hits(owner.id, "specification")
    assert {hit.item.metadata["resource_uri"] for hit in found} == {"share-a://specification.txt", "share-b://specification.txt"}
    assert await hits(peer.id, "specification") == []
    async def now_messenger(*args, **kwargs):
        return object(), "messenger"
    monkeypatch.setattr(catalogue, "resolve_resource_transport_with_service", now_messenger)
    assert await hits(owner.id, "specification") == []


@pytest.mark.asyncio
async def test_tool_exclusion_and_custom_mail_or_messenger_transport_never_observe(console_catalogue, db, monkeypatch):
    ctx, _transport, connection, _peer = console_catalogue
    tool = await db.get(ToolModel, connection.tool_id)
    tool.global_params = {**(tool.global_params or {}), "tools.fileindexing": {"value": "excluded", "forced": False}}
    await db.commit()
    result = await resource_service.resource_write_text(ctx, "console://excluded.txt", "source")
    assert result.indexing_status == "excluded"
    assert await db.scalar(select(FileCatalogEntry.id)) is None
    custom = ToolModel(code="custom-mail", label="Deferred mail", file_share_config={"service": "mail", "base_url": "https://synthetic.invalid"},
                       global_params={"tools.fileindexing": {"value": "known_uris", "forced": False}})
    db.add(custom)
    await db.flush()
    db.add(Connection(agent_id=ctx.agent_id, tool_id=custom.id))
    await db.commit()
    assert await catalogue.observation_scope(ctx, "custom-mail://attachment/a") is None
    custom.file_share_config = {"service": "grav", "base_url": "https://synthetic.invalid"}
    await db.commit()
    async def messenger(*args, **kwargs):
        return object(), "messenger"
    monkeypatch.setattr(catalogue, "resolve_resource_transport_with_service", messenger)
    assert await catalogue.observation_scope(ctx, "custom-mail://room/attachment") is None
    assert await db.scalar(select(FileCatalogEntry.id)) is None


@pytest_asyncio.fixture
async def recursive_catalogue(db, agents, memory_storage, tmp_path, monkeypatch):
    from app.file_share.file_contracts import FileListing
    owner, peer = agents
    class PagedShare(SyntheticShare):
        async def resource_list_page(self, path, *, recursive=False, limit=500, cursor=None):
            listing = await self.file_list(path, recursive=recursive, limit=10000)
            offset = int(cursor or 0)
            page = listing.entries[offset:offset + limit]
            more = offset + len(page) < len(listing.entries)
            return FileListing(path=listing.path, entries=page, truncated=more,
                next_cursor=str(offset + len(page)) if more else None)
        async def resource_list(self, path, *, recursive=False, limit=500):
            return await self.resource_list_page(path, recursive=recursive, limit=limit)
    transport = PagedShare(tmp_path / 'recursive')
    monkeypatch.setitem(BRIDGES, 'scan-test', FileShareBridge(service='scan-test', label='Synthetic share', params=(),
        build=lambda _url, _params: transport, indexing_modes=('excluded', 'known_uris', 'recursive')))
    tool = ToolModel(code='scan-test', label='Synthetic share', file_share_config={'service': 'scan-test', 'base_url': 'https://synthetic.invalid'}, global_params={"tools.fileindexing": {"value": "recursive", "forced": False}})
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id)
    db.add(connection)
    await db.commit()
    return ResourceContext(agent_id=owner.id, runtime='internal'), transport, connection, peer


@pytest.mark.asyncio
async def test_connection_indexing_override_and_forced_global_control_catalogue_access(console_catalogue, db):
    from app.connection import connection_service
    from app.tools import tool_service
    from app.tools.schemas import ToolGlobalParamsUpdate
    ctx, transport, connection, peer = console_catalogue
    await transport.file_write_text('override.txt', 'synthetic content', overwrite=False)
    other = Connection(agent_id=peer.id, tool_id=connection.tool_id)
    db.add(other)
    await db.flush()
    await connection_service.set_params_bulk(connection.id, {'tools.fileindexing': 'excluded'})
    excluded = await resource_service.resource_info(ctx, 'console://override.txt')
    assert excluded.indexing_status == 'excluded'
    peer_ctx = replace(ctx, agent_id=peer.id)
    assert (await resource_service.resource_info(peer_ctx, 'console://override.txt')).indexing_status == 'indexed'
    assert await hits(ctx.agent_id, 'override') == []
    assert len(await hits(peer.id, 'override')) == 1
    await tool_service.update_global_params(connection.tool_id, ToolGlobalParamsUpdate.model_validate({
        'params': {'tools.fileindexing': {'value': 'known_uris', 'forced': True}},
    }))
    assert (await resource_service.resource_info(ctx, 'console://override.txt')).indexing_status == 'indexed'
    assert len(await hits(ctx.agent_id, 'override')) == 1
    await tool_service.update_global_params(connection.tool_id, ToolGlobalParamsUpdate.model_validate({
        'params': {'tools.fileindexing': {'value': 'excluded', 'forced': True}},
    }))
    assert await hits(ctx.agent_id, 'override') == []
    assert await hits(peer.id, 'override') == []


@pytest.mark.asyncio
async def test_automatic_indexing_selection_respects_local_overrides(recursive_catalogue, db):
    from app.connection import connection_service
    from app.file_share.indexing import schedule_automatic_runs, start_index_run, process_index_page
    from app.file_share.models import FileIndexRun
    ctx, transport, connection, _peer = recursive_catalogue
    await connection_service.set_params_bulk(connection.id, {'tools.fileindexing': 'excluded'})
    await schedule_automatic_runs()
    assert list(await db.scalars(select(FileIndexRun))) == []
    with pytest.raises(PermissionError):
        await start_index_run(ctx, 'scan-test://')
    await connection_service.set_params_bulk(connection.id, {'tools.fileindexing': 'known_uris'})
    with pytest.raises(PermissionError, match='automatic traversal'):
        await start_index_run(ctx, 'scan-test://')
    await connection_service.set_params_bulk(connection.id, {'tools.fileindexing': 'recursive'})
    await schedule_automatic_runs()
    run = await db.scalar(select(FileIndexRun))
    assert run is not None and run.connection_id == connection.id
    await connection_service.set_params_bulk(connection.id, {'tools.fileindexing': 'excluded'})
    await process_index_page(run)
    assert run.status == 'excluded'


@pytest.mark.asyncio
async def test_recursive_pages_resume_reconcile_and_preserve_recent_observations(recursive_catalogue, db):
    from app.file_share.indexing import start_index_run, indexing_tick
    from app.file_share.models import FileIndexRun
    ctx, transport, connection, peer = recursive_catalogue
    for i in range(503):
        await transport.file_write_text(f'data/item-{i:04d}.txt', 'synthetic', overwrite=False)
    await resource_service.resource_info(ctx, 'scan-test://data/item-0000.txt')
    transport.resolve_path('data/item-0000.txt').unlink()
    run = await start_index_run(ctx, 'scan-test://data/')
    assert (await start_index_run(ctx, 'scan-test://data/')).id == run.id
    await db.commit()
    await indexing_tick()
    await db.refresh(run)
    assert run.status == 'running' and run.scanned == 500
    assert run.frontier[0]['cursor']
    # A concurrent observation after the scan start is not proof of absence.
    await resource_service.resource_write_text(ctx, 'scan-test://data/recent.txt', 'new')
    for _ in range(6):
        await indexing_tick()
        await db.refresh(run)
        if run.status == 'success':
            break
    assert run.status == 'success' and run.scanned == 503
    old = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'scan-test://data/item-0000.txt'))
    assert old is not None and not old.present
    assert await hits(peer.id, 'item') == []
    assert len(list(await db.scalars(select(FileIndexRun).where(FileIndexRun.root_uri == 'scan-test://data/')))) == 1


@pytest.mark.asyncio
async def test_partial_scan_and_cancel_never_remove_unseen_sources(recursive_catalogue, db):
    from app.file_share.indexing import start_index_run, indexing_tick, cancel_index_run
    ctx, transport, connection, peer = recursive_catalogue
    for i in range(3):
        await resource_service.resource_write_text(ctx, f'scan-test://folder/{i}.txt', 'synthetic')
    run = await start_index_run(ctx, 'scan-test://folder/', max_entries=1)
    await db.commit()
    for _ in range(6):
        await indexing_tick()
        await db.refresh(run)
        if run.status == 'partial':
            break
    assert run.status == 'partial'
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))
    later = await start_index_run(ctx, 'scan-test://folder/')
    assert not await cancel_index_run(later.id, peer.id)
    assert await cancel_index_run(later.id, ctx.agent_id)
    await db.commit()
    await indexing_tick()
    assert later.status == 'cancelled'


@pytest.mark.asyncio
async def test_explicit_resource_acquisition_reuses_catalogue_fiche(console_catalogue, db):
    from app.file_share.resource_description import record_resource_description
    from app.file_share.enrichment import FileCatalogueEnrichmentPort
    ctx, _, _, _ = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://acquired.txt', 'Synthetic source')
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://acquired.txt'))
    item_id = await record_resource_description(ctx, entry.uri, 'Synthetic acquired description')
    assert item_id == entry.memory_item_id
    _, body, _, _, _ = await service.get_item(item_id, agent_id=ctx.agent_id)
    assert b'Synthetic acquired description' in body
    assert not await FileCatalogueEnrichmentPort().candidates()
    assert not await db.scalar(select(MemoryItem.id).where(MemoryItem.managed_source_kind == 'image_description'))


@pytest.mark.asyncio
async def test_versioned_enrichment_does_not_overwrite_personal_content(console_catalogue, db):
    from app.file_share.enrichment import apply_enrichment, descriptor_version, FileCatalogueEnrichmentPort
    ctx, transport, connection, peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://analysis.txt', 'Source version one')
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://analysis.txt'))
    version = descriptor_version(entry.descriptor)
    assert await apply_enrichment(entry.id, version, 'Synthetic generated conclusion')
    assert not await apply_enrichment(entry.id, version, 'Duplicate inference')
    item, body, access, _, _ = await service.get_item(entry.memory_item_id, agent_id=ctx.agent_id)
    assert b'Synthetic generated conclusion' in body
    await service.update_item(item.id, MemoryItemUpdate(payload=MemoryPayload(text='<p>Personal text</p>')), actor_agent_id=ctx.agent_id)
    await resource_service.resource_write_text(ctx, 'console://analysis.txt', 'Source version two with a different size', overwrite=True)
    assert not await apply_enrichment(entry.id, version, 'Stale inference')
    candidates = await FileCatalogueEnrichmentPort().candidates()
    current = next(source for source in candidates if source['identity'] == str(entry.id))
    assert await apply_enrichment(entry.id, current['version'], 'Updated generated conclusion')
    _, body, _, _, _ = await service.get_item(item.id, agent_id=ctx.agent_id)
    assert b'Personal text' in body and b'Updated generated conclusion' not in body
    tool = await db.get(ToolModel, connection.tool_id)
    tool.global_params = {**tool.global_params, 'tools.fileindexing': {'value': 'excluded', 'forced': False}}
    await db.commit()
    assert not await FileCatalogueEnrichmentPort().candidates()


@pytest.mark.asyncio
async def test_known_uri_refresh_detects_external_updates_and_proven_deletion(console_catalogue, db):
    from app.file_share.indexing import refresh_known_tick
    ctx, transport, connection, peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://refresh.txt', 'old')
    transport.resolve_path('refresh.txt').write_text('A longer externally changed synthetic source')
    await refresh_known_tick()
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://refresh.txt'))
    assert entry.descriptor['size'] > 3
    transport.resolve_path('refresh.txt').unlink()
    entry.checked_at = None
    await db.commit()
    await refresh_known_tick()
    assert not entry.present


@pytest.mark.asyncio
async def test_indexing_http_requires_memory_privileges(client):
    path = '/api/file-share/indexing'
    assert (await client.get(path, params={'agent_id': 1})).status_code == 401
    credentials = {'email': 'catalogue-admin@example.com', 'password': 'synthetic-catalogue-password'}
    assert (await client.post('/api/auth/register', json=credentials)).status_code == 201
    login = await client.post('/api/auth/login-json', json=credentials)
    admin = {'Authorization': f"Bearer {login.json()['access_token']}"}
    agents = (await client.get('/api/agents/selection', headers=admin)).json()
    assert agents
    agent_id = agents[0]['id']
    response = await client.get(path, params={'agent_id': agent_id, 'page_size': 500}, headers=admin)
    assert response.status_code == 200 and response.json()['runs'] == []
    assert (await client.post(path + '/repairs/retry', headers=admin, params={'agent_id': agent_id})).json() == {'retried': 0}
    assert (await client.post(path, headers=admin, json={'agent_id': agent_id, 'root_uri': 'document://'})).status_code == 403
    reader = {'email': 'catalogue-reader@example.com', 'password': 'synthetic-catalogue-reader-password'}
    assert (await client.post('/api/auth/users', headers=admin, json=reader)).status_code == 201
    login = await client.post('/api/auth/login-json', json=reader)
    denied = {'Authorization': f"Bearer {login.json()['access_token']}"}
    assert (await client.get(path, params={'agent_id': agent_id}, headers=denied)).status_code == 403
    assert (await client.post(path, headers=denied, json={'agent_id': agent_id, 'root_uri': 'scan-test://'})).status_code == 403
    assert (await client.post(path + '/repairs/retry', headers=denied, params={'agent_id': agent_id})).status_code == 403


@pytest.mark.asyncio
async def test_provider_revision_conflict_restarts_cursor_with_backoff(recursive_catalogue, db, monkeypatch):
    from app.file_share.indexing import start_index_run, indexing_tick, now
    from app.file_share import ResourceRevisionConflict
    ctx, transport, connection, peer = recursive_catalogue
    await resource_service.resource_write_text(ctx, 'scan-test://retry/item.txt', 'synthetic')
    run = await start_index_run(ctx, 'scan-test://retry/')
    run.frontier = [{'uri': run.root_uri, 'cursor': 'old-cursor', 'depth': 0}]
    await db.commit()
    original = transport.resource_list_page
    async def conflicted(path, **kwargs):
        if path.strip('/') == 'retry':
            raise ResourceRevisionConflict('Synthetic revision change')
        return await original(path, **kwargs)
    monkeypatch.setattr(transport, 'resource_list_page', conflicted)
    await indexing_tick()
    await db.refresh(run)
    assert run.status == 'retry' and run.attempts == 1 and run.next_attempt_at > now()
    assert run.frontier[0]['cursor'] is None
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))
    monkeypatch.setattr(transport, 'resource_list_page', original)
    run.next_attempt_at = now() - timedelta(seconds=1)
    await db.commit()
    for _ in range(6):
        await indexing_tick()
        await db.refresh(run)
        if run.status == 'success':
            break
    assert run.status == 'success' and run.scanned == 1
    assert run.error_type is None


@pytest.mark.asyncio
async def test_dream_file_version_is_acquired_once_and_new_version_is_eligible(console_catalogue, db, monkeypatch):
    from app.dream import interface
    from app.dream.mechanisms import file_catalogue as mechanism_module
    from app.dream.service import mark_success
    from app.file_share import FileCatalogueEnrichmentPort
    from core.params import runtime_settings
    ctx, transport, connection, peer = console_catalogue
    monkeypatch.setattr(interface, '_file_catalogue', FileCatalogueEnrichmentPort())
    monkeypatch.setattr(runtime_settings, 'DREAM_ATTACHMENT_TEXT_ENABLED', True)
    invocations = []
    async def analyze(kind, path, source):
        invocations.append(path.read_text())
        return 'Synthetic acquired summary'
    monkeypatch.setattr(mechanism_module, 'analyze_attachment', analyze)
    await resource_service.resource_write_text(ctx, 'console://dream-version.txt', 'Original synthetic text')
    mechanism = mechanism_module.file_catalogue_mechanism
    claim = await mechanism.claim_one()
    assert claim is not None
    prepared = await mechanism.prepare(claim)
    assert await mechanism.apply(claim, prepared.payload) == 1
    await mark_success(claim, result_count=1)
    assert await mechanism.claim_one() is None
    assert invocations == ['Original synthetic text']
    await resource_service.resource_write_text(ctx, 'console://dream-version.txt', 'Changed source with a different size', overwrite=True)
    assert await mechanism.claim_one() is not None


@pytest.mark.asyncio
async def test_unsupported_dream_candidates_do_not_starve_later_files(console_catalogue, db, monkeypatch):
    from app.dream import interface
    from app.dream.mechanisms.file_catalogue import file_catalogue_mechanism
    from app.file_share import FileCatalogueEnrichmentPort
    from core.params import runtime_settings
    ctx, transport, connection, peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://unsupported.bin', 'Synthetic binary metadata')
    await resource_service.resource_write_text(ctx, 'console://eligible.txt', 'Synthetic text')
    port = FileCatalogueEnrichmentPort()
    original = port.candidates
    # Shrink the same bounded window to reproduce starvation with two sources.
    async def one_candidate():
        return (await original())[:1]
    monkeypatch.setattr(port, 'candidates', one_candidate)
    monkeypatch.setattr(interface, '_file_catalogue', port)
    monkeypatch.setattr(runtime_settings, 'DREAM_ATTACHMENT_TEXT_ENABLED', True)
    assert await file_catalogue_mechanism.claim_one() is None
    claim = await file_catalogue_mechanism.claim_one()
    assert claim is not None and claim.prepared_payload['uri'] == 'console://eligible.txt'


@pytest.mark.parametrize(('mime', 'name', 'kinds'), [
    ('application/pdf', 'scan.pdf', ('text', 'document')),
    ('text/plain', 'notes.txt', ('text',)),
    ('image/png', 'picture.png', ('image',)),
    ('audio/ogg', 'audio.ogg', ('video',)),
    ('application/octet-stream', 'unknown.bin', ()),
])
def test_file_media_pipeline_has_document_fallback_without_arbitrary_binary_inference(mime, name, kinds):
    from app.dream.mechanisms.file_catalogue import media_kinds
    assert media_kinds({'media_type': mime, 'name': name}) == kinds


@pytest.mark.asyncio
async def test_wide_directory_tree_keeps_a_bounded_checkpoint(recursive_catalogue, db):
    from app.file_share.indexing import start_index_run, indexing_tick
    ctx, transport, connection, peer = recursive_catalogue
    transport.resolve_path('wide/000-new').mkdir()
    frames = [{'uri': 'scan-test://wide/', 'cursor': None, 'depth': 0}]
    for index in range(4095):
        path = f'wide/existing-{index:04d}'
        transport.resolve_path(path).mkdir()
        frames.append({'uri': f'scan-test://{path}/', 'cursor': None, 'depth': 1})
    run = await start_index_run(ctx, 'scan-test://wide/')
    run.frontier = frames
    await db.commit()
    await indexing_tick()
    await db.refresh(run)
    assert len(run.frontier) <= 4096
    assert run.error_type == 'FrontierLimit'
    assert run.status != 'success'
