from app.share import ShareGrant
from uuid import UUID

import pytest
from sqlalchemy import select

from app.dataset import service
from app.dataset.models import Dataset, DatasetAlias
from app.file_share import ResourceContext, resource_create, resource_delete, resource_info, resource_read, resource_write
from app.document import document_service


@pytest.mark.asyncio
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
async def test_dataset_partial_read_locates_edit_lines_without_changing_character_pagination(db, agents, newline):
    from app.file_share import resource_edit

    owner, other = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    source = newline.join(['{', '  "first": {"kept": true},', '  "target": {',
        '    "state": "pending"', '  },', '  "last": 3', '}', ''])
    created = await resource_create(ctx, "data://", source.encode(), name="Synthetic editable inventory")
    start = source.index('"target"') - 1
    end = source.index(newline + '  "last"')
    page = await resource_read(ctx, created.uri, offset=start, max_chars=end - start)
    metadata = page.model_dump()
    assert page.content == source[start:end]
    assert (page.start, page.end, page.next_offset, page.total) == (start, end, end, len(source))
    assert metadata["start_line"] == 3
    assert metadata["end_line"] == 5
    assert metadata["total_lines"] == 7
    assert metadata["start_line_complete"] is False
    assert metadata["end_line_complete"] is False
    await resource_edit(ctx, created.uri, start_line=metadata["start_line"] + 1,
        end_line=metadata["start_line"] + 1, content='    "state": "done"', expected_revision=page.revision)
    updated = await resource_read(ctx, created.uri)
    assert updated.content == source.replace('"pending"', '"done"')
    assert updated.model_dump()["start_line_complete"] is True
    assert updated.model_dump()["end_line_complete"] is True
    empty = await resource_read(ctx, created.uri, offset=len(updated.content) + 100)
    assert empty.content == "" and empty.next_offset is None
    assert empty.model_dump()["start_line"] is None
    assert empty.model_dump()["end_line"] is None
    assert empty.model_dump()["total_lines"] == 7
    with pytest.raises(service.DatasetConflictError):
        await resource_edit(ctx, created.uri, start_line=4, end_line=4,
            content='    "state": "stale"', expected_revision=page.revision)
    with pytest.raises(service.DatasetNotFoundError):
        await resource_read(ResourceContext(agent_id=other.id, runtime="internal"), created.uri, offset=start)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["native", "legacy-file", "document-api"])
