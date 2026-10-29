from __future__ import annotations
from app.memory.tests.document_fixtures import finish_document_deletion
from app.document import resource_service as documents
from app.memory.tests.document_fixtures import create_indexed_attachment
from app.document.schemas import DocumentPayload
from app.document.schemas import DocumentItemCreate
from app.memory.tests.document_fixtures import create_document_reference, edit_document_reference

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_service import resource_info, resource_list, resource_search, resource_read, materialize_resource
from app.memory import service
from app.document import document_attachment_service as attachments
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.document.schemas import DocumentGrantUpdate
from core.settings import settings
from core.storage import FileAlias, StoredFile, file_path
from core.storage.migration import cleanup_legacy_files, transfer_legacy_files
from file_storage_composition import legacy_inventory, needs_file_storage
from core.dbadmin import SchemaTransitionSet


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_scheme", ["file", "document"])
async def test_native_attachment_views_read_the_single_registered_name(agents, memory_storage, db, tmp_path, reference_scheme):
    from io import BytesIO
    from zipfile import ZipFile
    from app.dataset import service as datasets
    from app.dataset.attachments import attach_existing, list_attachments
    from app.document.document_export import export_document_bundle

    owner, _ = agents
    document, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic shared filename", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Preserved body</p>")))
    attachment = await create_indexed_attachment(document.id, actor_agent_id=owner.id,
        name="Original.txt", media_type="text/plain", content=b"Synthetic shared bytes")
    dataset = await datasets.create(owner.id, title="Synthetic file references", content="{}")
    reference_uri = f"file://{attachment.id}" if reference_scheme == "file" else f"document://{document.id}/attachments/{attachment.id}"
    reference = await attach_existing(dataset.id, owner.id, uri=reference_uri, agent_id=owner.id)
    assert reference.file_id == attachment.id
    await db.commit()
    unchanged_document = (deepcopy(document.metadata_), document.revision, document.lock_version)
    # Rename only the authoritative row; no consumer may need its own name update.
    stored = await db.get(StoredFile, attachment.id)
    stored.name = "Global name.txt"
    await db.commit()
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    uri = f"document://{document.id}/attachments/{attachment.id}"
    assert (await attachments.list_document_attachments(document.id, actor_agent_id=owner.id))[0].name == stored.name
    assert (await attachments.document_attachment_path(document.id, attachment.id, actor_agent_id=owner.id))[0].name == stored.name
    assert (await attachments.read_document_attachment(document.id, attachment.id, actor_agent_id=owner.id))[0].name == stored.name
    assert (await list_attachments(dataset.id, owner.id))[0]["name"] == stored.name
    for source in (f"file://{attachment.id}", uri, f"data://{dataset.id}/attachments/{reference.id}"):
        assert (await resource_info(ctx, source)).name == stored.name
        exported = await materialize_resource(ctx, source, tmp_path / "download", max_bytes=100)
        assert exported.name == stored.name
    bundle = await export_document_bundle(document.id, f'<p><a href="{uri}">Attachment</a></p>', actor_agent_id=owner.id)
    with ZipFile(BytesIO(bundle)) as archive:
        assert f"attachments/{attachment.id}-{stored.name}" in archive.namelist()
    await attachments.rename_document_attachment(document.id, attachment.id, actor_agent_id=owner.id, name="From document.txt")
    assert (await resource_info(ctx, f"data://{dataset.id}/attachments/{reference.id}")).name == "From document.txt"
    from app.dataset.attachments import rename_attachment
    await rename_attachment(dataset.id, reference.id, owner.id, "From dataset.txt")
    assert (await attachments.list_document_attachments(document.id, actor_agent_id=owner.id))[0].name == "From dataset.txt"
    assert (document.metadata_, document.revision, document.lock_version) == unchanged_document
    assert reference.name == "Original.txt"  # Historical ingestion metadata is never rewritten.


