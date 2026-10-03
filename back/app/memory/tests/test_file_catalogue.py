"""Resource encounters become private lexical Memory without model calls."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
        if not path:
            return replace(self._entry(self.root_path(), include_sha256=include_sha256), path='')
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
    import app.console
    from app.console import ConsoleRunResource
    from app.console.contracts import SshConnectionConfig
    owner, peer = agents
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "console"))
    assert tool is not None
    connection = Connection(agent_id=owner.id, tool_id=tool.id)
    db.add(connection)
    await db.flush()
    connection_id = connection.id
    transport = SyntheticShare(tmp_path / "source")
    async def build(_agent_id):
        resource = ConsoleRunResource(SshConnectionConfig(connection_id=connection_id,
            host="synthetic.invalid", username="synthetic", private_key="synthetic", known_host_key="synthetic"))
        resource.files = transport
        return resource
    monkeypatch.setattr(app.console, "build_run_resource", build)
    return ResourceContext(agent_id=owner.id, runtime="internal", console_resource=object()), transport, connection, peer


async def hits(agent_id, query):
    return (await service.search_items(MemorySearchRequest(agent_id=agent_id, query=query))).hits


async def acquire_fingerprints(db):
    from app.file_share import FileCatalogueEnrichmentPort
    port = FileCatalogueEnrichmentPort()
    for source in await port.fingerprints():
        digest = await port.fingerprint(source)
        assert digest is not None
        assert await port.identify(source['identity'], source['version'], digest)
        await db.commit()
    return port


@pytest.mark.asyncio
async def test_graph_checks_live_files_with_one_closed_console_per_page(console_catalogue, monkeypatch):
    from app.console import ConsoleRunResource
    from app.console.contracts import SshConnectionConfig
    import app.console

    ctx, transport, connection, peer = console_catalogue
    for index in range(12):
        await resource_service.resource_write_text(ctx, f"console://graph/file-{index}.txt", f"Synthetic {index}")
    transport.resolve_path("graph/file-3.txt", create_parent=False).unlink()
    opened, closed = [], []

    async def build(_agent_id):
        resource = ConsoleRunResource(SshConnectionConfig(connection_id=connection.id,
            host="synthetic.invalid", username="synthetic", private_key="synthetic", known_host_key="synthetic"))
        resource.files = transport
        opened.append(resource)
        return resource

    async def close(resource):
        closed.append(resource)

    monkeypatch.setattr(app.console, "build_run_resource", build)
    monkeypatch.setattr(ConsoleRunResource, "close", close)
    request = MemoryGraphRootsRequest(agent_id=ctx.agent_id, limit=100)
    for page_index in range(2):
        page = await service.list_graph_roots(request)
        titles = {node.title for node in page.nodes}
        assert "file-3.txt" not in titles
        assert all(f"file-{index}.txt" in titles for index in range(12) if index != 3)
        assert len(opened) == page_index + 1
        assert closed == opened
    assert not (await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=peer.id))).nodes
    connection.active = False
    from core.database import get_db
    await get_db().commit()
    assert not (await service.list_graph_roots(request)).nodes
    assert len(opened) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["cancel", "revoke", "rebind"])
async def test_graph_closes_console_and_hides_changed_bindings(console_catalogue, db, monkeypatch, interruption):
    import asyncio
    from app.console import ConsoleRunResource
    ctx, _transport, connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, "console://graph/synthetic.txt", "Synthetic content")
    original = resource_service.resource_info
    closed = []
    async def close(resource):
        closed.append(resource)
    async def interrupt(*args, **kwargs):
        if interruption == "cancel":
            raise asyncio.CancelledError()
        descriptor = await original(*args, **kwargs)
        if interruption == "revoke":
            connection.active = False
        else:
            tool = await db.get(ToolModel, connection.tool_id)
            tool.global_params = {**tool.global_params, "account": {"value": "synthetic-new-binding"}}
        await db.flush()
        return descriptor
    monkeypatch.setattr(ConsoleRunResource, "close", close)
    monkeypatch.setattr(resource_service, "resource_info", interrupt)
    request = MemoryGraphRootsRequest(agent_id=ctx.agent_id)
    if interruption == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await service.list_graph_roots(request)
    else:
        assert not (await service.list_graph_roots(request)).nodes
    assert len(closed) == 1


@pytest.mark.asyncio
async def test_content_identity_unifies_locations_summary_and_graph_per_agent(console_catalogue, db, tmp_path, monkeypatch):
    import hashlib
    from app.file_share import apply_enrichment, FileCatalogueEnrichmentPort
    from app.file_share.catalogue_resources import resources, thumbnail, content
    from app.memory.models import MemorySource
    ctx, console, connection, peer = console_catalogue
    mirror = SyntheticShare(tmp_path / 'mirror')
    monkeypatch.setitem(BRIDGES, 'mirror-test', FileShareBridge(service='mirror-test', label='Mirror', params=(),
        build=lambda _url, _params: mirror))
    tool = ToolModel(code='mirror-test', label='Mirror', file_share_config={'service': 'mirror-test', 'base_url': 'https://synthetic.invalid'},
        global_params={'tools.fileindexing': {'value': 'known_uris', 'forced': False}})
    db.add(tool)
    await db.flush()
    db.add_all([Connection(tool_id=tool.id, agent_id=ctx.agent_id), Connection(tool_id=connection.tool_id, agent_id=peer.id)])
    await db.commit()
    data = 'Synthetic identical file bytes'
    await resource_service.resource_write_text(ctx, 'console://first/report.txt', data)
    await mirror.file_write_text('second/report-copy.txt', data, overwrite=False)
    await resource_service.resource_list(ctx, 'console://first/')
    await resource_service.resource_list(ctx, 'mirror-test://second/')
    before = list(await db.scalars(select(FileCatalogEntry).where(FileCatalogEntry.descriptor['is_collection'].as_boolean().is_(False))))
    duplicate_item = before[1].memory_item_id
    await service.update_item(duplicate_item, MemoryItemUpdate(title='Synthetic personal title', payload=MemoryPayload(text='<p>Synthetic personal note</p>')),
        actor_agent_id=ctx.agent_id)
    await acquire_fingerprints(db)
    entries = list(await db.scalars(select(FileCatalogEntry).where(FileCatalogEntry.descriptor['is_collection'].as_boolean().is_(False)).execution_options(populate_existing=True)))
    assert len({entry.memory_item_id for entry in entries}) == 1
    canonical = await db.get(MemoryItem, entries[0].memory_item_id)
    await db.refresh(canonical)
    assert canonical.file_sha256 == hashlib.sha256(data.encode()).hexdigest()
    assert canonical.title == 'Synthetic personal title'
    assert len(list(await db.scalars(select(MemoryItem).where(MemoryItem.node_kind == 'file')))) == 1
    assert len(list(await db.scalars(select(MemoryLink).where(MemoryLink.target_item_id == canonical.id)))) == 2
    assert {row.source_ref for row in await db.scalars(select(MemorySource).where(MemorySource.item_id == canonical.id))} == {entry.uri for entry in entries}
    assert (await service.get_item(canonical.id, agent_id=ctx.agent_id))[1].find(b'Synthetic personal note') >= 0
    assert await apply_enrichment(entries[0].id, entries[0].source_version, 'One shared synthetic summary')
    await db.commit()
    assert not await apply_enrichment(entries[1].id, entries[1].source_version, 'Should not replace the common summary')
    assert await FileCatalogueEnrichmentPort().candidates() == []
    locations = await resources(canonical.id, ctx.agent_id)
    assert {location.uri for location in locations} == {entry.uri for entry in entries}
    assert await resources(canonical.id, peer.id) == []
    with pytest.raises(PermissionError):
        async with content(canonical.id, peer.id, entries[0].id, preview=False):
            pass
    assert await thumbnail(canonical.id, ctx.agent_id, entries[0].id)
    async with content(canonical.id, ctx.agent_id, entries[0].id, preview=True) as source:
        assert source.path.read_text() == data
        path = source.path
    assert not path.exists()
    await resource_service.resource_info(ResourceContext(agent_id=peer.id, runtime='internal'), 'console://first/report.txt')
    await acquire_fingerprints(db)
    peer_entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.agent_id == peer.id))
    assert peer_entry.memory_item_id != canonical.id
    assert (await db.get(MemoryItem, peer_entry.memory_item_id)).file_sha256 == canonical.file_sha256
    await resource_service.resource_write_text(ctx, entries[0].uri, 'Changed only this location', overwrite=True)
    await acquire_fingerprints(db)
    await db.refresh(entries[0])
    await db.refresh(entries[1])
    assert entries[0].memory_item_id != entries[1].memory_item_id
    assert entries[1].memory_item_id == canonical.id
    await db.refresh(canonical)
    assert canonical.metadata_['file_summary'] == 'One shared synthetic summary'
    assert canonical.metadata_['resource_uris'] == [entries[1].uri]
    assert entries[0].uri not in canonical.search_text.splitlines()
    await resource_service.resource_delete(ctx, entries[0].uri)
    assert len(await resources(canonical.id, ctx.agent_id)) == 1


@pytest.mark.asyncio
async def test_shared_summary_has_a_revision_and_survives_a_hashed_file_move(console_catalogue, db):
    from app.file_share import apply_enrichment
    from app.file_share.catalogue_resources import content
    from app.memory.models import MemoryRevision

    ctx, transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://before/file.txt', 'Synthetic original bytes')
    await resource_service.resource_list(ctx, 'console://before/')
    await transport.file_write_text('after/placeholder.txt', 'Different bytes', overwrite=False)
    await resource_service.resource_info(ctx, 'console://after/')
    await acquire_fingerprints(db)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://before/file.txt'))
    identity = entry.memory_item_id
    assert await apply_enrichment(entry.id, entry.source_version, 'Synthetic shared summary')
    await db.commit()
    item = await db.get(MemoryItem, identity)
    revision = await db.scalar(select(MemoryRevision).where(MemoryRevision.item_id == identity, MemoryRevision.revision == item.revision))
    assert revision is not None and revision.resource_id == item.resource_id
    await resource_service.resource_move(ctx, entry.uri, 'console://after/file.txt')
    await db.refresh(entry)
    assert entry.memory_item_id == identity
    links = list(await db.scalars(select(MemoryLink).where(MemoryLink.target_item_id == identity, MemoryLink.relation_type == 'parent_of')))
    parent = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://after/'))
    assert [link.source_item_id for link in links] == [parent.memory_item_id]
    async with content(identity, ctx.agent_id, entry.id, preview=False) as source:
        assert source.path.read_text() == 'Synthetic original bytes'


@pytest.mark.asyncio
async def test_catalogue_preview_rechecks_revocation_after_thumbnail_render(console_catalogue, db, monkeypatch):
    from app.file_share import catalogue_resources

    ctx, _transport, connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://preview.txt', 'Synthetic preview bytes')
    await acquire_fingerprints(db)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://preview.txt'))
    async def revoke(_path, _name, _media_type):
        connection.active = False
        await db.flush()
        return b'Synthetic thumbnail that must not be served'
    monkeypatch.setattr(catalogue_resources, 'render_file_thumbnail', revoke)
    with pytest.raises(PermissionError):
        await catalogue_resources.thumbnail(entry.memory_item_id, ctx.agent_id, entry.id)
    assert await catalogue_resources.resources(entry.memory_item_id, ctx.agent_id) == []


@pytest.mark.asyncio
async def test_preview_rejects_changed_bytes_even_with_unchanged_metadata(console_catalogue, db):
    import os
    from app.file_share.catalogue_resources import content

    ctx, transport, _connection, _peer = console_catalogue
    await resource_service.resource_write_text(ctx, 'console://preview.txt', 'Original bytes')
    await acquire_fingerprints(db)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'console://preview.txt'))
    path = transport.resolve_path('preview.txt')
    timestamp = path.stat()
    path.write_text('Replaced bytes')
    os.utime(path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    with pytest.raises(PermissionError):
        async with content(entry.memory_item_id, ctx.agent_id, entry.id, preview=False):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize('size', [0, 33 * 1024 * 1024])
async def test_fingerprint_covers_complete_binary_and_empty_files_beyond_analysis_budget(console_catalogue, db, size):
    import hashlib
    ctx, transport, connection, peer = console_catalogue
    path = transport.resolve_path('binary.dat')
    with path.open('wb') as source:
        source.truncate(size)
    await resource_service.resource_info(ctx, 'console://binary.dat')
    await acquire_fingerprints(db)
    item = await db.scalar(select(MemoryItem).where(MemoryItem.node_kind == 'file'))
    with path.open('rb') as source:
        assert item.file_sha256 == hashlib.file_digest(source, 'sha256').hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize('projection_failure', [False, True])
async def test_received_messenger_copy_unifies_with_file_provider_and_repairs_metadata(console_catalogue, db, monkeypatch, projection_failure):
    from types import SimpleNamespace
    from app.file_share import indexing
    from app.file_share.models import FileObservationRepair
    from app.messenger import facade, journal
    from app.messenger._observations import ObservedMessengerMessage, ObservedMessengerRoom, ObservedMessengerUser, ObservedMessengerFile
    from app.messenger.models import File

    ctx, _transport, _connection, _peer = console_catalogue
    data = b'Synthetic shared Messenger file'
    await resource_service.resource_write_text(ctx, 'console://shared.txt', data.decode())
    tool = ToolModel(code='synthetic-talk', label='Synthetic Talk', messenger_config={'service': 'telegram'})
    db.add(tool)
    await db.flush()
    connection = Connection(agent_id=ctx.agent_id, tool_id=tool.id)
    db.add(connection)
    await db.flush()
    message = ObservedMessengerMessage(id='synthetic-message', tool_id=tool.id, platform='telegram', time=100,
        sender=ObservedMessengerUser(id='synthetic-sender', connection_id=connection.id), room=ObservedMessengerRoom(id='synthetic-room'),
        attachments=[ObservedMessengerFile(id='synthetic-provider-file', name='shared-copy.txt', mime='text/plain', size=len(data))])
    original_projection = resource_observation.observe_descriptors
    if projection_failure:
        async def unavailable(*_args):
            raise RuntimeError('Synthetic projection failure')
        monkeypatch.setattr(resource_observation, 'observe_descriptors', unavailable)
    assert await journal.record(message, connection_id=connection.id, platform='telegram', direction='inbound', status='received')
    await db.commit()
    if projection_failure:
        pending = await db.scalar(select(FileObservationRepair).where(FileObservationRepair.connection_id == connection.id))
        assert pending is not None and pending.status == 'pending'
        monkeypatch.setattr(resource_observation, 'observe_descriptors', original_projection)
        await indexing.repair_tick()
        await db.refresh(pending)
        assert pending.status == 'success'
    assert not await journal.record(message, connection_id=connection.id, platform='telegram', direction='inbound', status='received')
    await db.commit()
    stored = await db.scalar(select(File).where(File.connection_id == connection.id))
    async def fetch(attachment, destination, *, max_bytes):
        assert attachment.local_id == stored.id and max_bytes >= len(data)
        destination.write_bytes(data)
        return len(data)
    async def history(*_args):
        pytest.fail('A stored attachment must remain readable beyond the recent-history window')
    delegate = SimpleNamespace(tool_id=tool.id, tool_code=tool.code, fetch_attachment_to_file=fetch, history=history)
    messenger = facade.MessengerFacade(delegate, connection.id)
    async def resolve(_agent_id, identity):
        assert identity == connection.id
        return messenger
    monkeypatch.setattr('app.messenger.messenger_for_agent_connection', resolve)
    await acquire_fingerprints(db)
    entries = list(await db.scalars(select(FileCatalogEntry).where(FileCatalogEntry.descriptor['is_collection'].as_boolean().is_(False)).execution_options(populate_existing=True)))
    assert len(entries) == 2 and len({entry.memory_item_id for entry in entries}) == 1
    assert {entry.uri for entry in entries} == {'console://shared.txt', f'synthetic-talk://synthetic-room/{stored.id}'}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "search"])
async def test_discovery_creates_memory_by_default(console_catalogue, db, operation):
    from app.file_share import FileCatalogueEnrichmentPort

    ctx, transport, _connection, peer = console_catalogue
    await transport.file_write_text("discovered/reports.txt", "Synthetic file content", overwrite=False)
    assert await db.scalar(select(FileCatalogEntry.id)) is None
    if operation == "list":
        await resource_service.resource_list(ctx, "console://", recursive=True)
    else:
        await resource_service.resource_search(ctx, "console://", "discovered")
    found = await hits(ctx.agent_id, "discovered")
    assert {(hit.item.node_kind, hit.item.metadata["resource_uri"]) for hit in found} == {
        ("directory", "console://discovered/"),
        ("file", "console://discovered/reports.txt"),
    }
    identities = {hit.item.id for hit in found}
    await resource_service.resource_search(ctx, "console://", "discovered")
    assert {hit.item.id for hit in await hits(ctx.agent_id, "discovered")} == identities
    assert await hits(peer.id, "discovered") == []
    assert {source["uri"] for source in await FileCatalogueEnrichmentPort().candidates()} == {
        "console://discovered/reports.txt",
    }


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
    assert len(await hits(owner.id, "specification")) == 2  # Messenger is now a supported file facade.


@pytest.mark.asyncio
async def test_tool_exclusion_and_mail_are_preserved_but_messenger_is_observed(console_catalogue, db, monkeypatch):
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
    assert await catalogue.observation_scope(ctx, "custom-mail://room/attachment") is not None
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
    hash_claim = await mechanism.claim_one()
    assert hash_claim.subject_kind == 'file_fingerprint'
    prepared = await mechanism.prepare(hash_claim)
    assert await mechanism.apply(hash_claim, prepared.payload) == 1
    await mark_success(hash_claim, result_count=1)
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
    from app.dream.service import mark_success
    for _ in range(2):
        hash_claim = await file_catalogue_mechanism.claim_one()
        assert hash_claim.subject_kind == 'file_fingerprint'
        prepared = await file_catalogue_mechanism.prepare(hash_claim)
        assert await file_catalogue_mechanism.apply(hash_claim, prepared.payload) == 1
        await mark_success(hash_claim, result_count=1)
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


@pytest_asyncio.fixture
async def catalogue_dream(recursive_catalogue, monkeypatch):
    from app.dream import interface, registry, scheduler
    from app.dream.mechanisms.file_catalogue import file_catalogue_mechanism
    from app.file_share import FileCatalogueEnrichmentPort
    from core.params import runtime_settings
    from collections import OrderedDict

    monkeypatch.setattr(interface, '_file_catalogue', FileCatalogueEnrichmentPort())
    monkeypatch.setattr(registry, '_mechanisms', OrderedDict([(file_catalogue_mechanism.key, file_catalogue_mechanism)]))
    monkeypatch.setattr(scheduler, '_stopping', False)
    monkeypatch.setattr(scheduler, '_next_mechanism_index', 0)
    monkeypatch.setattr(scheduler, 'has_active_voice_calls', lambda: False)
    async def idle():
        return False
    monkeypatch.setattr(scheduler, 'has_active_task_work', idle)
    monkeypatch.setattr(runtime_settings, 'DREAM_ENABLED', True)
    monkeypatch.setattr(runtime_settings, 'DREAM_FILE_RESCAN_SCHEDULE', 'weekly_midnight')
    for kind in ('TEXT', 'DOCUMENT', 'IMAGE', 'VIDEO'):
        monkeypatch.setattr(runtime_settings, f'DREAM_ATTACHMENT_{kind}_ENABLED', False)
    async def unexpected_model(*args, **kwargs):
        pytest.fail('Directory discovery must not invoke an attachment model')
    monkeypatch.setattr('app.dream.mechanisms.file_catalogue.analyze_attachment', unexpected_model)
    return recursive_catalogue, scheduler, file_catalogue_mechanism


@pytest.mark.asyncio
async def test_dream_discovers_directory_per_idle_turn_with_receipts_and_gauges(catalogue_dream, db, monkeypatch):
    from app.dream.models import DreamReceipt
    from app.dream.monitoring_service import _receipt_summary
    from app.file_share.models import FileIndexRun
    from app.llm import LLMCall
    from sqlalchemy import func
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    await transport.file_write_text('parent/child/report.txt', 'synthetic', overwrite=False)
    await transport.file_write_text('sibling/note.txt', 'synthetic', overwrite=False)
    assert await mechanism.count_pending() == 1
    baseline_calls = await db.scalar(select(func.count()).select_from(LLMCall))
    async def busy():
        return True
    with monkeypatch.context() as patch:
        patch.setattr(scheduler, 'has_active_task_work', busy)
        assert await scheduler.run_cycle() == 0
    assert await db.scalar(select(FileIndexRun.id)) is None
    assert await scheduler.run_cycle() == 1
    run = await db.scalar(select(FileIndexRun))
    assert run.directories == 1 and run.frontier[0]['uri'] == 'scan-test://parent/'
    assert await mechanism.count_pending() == 2
    assert {entry.uri for entry in await db.scalars(select(FileCatalogEntry))} == {'scan-test://', 'scan-test://parent/', 'scan-test://sibling/'}
    for _ in range(3):
        assert await scheduler.run_cycle() == 1
    await db.refresh(run)
    assert run.status == 'success' and run.directories == 4
    assert await mechanism.count_pending() == 2
    for _ in range(2):
        assert await scheduler.run_cycle() == 1
    assert await mechanism.count_pending() == 0
    assert await scheduler.run_cycle() == 0
    receipts = list(await db.scalars(select(DreamReceipt).order_by(DreamReceipt.created_at)))
    assert len(receipts) == 6
    assert all(receipt.subject_kind in {'file_directory', 'file_fingerprint'} and receipt.status == 'success' and receipt.cost == 0 for receipt in receipts)
    assert [_receipt_summary(receipt, None, None).subject_preview for receipt in receipts if receipt.subject_kind == 'file_directory'] == ['scan-test://', 'scan-test://parent/', 'scan-test://sibling/', 'scan-test://parent/child/']
    assert await db.scalar(select(func.count()).select_from(LLMCall)) == baseline_calls
    assert len(await hits(ctx.agent_id, 'report')) == 1
    assert await hits(peer.id, 'report') == []


@pytest.mark.asyncio
async def test_dream_rescan_catches_up_once_and_reconciles_changed_tree(catalogue_dream, db, monkeypatch):
    from app.file_share import indexing
    from app.file_share.models import FileIndexRun
    from core.params import runtime_settings
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    clock = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    class CatalogueClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.astimezone(tz) if tz is not None else clock.replace(tzinfo=None)
    monkeypatch.setattr(catalogue, 'datetime', CatalogueClock)
    monkeypatch.setattr(indexing, 'now', lambda: clock)
    monkeypatch.setattr(indexing, 'local_timezone_name', lambda: 'Europe/Paris')
    await transport.file_write_text('removed/old.txt', 'synthetic old', overwrite=False)
    for _ in range(2):
        assert await scheduler.run_cycle() == 1
    old = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.uri == 'scan-test://removed/old.txt'))
    original_id = old.memory_item_id
    shutil.rmtree(transport.resolve_path('removed'))
    await transport.file_write_text('added/new.txt', 'synthetic new', overwrite=False)
    clock = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
    # A missed midnight is caught up once, even if the scheduler was offline.
    assert await mechanism.count_pending() == 2  # One root rescan and one pending byte fingerprint.
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 1
    assert await scheduler.run_cycle() == 0
    await db.refresh(old)
    assert not old.present and old.memory_item_id == original_id
    assert await hits(ctx.agent_id, 'old') == []
    assert len(await hits(ctx.agent_id, 'new')) == 1
    assert len(list(await db.scalars(select(FileIndexRun)))) == 2
    monkeypatch.setattr(runtime_settings, 'DREAM_FILE_RESCAN_SCHEDULE', 'off')
    clock += timedelta(days=40)
    await indexing.prune_index_history()
    assert len(list(await db.scalars(select(FileIndexRun)))) == 1
    assert await scheduler.run_cycle() == 0


@pytest.mark.asyncio
async def test_dream_directory_checkpoint_is_atomic_and_replay_is_idempotent(catalogue_dream, db):
    from app.dream.service import mark_success
    from app.file_share.models import FileIndexRun
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    await transport.file_write_text('child/file.txt', 'synthetic', overwrite=False)
    claim = await mechanism.claim_one()
    assert claim is not None and claim.subject_kind == 'file_directory'
    assert await mechanism.count_pending() == 0
    assert await mechanism.claim_one() is None
    assert await mechanism.apply(claim, claim.prepared_payload) == 1
    run = await db.scalar(select(FileIndexRun))
    assert run.directories == 1 and run.scanned == 1
    assert await mechanism.apply(claim, claim.prepared_payload) == 1
    await db.refresh(run)
    assert run.directories == 1 and run.scanned == 1
    await mark_success(claim, result_count=1)
    with pytest.raises(RuntimeError, match='lease was lost'):
        await mechanism.apply(claim, claim.prepared_payload)
    assert await mechanism.count_pending() == 1


@pytest.mark.asyncio
async def test_dream_failed_listing_retries_same_receipt_without_removing_entries(catalogue_dream, db, monkeypatch):
    from app.dream.models import DreamReceipt
    from app.file_share import ResourceRevisionConflict
    from app.file_share.indexing import start_index_run, now
    from app.file_share.models import FileIndexRun
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    await resource_service.resource_write_text(ctx, 'scan-test://retry/file.txt', 'synthetic')
    run = await start_index_run(ctx, 'scan-test://retry/')
    run.frontier = [{'uri': run.root_uri, 'cursor': 'stale-cursor', 'depth': 0}]
    await db.commit()
    original = transport.resource_list_page
    async def failed(path, **kwargs):
        raise ResourceRevisionConflict('Synthetic revision changed')
    monkeypatch.setattr(transport, 'resource_list_page', failed)
    assert await scheduler.run_cycle() == 1
    receipt = await db.scalar(select(DreamReceipt))
    assert receipt.status == 'retry' and receipt.attempts == 1
    await db.refresh(run)
    assert run.status == 'retry' and run.frontier[0]['cursor'] is None
    assert all(entry.present for entry in await db.scalars(select(FileCatalogEntry)))
    # The backoff belongs to Dream, and another claim cannot bypass it.
    original_subject = receipt.subject_id
    claim = await mechanism.claim_one()
    assert claim is None or claim.subject_id != original_subject
    # A fresh automatic root can also be eligible; leave it pending for this assertion.
    if claim is not None:
        from app.dream.service import release_interrupted
        await release_interrupted(claim, 'Synthetic test leaves the root pending')
    receipt.available_at = now() - timedelta(seconds=1)
    monkeypatch.setattr(transport, 'resource_list_page', original)
    await db.commit()
    retry = await mechanism.claim_one()
    assert retry is not None and retry.receipt_id == receipt.id
    await scheduler._run_claim(mechanism, retry)
    await db.refresh(run)
    await db.refresh(receipt)
    assert receipt.status == 'success' and receipt.subject_id == original_subject
    assert run.status == 'success' and run.scanned == 1


@pytest.mark.parametrize(('schedule', 'reference', 'expected'), [
    ('off', '2026-10-05T00:00:00+00:00', None),
    ('weekly_midnight', '2026-10-04T21:59:59+00:00', '2026-09-27T22:00:00+00:00'),
    ('weekly_midnight', '2026-10-04T22:00:00+00:00', '2026-10-04T22:00:00+00:00'),
    ('weekly_midnight', '2026-10-26T12:00:00+00:00', '2026-10-25T23:00:00+00:00'),
    ('daily_midnight', '2026-10-02T12:00:00+00:00', '2026-10-01T22:00:00+00:00'),
])
def test_file_rescan_uses_local_calendar_midnight(schedule, reference, expected, monkeypatch):
    from app.file_share import indexing
    from core.params import runtime_settings
    monkeypatch.setattr(runtime_settings, 'DREAM_FILE_RESCAN_SCHEDULE', schedule)
    monkeypatch.setattr(indexing, 'local_timezone_name', lambda: 'Europe/Paris')
    assert indexing.rescan_boundary(datetime.fromisoformat(reference)) == (datetime.fromisoformat(expected) if expected else None)


@pytest.mark.asyncio
async def test_dream_directory_interruption_and_exhausted_crash_lease(catalogue_dream, db, monkeypatch):
    import asyncio
    from app.dream.models import DreamReceipt
    from app.dream.service import reconcile_expired_receipts
    from app.file_share.models import FileIndexRun
    from core.params import runtime_settings
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    await transport.file_write_text('file.txt', 'synthetic', overwrite=False)
    async def interrupted(path, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(transport, 'resource_list_page', interrupted)
    assert await scheduler.run_cycle() == 1
    receipt = await db.scalar(select(DreamReceipt))
    run = await db.scalar(select(FileIndexRun))
    assert receipt.status == 'retry' and receipt.attempts == 0
    assert run.scanned == 0 and run.directories == 0
    assert await db.scalar(select(FileCatalogEntry.id)) is None
    claim = await mechanism.claim_one()
    assert claim is not None and claim.receipt_id == receipt.id
    await db.refresh(receipt)
    receipt.attempts = runtime_settings.DREAM_MAX_ATTEMPTS
    receipt.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    await reconcile_expired_receipts()
    assert await mechanism.count_pending() == 0
    assert await mechanism.claim_one() is None
    await db.refresh(run)
    assert run.status == 'error' and run.error_type == 'DreamAttemptsExhausted'
    assert await db.scalar(select(FileCatalogEntry.id)) is None


@pytest.mark.asyncio
async def test_dream_directory_pagination_has_distinct_bounded_receipts(catalogue_dream, db):
    from app.dream.models import DreamReceipt
    from app.file_share.models import FileIndexRun
    (ctx, transport, connection, peer), scheduler, mechanism = catalogue_dream
    for index in range(503):
        await transport.file_write_text(f'item-{index:04d}.txt', 'synthetic', overwrite=False)
    assert await scheduler.run_cycle() == 1
    run = await db.scalar(select(FileIndexRun))
    assert run.scanned == 500 and run.directories == 0
    assert await mechanism.count_pending() == 501
    assert await scheduler.run_cycle() == 1
    await db.refresh(run)
    assert run.status == 'success' and run.scanned == 503 and run.directories == 1
    receipts = list(await db.scalars(select(DreamReceipt)))
    assert len(receipts) == 2 and len({receipt.subject_id for receipt in receipts}) == 2
    assert sorted(receipt.result_count for receipt in receipts) == [3, 500]
    assert await mechanism.count_pending() == 500  # Further fingerprint candidates remain beyond this bounded window.
