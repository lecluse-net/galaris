from uuid import UUID

import pytest
from sqlalchemy import select

from app.dataset import service
from app.dataset.models import Dataset, DatasetAlias
from app.file_share import ResourceContext, resource_create, resource_delete, resource_info, resource_read, resource_write
from app.memory import document_service


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
    from app.memory import service as memory
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
    from app.memory import service as memory
    from app.memory.schemas import DocumentGlobalAccessUpdate
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
    from app.memory.models import MemoryItemGrant
    dataset = await service.record(legacy.id, owner.id)
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=other.id,
        can_write=False, expected_lock_version=dataset.lock_version)
    assert (await memory.get_item(legacy.id, agent_id=other.id))[1] == b'{"synthetic":true}'
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=other.id,
        can_write=None, expected_lock_version=dataset.lock_version)
    await service.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version,
        values={"title": "Synthetic renamed data", "keywords": ["synthetic"]})
    await service.replace(dataset.id, owner.id, content='{"updated":false}', expected_revision=dataset.revision)
    projected = await db.get(MemoryItem, legacy.id)
    assert projected.title == dataset.title and projected.keywords == dataset.keywords
    assert projected.revision == dataset.revision and projected.lock_version == dataset.lock_version
    assert projected.size_bytes == len(dataset.content.encode())
    assert await db.scalar(select(MemoryItemGrant.id).where(MemoryItemGrant.item_id == legacy.id)) is None
    with pytest.raises(memory.MemoryPermissionError):
        await memory.get_item(legacy.id, agent_id=other.id)
    if delete_via_file:
        await resource_delete(ResourceContext(agent_id=owner.id, runtime="internal"), f"data://{dataset.id}")
    else:
        await service.remove(dataset.id, owner.id, expected_lock_version=dataset.lock_version)
    assert await memory.document_record(legacy.id) is None