@pytest.mark.asyncio
async def test_standalone_upload_is_private_renameable_and_reuses_thumbnail_engine(agents, db, tmp_path, monkeypatch):
    from io import BytesIO
    from fastapi import UploadFile
    from core.preview import thumbnails
    from app.file_share.managed_files import upload_managed_file, rename_managed_file, managed_file_thumbnail

    owner, other = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    denied = ResourceContext(agent_id=other.id, runtime="internal")
    monkeypatch.setattr(type(settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path / "thumbnails"))
    descriptor = await upload_managed_file(ctx, UploadFile(filename="../../Report.txt", file=BytesIO(b"Synthetic file content")))
    assert descriptor.uri.startswith("file://") and descriptor.name == "Report.txt"
    identifier = UUID(descriptor.uri.removeprefix("file://"))
    original_path = file_path(identifier)
    with pytest.raises(PermissionError):
        await resource_read(denied, descriptor.uri)
    with pytest.raises(PermissionError):
        await rename_managed_file(denied, identifier, "stolen.txt")
    renamed = await rename_managed_file(ctx, identifier, "Official report.txt")
    assert renamed.uri == descriptor.uri and renamed.name == "Official report.txt"
    assert file_path(identifier) == original_path and original_path.read_bytes() == b"Synthetic file content"
    from app.file_share.resource_service import resource_copy
    copied = await resource_copy(ctx, renamed.uri, "file://")
    assert copied.uri != renamed.uri
    assert (await resource_info(ctx, copied.uri)).name == renamed.name
    assert (await resource_info(ctx, copied.uri)).media_type == renamed.media_type
    image = await managed_file_thumbnail(ctx, identifier)
    assert image is not None
    assert thumbnails.cache_path(descriptor.uri).read_bytes() == image
    with pytest.raises(PermissionError):
        await managed_file_thumbnail(denied, identifier)
    assert await managed_file_thumbnail(ctx, identifier) == image