@pytest.mark.parametrize("markers", [
    {"engine_dataset": True},
    {"engine_managed": True, "engine_agent": 1},
    {"engine_dataset": True, "engine_managed": True, "engine_agent": 1},
])
async def test_obsolete_process_markers_do_not_override_dataset_deletion_rights(db, agents, memory_storage, surface, markers):
    from app.dataset.models import DatasetAttachment, DatasetRevision

    owner, other = agents
    content = '{"synthetic":"retained history"}'
    legacy = surface != "native"
    if legacy:
        source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic former run data",
            content=content, task_id=None, document_type="dataset", metadata=markers, workflow_metadata=True)
        uri = f"document://{source.id}"
        await resource_info(ResourceContext(agent_id=owner.id, runtime="internal"), uri)
        dataset = await service.record(source.id, owner.id)
    else:
        dataset = Dataset(owner_agent_id=owner.id, title="Synthetic former run data", content=content, metadata_=markers)
        db.add(dataset)
        await db.flush()
        db.add(DatasetRevision(dataset_id=dataset.id, revision=1, content=content, author_agent_id=owner.id))
        await db.flush()
        uri = f"data://{dataset.id}"
    assert (await service.describe(dataset, owner.id))["can_delete"]
    listed = await service.list_datasets(owner.id)
    assert next(item for item in listed["items"] if item["id"] == str(dataset.id))["can_delete"]
    with pytest.raises(service.DatasetNotFoundError):
        await resource_delete(ResourceContext(agent_id=other.id, runtime="internal"), uri)
    with pytest.raises(service.DatasetConflictError):
        await service.remove(dataset.id, owner.id, expected_lock_version=dataset.lock_version + 1)
    context = ResourceContext(agent_id=owner.id, runtime="internal")
    if legacy:
        from app.document import write_workflow_document
        await write_workflow_document(dataset.id, owner.id, '{"updated":true}', expected_revision=1)
    else:
        await resource_write(context, uri, b'{"updated":true}', expected_revision=1)
    await service.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version,
        values={"metadata": {**dataset.metadata_, "ordinary": True}})
    attachment = await resource_create(context, f"data://{dataset.id}/attachments/", b"Synthetic former run attachment", name="synthetic.txt")
    assert (await resource_read(context, attachment.uri)).content == "Synthetic former run attachment"
    attached = await db.scalar(select(DatasetAttachment).where(DatasetAttachment.dataset_id == dataset.id, DatasetAttachment.uri == attachment.uri))
    attachment_uri = f"data://{dataset.id}/attachments/{attached.id}"
    from app.dataset.attachments import rename_attachment
    before = (dataset.content, dataset.revision, attached.uri, attached.file_id)
    with pytest.raises(service.DatasetNotFoundError):
        await rename_attachment(dataset.id, attached.id, other.id, "denied.txt")
    await rename_attachment(dataset.id, attached.id, owner.id, "Renamed dataset attachment.txt")
    assert (await resource_info(context, attachment_uri)).name == "Renamed dataset attachment.txt"
    assert (dataset.content, dataset.revision, attached.uri, attached.file_id) == before
    assert (await resource_read(context, attachment_uri)).content == "Synthetic former run attachment"
    await resource_delete(context, attachment_uri)
    with pytest.raises(FileNotFoundError):
        await resource_info(context, attachment_uri)
    # Read-only prevents content edits, while owners retain deletion rights.
    await service.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version, values={"read_only": True})
    if surface == "document-api":
        from app.document import resource_service as documents
        await documents.delete_document(dataset.id, actor_agent_id=owner.id)
    else:
        await resource_delete(context, uri)
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(dataset.id, owner.id)
    assert await db.scalar(select(DatasetRevision.content).where(DatasetRevision.dataset_id == dataset.id, DatasetRevision.revision == 1)) == content
    if legacy:
        from app.memory.models import MemoryItem
        assert await db.get(MemoryItem, dataset.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,options", [("data://", {}), ("document://", {"document_type": "dataset"}), ("document://", {"document_type": "data"})])
@pytest.mark.parametrize("empty", [None, "   "])
async def test_missing_dataset_content_is_rejected_then_corrected_without_extra_resources(db, agents, path, options, empty):
    from sqlalchemy import func
    from app.file_share.mcp import create_file
    from app.tools.contracts import ToolCallRejectedError
    from app.tools.mcp_loader import McpToolContext
    import json

    owner, _ = agents
    tool_context = McpToolContext(agent_id=owner.id, runtime="internal")
    count = select(func.count()).select_from(Dataset).where(Dataset.owner_agent_id == owner.id)
    before = await db.scalar(count)
    with pytest.raises(ToolCallRejectedError, match="content"):
        if empty is None:
            await create_file(tool_context, path, **options)
        else:
            await create_file(tool_context, path, content=empty, **options)
    assert await db.scalar(count) == before
    created = json.loads(await create_file(tool_context, path,
        content='{"items":[]}', name="Synthetic corrected inventory", **options))
    assert created["uri"].startswith("data://")
    assert await db.scalar(count) == before + 1
    from app.memory import MemoryItem
    assert await db.get(MemoryItem, UUID(created["uri"].removeprefix("data://"))) is None
    assert (await resource_read(ResourceContext(agent_id=owner.id, runtime="internal"), created["uri"])).content == '{"items":[]}'


@pytest.mark.asyncio
async def test_dataset_uri_lifecycle_preserves_exact_json_revisions_and_denies_other_actors(db, agents):
    owner, other = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    source = '{\n "note": "<p>Literal JSON</p>", "zero": 0\n}\n'
    created = await resource_create(ctx, "data://", source.encode(), name="Synthetic structured data")
    identity = UUID(created.uri.removeprefix("data://"))
    assert await db.get(Dataset, identity) is not None
    from app.memory import MemoryItem
    assert await db.get(MemoryItem, identity) is None
    assert (await resource_read(ctx, created.uri)).content == source
    with pytest.raises(service.DatasetNotFoundError):
        await resource_read(ResourceContext(agent_id=other.id, runtime="internal"), created.uri)
    with pytest.raises(service.DatasetConflictError):
        await resource_write(ctx, created.uri, b"{}")
    await resource_write(ctx, created.uri, b"false", expected_revision=1)
    assert (await resource_read(ctx, created.uri)).revision == 2
    assert (await service.revision(identity, owner.id, 1)).content == source
    restored = await service.restore(identity, owner.id, number=1, expected_revision=2)
    assert restored.revision == 3 and restored.content == source


@pytest.mark.asyncio
async def test_explicit_legacy_alias_preserves_identity_content_and_uses_one_authority(db, agents, memory_storage):
    owner, _ = agents
    legacy = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic legacy Dataset",
        content='{"kept":false}', task_id=None, document_type="dataset")
    ordinary = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic prose", content="<p>Prose</p>", task_id=None)
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    info = await resource_info(ctx, f"document://{legacy.id}")
    assert info.uri == f"data://{legacy.id}"
    alias = await db.scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == legacy.id))
    assert alias is not None and alias.dataset_id == legacy.id
    await resource_write(ctx, f"document://{legacy.id}", b'{"kept":true}', expected_revision=1)
    assert (await resource_read(ctx, f"data://{legacy.id}")).content == '{"kept":true}'
    from app.document import resource_service as memory
    assert (await memory.get_item(legacy.id, agent_id=owner.id))[1] == b'{"kept":true}'
    with pytest.raises(service.DatasetNotFoundError):
        await resource_read(ctx, f"data://{ordinary.id}")
    assert (await resource_info(ctx, f"document://{ordinary.id}")).uri == f"document://{ordinary.id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ['{\n}\n', 'null', 'false', '0', '"Synthetic text"', '[1,false,null,{"free":"data"}]'])