@pytest.mark.asyncio
async def test_document_attachment_registry_keeps_acl_retained_bytes_and_old_links(agents, memory_storage, db, tmp_path):
    owner, stranger = agents
    item, _ = await create_document_reference(DocumentItemCreate(
        owner_agent_id=owner.id, title="Synthetic report", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Synthetic body</p>"),
    ))
    attachment = await create_indexed_attachment(item.id, actor_agent_id=owner.id,
        name="Synthetic appendix.txt", media_type="text/plain", content=b"synthetic appendix")
    record = await db.get(StoredFile, attachment.id)
    assert record is not None and record.name == attachment.name
    assert file_path(attachment.id).read_bytes() == b"synthetic appendix"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    uri = f"file://{attachment.id}"
    assert (await resource_read(ctx, uri)).content == "synthetic appendix"
    assert uri in {entry.uri for entry in (await resource_list(ctx, "file://")).entries}
    assert [hit.resource.uri for hit in (await resource_search(ctx, "file://", "Synthetic appendix", mode="name")).hits] == [uri]
    denied = ResourceContext(agent_id=stranger.id, runtime="internal")
    assert uri not in {entry.uri for entry in (await resource_list(denied, "file://")).entries}
    assert not (await resource_search(denied, "file://", "Synthetic appendix", mode="name")).hits
    await documents.set_item_grant(item.id, stranger.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert uri in {entry.uri for entry in (await resource_list(denied, "file://")).entries}
    await documents.remove_item_grant(item.id, stranger.id, actor_agent_id=owner.id)
    assert uri not in {entry.uri for entry in (await resource_list(denied, "file://")).entries}
    assert not (await resource_search(denied, "file://", "Synthetic appendix", mode="name")).hits
    with pytest.raises(PermissionError):
        await resource_info(ResourceContext(agent_id=stranger.id, runtime="internal"), uri)
    await attachments.delete_document_attachment(item.id, attachment.id, actor_agent_id=owner.id)
    assert (await resource_read(ctx, uri)).content == "synthetic appendix"
    assert uri in {entry.uri for entry in (await resource_list(ctx, "file://")).entries}
    assert (await resource_read(ctx, f"document://{item.id}/attachments/{attachment.id}")).content == "synthetic appendix"
    destination = tmp_path / "materialized.txt"
    result = await materialize_resource(ctx, uri, destination, max_bytes=100)
    assert result.size == len(b"synthetic appendix")
    assert destination.read_bytes() == b"synthetic appendix"
    assert file_path(attachment.id).is_file()
    await finish_document_deletion(item.id, actor_agent_id=owner.id)
    assert not file_path(attachment.id).exists()
    assert uri not in {entry.uri for entry in (await resource_list(ctx, "file://")).entries}
    assert not (await resource_search(ctx, "file://", "Synthetic appendix", mode="name")).hits
    with pytest.raises((PermissionError, FileNotFoundError)):
        await resource_read(ctx, uri)
    with pytest.raises(documents.DocumentNotFoundError):
        await resource_read(ctx, f"document://{item.id}/attachments/{attachment.id}")
    assert str(attachment.id) not in {source.uuid for source in await legacy_inventory(db)}, (
        "Forgotten document pointers must not become missing legacy migration sources"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scan_limit", [1, 500])
async def test_file_root_paginates_accessible_attachments_without_duplicates_or_leaks(
    agents, memory_storage, db, monkeypatch, scan_limit,
):
    from app.file_share import managed_files
    from app.file_share.resource_service import resource_create

    owner, stranger = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    monkeypatch.setattr(managed_files, "_LIST_SCAN_LIMIT", scan_limit)
    standalone = await resource_create(ctx, "file://", b"Synthetic independent bytes", name="Same_%.txt")
    decoy = await resource_create(ctx, "file://", b"Synthetic different name", name="SameXX.txt")
    expected = {standalone.uri}
    for agent in (owner, stranger):
        document, _ = await create_document_reference(DocumentItemCreate(
            owner_agent_id=agent.id, title="Synthetic paginated files", node_kind="document", media_type="text/html",
            payload=DocumentPayload(text="<p>Synthetic body</p>"),
        ))
        for index in range(3):
            attachment = await create_indexed_attachment(document.id, actor_agent_id=agent.id,
                name="Same_%.txt", media_type="text/plain", content=f"Synthetic appendix {index}".encode())
            # A stale reference must neither hide the valid alias nor duplicate the file.
            db.add(FileAlias(file_id=attachment.id, uri=f"document://{UUID(int=1)}/attachments/{attachment.id}"))
            if agent.id == owner.id:
                expected.add(f"file://{attachment.id}")
    await db.flush()

    for searching in (False, True):
        cursor, seen, cursors = None, [], set()
        for _ in range(20):
            if searching:
                page = await resource_search(ctx, "file://", "Same_%", mode="name", max_results=1, cursor=cursor)
                seen.extend(hit.resource.uri for hit in page.hits)
            else:
                page = await resource_list(ctx, "file://", max_entries=1, cursor=cursor)
                seen.extend(entry.uri for entry in page.entries)
            if not page.truncated:
                assert page.next_cursor is None
                break
            assert page.next_cursor and page.next_cursor not in cursors
            cursors.add(page.next_cursor)
            cursor = page.next_cursor
        else:
            pytest.fail("File pagination did not terminate")
        visible = expected if searching else expected | {decoy.uri}
        assert set(seen) == visible and len(seen) == len(visible)
    assert not (await resource_search(ctx, "file://", "SameX%", mode="name")).hits


@pytest.mark.asyncio
async def test_migration_preserves_document_body_history_and_never_fetches_external_files(
    agents, memory_storage, db, tmp_path, monkeypatch,
):
    from app.connection import Connection
    from app.tools import ToolModel
    from app.messenger.models import File
    from app.messenger import native_facade
    from app.file_share import file_share_service

    monkeypatch.setattr(type(settings), "GALARIS_MEMORY_ROOT", str(memory_storage))
    owner, _ = agents
    item, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic migration", node_kind="document", media_type="text/html", payload=DocumentPayload(text="<p>Body to preserve</p>")))
    attachment = await create_indexed_attachment(item.id, actor_agent_id=owner.id,
        name="Historical.txt", media_type="text/plain", content=b"historical attachment")
    await attachments.delete_document_attachment(item.id, attachment.id, actor_agent_id=owner.id)
    snapshot = deepcopy(item.metadata_)
    body = (await service.get_item(item.id, agent_id=owner.id))[1]
    tool = ToolModel(code=f"offline-{uuid4().hex}", label="Offline synthetic Nextcloud", description="", connection_schema={})
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    external = File(connection_id=connection.id, name="External.txt", mime_type="text/plain", kind="file",
        remote_url="https://nextcloud.example.test/remote.php/dav/files/synthetic/External.txt")
    db.add(external)
    await db.flush()
    external_uri = external.remote_url

    async def forbidden(*args, **kwargs):
        raise AssertionError("A migration must never resolve an external provider")

    monkeypatch.setattr(native_facade, "get_messenger", forbidden)
    monkeypatch.setattr(file_share_service, "resolve_resource_transport_with_service", forbidden)
    # Reconstruct an old-layout internal attachment. The body remains in Memory.
    old_path = memory_storage / str(attachment.id)[:2] / str(attachment.id)
    old_path.parent.mkdir(parents=True, exist_ok=True)
    file_path(attachment.id).replace(old_path)
    await db.execute(delete(FileAlias).where(FileAlias.file_id == attachment.id))
    await db.execute(delete(StoredFile).where(StoredFile.id == attachment.id))
    await db.commit()
    sources = await legacy_inventory(db)
    assert [source.uuid for source in sources] == [str(attachment.id)]
    await transfer_legacy_files(db, sources)
    await db.commit()
    await cleanup_legacy_files(db, sources)
    assert not old_path.exists()
    assert (await service.get_item(item.id, agent_id=owner.id))[1] == body
    assert item.metadata_ == snapshot
    assert external.remote_url == external_uri
    assert await db.get(StoredFile, external.id) is None
    assert (await attachments.read_document_attachment(item.id, attachment.id, actor_agent_id=owner.id))[1] == b"historical attachment"


def test_file_storage_migration_triggers_only_on_its_schema_expansion():
    assert needs_file_storage(SchemaTransitionSet(added_tables=frozenset({"files"})))
    assert not needs_file_storage(SchemaTransitionSet())


@pytest.mark.asyncio
async def test_detached_cleanup_worker_keeps_its_database_context_until_purge_finishes(
    committed_database, memory_storage,
):
    from core.database import get_db, get_db_session
    from core.storage import register_file, retire_file_references
    from app.memory.automation import _process_resource_cleanup

    identifier = uuid4()
    path = file_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic deferred cleanup")
    async with get_db_session():
        await register_file(identifier, name="Deferred.txt", media_type="text/plain",
            alias=f"document://{uuid4()}/attachments/{identifier}")
        alias = await get_db().scalar(select(FileAlias.uri).where(FileAlias.file_id == identifier))
        await retire_file_references(alias.rsplit("/", 1)[0] + "/")
    # This worker owns its root session; no request or rollback fixture can mask
    # using a closed context after its archive check.
    with pytest.raises(RuntimeError):
        get_db()
    await _process_resource_cleanup({"provider_code": "native", "resource_id": str(identifier)})
    assert not path.exists()


@pytest.mark.asyncio
async def test_native_chat_migration_preserves_journal_and_provider_alias(agents, db, tmp_path, monkeypatch):
    from app.connection import Connection
    from app.tools import ToolModel
    from app.messenger import create_internal_room
    from app.messenger import journal
    from app.messenger._observations import ObservedMessengerFile, ObservedMessengerMessage, ObservedMessengerRoom
    from app.messenger.models import Message
    from core.storage.migration import LegacyFile

    owner, stranger = agents
    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path / "chat"))
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    assert tool is not None
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.user_id, agent_id=owner.id)
    assert room is not None
    identifier = uuid4()
    alias = f"chat://{room.external_id}/{identifier}"
    old = LegacyFile("chat", str(identifier), "Legacy.txt", "text/plain", (alias,))
    old.source.parent.mkdir(parents=True, exist_ok=True)
    old.source.write_bytes(b"synthetic legacy chat")
    remote_identifier = f"synthetic-legacy-{uuid4()}"
    assert await journal.record(ObservedMessengerMessage(id=remote_identifier, tool_id=tool.id,
        room=ObservedMessengerRoom(id=room.external_id), text="Synthetic attachment receipt",
        attachments=[ObservedMessengerFile(local_id=identifier, name=old.name, mime=old.media_type, size=21)]),
        connection_id=connection.id, platform="internal", direction="outbound", status="sent")
    await db.commit()
    original = await db.scalar(select(Message).where(Message.remote_message_id == remote_identifier))
    assert original is not None
    snapshot = original.id, original.text, deepcopy(original.metadata_)
    sources = await legacy_inventory(db)
    assert [source.uuid for source in sources] == [str(identifier)]
    await transfer_legacy_files(db, sources)
    await db.commit()
    await cleanup_legacy_files(db, sources)
    assert not old.source.exists()
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    assert (await resource_read(ctx, f"file://{identifier}")).content == "synthetic legacy chat"
    assert f"file://{identifier}" in {entry.uri for entry in (await resource_list(ctx, "file://")).entries}
    assert [hit.resource.uri for hit in (await resource_search(ctx, "file://", "Legacy.txt", mode="name")).hits] == [f"file://{identifier}"]
    denied = ResourceContext(agent_id=stranger.id, runtime="internal")
    assert f"file://{identifier}" not in {entry.uri for entry in (await resource_list(denied, "file://")).entries}
    assert (await resource_read(ctx, alias)).content == "synthetic legacy chat"
    with pytest.raises(PermissionError):
        await resource_info(ResourceContext(agent_id=stranger.id, runtime="internal"), f"file://{identifier}")
    rows = list(await db.scalars(select(Message).where(Message.remote_message_id == remote_identifier)))
    assert len(rows) == 1
    assert (rows[0].id, rows[0].text, rows[0].metadata_) == snapshot
    from app.chat import storage

    # Late failure cleanup must not unlink a file whose journal already committed.
    await storage.discard(identifier)
    assert (await resource_read(ctx, alias)).content == "synthetic legacy chat"


@pytest.mark.asyncio
async def test_shared_document_bytes_do_not_consume_the_chat_quota(agents, memory_storage, db, monkeypatch, tmp_path):
    from io import BytesIO
    from fastapi import UploadFile
    from app.chat import storage
    from core.params import runtime_settings
    from app.file_share.resource_service import resource_create, resource_copy

    owner, _ = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    content = b"other-domain" * 100_000
    created = await resource_create(ctx, "file://", content, name="Synthetic.txt")
    copied = await resource_copy(ctx, created.uri, "file://")
    assert copied.uri != created.uri
    assert (await resource_info(ctx, copied.uri)).size == len(content)
    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path / "chat"))
    monkeypatch.setattr(runtime_settings, "GALARIS_INTERNAL_MESSENGER_MAX_BYTES", 1_000_000)
    identifier = uuid4()
    await storage.store_upload(UploadFile(filename="Chat.txt", file=BytesIO(b"small chat payload")), identifier)
    assert await storage.read_bytes(identifier) == b"small chat payload"
    # Deleted document bytes must not leave a quota credit after their physical purge.
    document, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic quota document", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Temporary appendix</p>")))
    await create_indexed_attachment(document.id, actor_agent_id=owner.id,
        name="Temporary.txt", media_type="text/plain", content=content)
    await finish_document_deletion(document.id, actor_agent_id=owner.id)
    await storage.store_upload(UploadFile(filename="Within.txt", file=BytesIO(b"x" * 750_000)), uuid4())
    with pytest.raises(storage.AttachmentStorageFullError):
        await storage.store_upload(UploadFile(filename="Beyond.txt", file=BytesIO(b"x" * 300_000)), uuid4())