async def test_dataset_json_roots_remain_free_and_exact_on_write_and_restore(db, agents, source):
    owner, _ = agents
    dataset = await service.create(owner.id, title="Synthetic sparse values", content=source)
    assert dataset.content == source
    await service.replace(dataset.id, owner.id, content='{"different":[true,0]}', expected_revision=1)
    await service.restore(dataset.id, owner.id, number=1, expected_revision=2)
    assert dataset.content == source
    with pytest.raises(ValueError):
        await service.replace(dataset.id, owner.id, content='{"broken":', expected_revision=3)
    assert dataset.content == source and dataset.revision == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_via_file", [False, True])
async def test_legacy_public_sharing_and_revocation_apply_to_the_canonical_uri(db, agents, memory_storage, delete_via_file):
    from app.document import resource_service as memory
    from app.document.schemas import DocumentGlobalAccessUpdate
    owner, other = agents
    legacy = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic public data",
        content='{"synthetic":true}', task_id=None, document_type="dataset")
    await memory.set_document_global_access(legacy.id, DocumentGlobalAccessUpdate(expected_revision=1, global_access=1), actor_agent_id=owner.id)
    assert (await service.record(legacy.id, other.id)).global_access == 1
    await memory.set_document_global_access(legacy.id, DocumentGlobalAccessUpdate(expected_revision=1, global_access=0), actor_agent_id=owner.id)
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(legacy.id, other.id)
    # Canonical writes refresh legacy readers without reviving revoked grants.
    from app.memory import MemoryItem

    dataset = await service.record(legacy.id, owner.id)
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=other.id,
        can_write=False, expected_lock_version=dataset.lock_version)
    assert (await memory.get_item(legacy.id, agent_id=other.id))[1] == b'{"synthetic":true}'
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=other.id,
        can_write=None, expected_lock_version=dataset.lock_version)
    await service.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version,
        values={"title": "Synthetic renamed data", "keywords": ["synthetic"]})
    await service.replace(dataset.id, owner.id, content='{"updated":false}', expected_revision=dataset.revision)
    from app.document.models import Document, DocumentRevision
    current = await db.get(Document, legacy.id)
    assert current.title == dataset.title and current.keywords == dataset.keywords
    assert current.revision == dataset.revision
    assert await db.get(MemoryItem, legacy.id) is None
    if delete_via_file:
        await resource_delete(ResourceContext(agent_id=owner.id, runtime="internal"), f"data://{dataset.id}")
    else:
        await service.remove(dataset.id, owner.id, expected_lock_version=dataset.lock_version)
    assert await memory.item_record(legacy.id) is None
    assert await db.scalar(select(DocumentRevision.id).where(DocumentRevision.document_id == legacy.id).limit(1)) is not None



@pytest.mark.asyncio
async def test_cancelled_dataset_deletion_preserves_document_and_canonical_history(db, agents, memory_storage):
    from app.document import resource_service as memory
    from app.document.models import DocumentRevision
    from app.dataset.models import DatasetRevision

    owner, _other = agents
    legacy = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic rollback data",
        content='{"synthetic":"preserved"}', task_id=None, document_type="dataset")
    dataset = await service.record(legacy.id, owner.id)
    identity, version = dataset.id, dataset.lock_version
    await db.commit()
    async with db.begin_nested() as savepoint:
        await service.remove(identity, owner.id, expected_lock_version=version)
        assert await memory.item_record(identity) is None
        await savepoint.rollback()
    assert await service.record(identity, owner.id)
    assert await memory.item_record(identity) is not None
    assert await db.scalar(select(DocumentRevision.id).where(DocumentRevision.document_id == identity)) is not None
    assert await db.scalar(select(DatasetRevision.id).where(DatasetRevision.dataset_id == identity)) is not None