@pytest.mark.asyncio
async def test_populated_upgrade_through_dbadmin_preserves_content_and_resumes_after_ddl(
    inference_db, committed_database, memory_storage, monkeypatch, tmp_path,
):
    """Exercise the actual upgrade phases and real commits in a disposable clone."""
    from sqlalchemy import text
    from app.agent import Agent, Title
    from app.connection import Connection
    from app.tools import ToolModel
    from app.messenger import create_internal_room, journal
    from app.messenger._observations import ObservedMessengerFile, ObservedMessengerMessage, ObservedMessengerRoom
    from app.memory.schemas import MemoryItemUpdate
    from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
    from core.dbadmin._internal import atlas
    from core.storage.dbadmin import register_dbadmin as register_volume
    from core.storage.migration import LegacyFile
    from file_storage_composition import register_dbadmin as register_moves

    db = inference_db
    isolated_engine = committed_database.kw["bind"]
    monkeypatch.setattr(settings, "POSTGRES_DB", isolated_engine.url.database)
    monkeypatch.setattr(orchestrator, "engine", isolated_engine)
    monkeypatch.setattr(atlas, "engine", isolated_engine)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    monkeypatch.setattr(type(settings), "GALARIS_MEMORY_ROOT", str(memory_storage))
    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path / "legacy-chat"))

    title = Title(label="Synthetic upgrade", gender="X")
    owner = Agent(title=title, code=f"upgrade-{uuid4().hex}", first_name="Synthetic", last_name="Owner", agent_driver="internal")
    db.add(owner)
    await db.flush()
    document, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic upgrade document", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Original document revision</p>")))
    attachment = await create_indexed_attachment(document.id, actor_agent_id=owner.id,
        name="Preserved appendix.txt", media_type="text/plain", content=b"preserved appendix")
    await attachments.delete_document_attachment(document.id, attachment.id, actor_agent_id=owner.id)
    await edit_document_reference(document.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Current document revision</p>")), actor_agent_id=owner.id)
    memory, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Synthetic independent memory", payload=MemoryPayload(text="<p>Original memory</p>")))
    await service.update_item(memory.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Current memory</p>")), actor_agent_id=owner.id)
    forgotten, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic previously deleted document", node_kind="document", media_type="text/html",
        payload=DocumentPayload(text="<p>Already forgotten before upgrade</p>")))
    forgotten_attachment = await create_indexed_attachment(forgotten.id, actor_agent_id=owner.id,
        name="Already removed.txt", media_type="text/plain", content=b"already removed before upgrade")
    await finish_document_deletion(forgotten.id, actor_agent_id=owner.id)
    assert not file_path(forgotten_attachment.id).exists()

    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "chat"))
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    room = await create_internal_room(actor_user_id=owner.user_id, agent_id=owner.id)
    chat_file = LegacyFile("chat", str(uuid4()), "Preserved chat.txt", "text/plain", ())
    chat_file.source.parent.mkdir(parents=True, exist_ok=True)
    chat_file.source.write_bytes(b"preserved chat bytes")
    await journal.record(ObservedMessengerMessage(id=f"upgrade-{uuid4()}", tool_id=tool.id,
        room=ObservedMessengerRoom(id=room.external_id), text="Synthetic preserved conversation",
        attachments=[ObservedMessengerFile(local_id=UUID(chat_file.uuid), name=chat_file.name, mime=chat_file.media_type, size=20)]),
        connection_id=connection.id, platform="internal", direction="outbound", status="sent")
    await db.commit()

    old_attachment = memory_storage / str(attachment.id)[:2] / str(attachment.id)
    old_attachment.parent.mkdir(parents=True, exist_ok=True)
    file_path(attachment.id).replace(old_attachment)
    # Reconstruct the schema immediately before the file registry was introduced.
    async with isolated_engine.begin() as connection:
        # Dataset and Process references did not exist in this historical schema.
        # Keep its rows/tables; Atlas restores these constraints with the registry.
        await connection.execute(text("ALTER TABLE dataset_attachments DROP CONSTRAINT dataset_attachments_file_id_fkey"))
        await connection.execute(text("ALTER TABLE process_run_files DROP CONSTRAINT process_run_files_file_id_fkey"))
        await connection.execute(text("DROP TABLE file_owners, file_aliases, files, file_stores"))
        await connection.execute(text("DELETE FROM dbadmin_actions WHERE key LIKE 'core.storage.%'"))

    async def business_snapshot():
        snapshot = {}
        for table in ("memory_items", "memory_revisions", "documents",
                      "document_revisions", "document_attachments", "messenger_files",
                      "messenger_messages", "messenger_message_files"):
            rows = await db.scalars(text(f"SELECT to_jsonb(t)::text FROM {table} t ORDER BY to_jsonb(t)::text"))
            snapshot[table] = list(rows)
        await db.commit()
        return snapshot

    before = await business_snapshot()
    preserved_bytes = {path.relative_to(memory_storage): path.read_bytes()
                       for path in memory_storage.glob("*/*") if path.is_file() and path != old_attachment}
    registry = DbAdminRegistry()
    register_moves(registry)
    register_volume(registry)
    real_apply = atlas.apply_target
    interrupted = False

    async def interrupt_after_expansion(*args, **kwargs):
        nonlocal interrupted
        result = await real_apply(*args, **kwargs)
        if not interrupted:
            interrupted = True
            raise RuntimeError("Synthetic process failure after committed file schema expansion")
        return result

    monkeypatch.setattr(orchestrator, "apply_target", interrupt_after_expansion)
    first = await orchestrator.synchronize_database(target_registry=registry)
    assert first.verdict is DbAdminVerdict.FATAL
    assert old_attachment.read_bytes() == b"preserved appendix"
    assert chat_file.source.read_bytes() == b"preserved chat bytes"
    second = await orchestrator.synchronize_database(target_registry=registry)
    assert second.verdict is DbAdminVerdict.CONVERGED, second.issues
    assert not second.transitions.table_added("files")
    assert not old_attachment.exists() and not chat_file.source.exists()
    assert file_path(attachment.id).read_bytes() == b"preserved appendix"
    assert file_path(UUID(chat_file.uuid)).read_bytes() == b"preserved chat bytes"
    assert await db.get(StoredFile, forgotten_attachment.id) is None
    assert await business_snapshot() == before
    assert all((memory_storage / path).read_bytes() == content for path, content in preserved_bytes.items())
    third = await orchestrator.synchronize_database(target_registry=registry)
    assert third.verdict is DbAdminVerdict.CONVERGED, third.issues
    assert await business_snapshot() == before
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    assert (await resource_read(ctx, f"file://{attachment.id}")).content == "preserved appendix"
    assert (await resource_read(ctx, f"chat://{room.external_id}/{chat_file.uuid}")).content == "preserved chat bytes"
    assert (await service.get_item(document.id, agent_id=owner.id))[1] == b"<p>Current document revision</p>"
    assert (await service.get_item(memory.id, agent_id=owner.id))[1] == b"<p>Current memory</p>"
