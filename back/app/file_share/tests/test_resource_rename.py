"""Renaming changes labels while preserving native resources and their contents."""

import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.dataset import service as datasets
from app.document import resource_service as documents
from app.document.models import DocumentRevision
from app.dataset.models import DatasetRevision
from app.file_share import (ResourceContext, resource_create, resource_info, resource_read,
    resource_rename, resource_search, resource_write)
from app.file_share import mcp as file_mcp, resource_service
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from app.tools.mcp_loader import McpToolContext, load_mcp_tools
from .local_file_transport import TemporaryFileTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme,body", [("document", "<p>Synthetic preserved content.</p>"), ("data", '{"kept":[1,2]}')])
async def test_mcp_rename_preserves_native_identity_body_history_attachments_and_grants(
    db, agents, memory_storage, monkeypatch, scheme, body,
):
    owner, reader = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    monkeypatch.setattr(file_mcp, "_resource_context", AsyncMock(return_value=ctx))
    created = await resource_create(ctx, f"{scheme}://", body.encode(), name="Synthetic original")
    identity = UUID(created.uri.split("://")[1])
    attachment = await resource_create(ctx, f"{created.uri}/attachments/", b"Synthetic attachment", name="kept.txt")
    if scheme == "document":
        from app.document.item_sharing import update_agent_sharing
        item, _ = await documents.get_item_metadata(identity, agent_id=owner.id)
        await update_agent_sharing(identity, agent_id=owner.id, kind="agent", target_id=reader.id,
            access="read", expected_lock_version=item.lock_version, document_only=True)
        history_model = DocumentRevision
        history_key = DocumentRevision.document_id
        from app.document.schemas import DocumentUpdate
        await documents.update_item(identity, DocumentUpdate(filename="original-import.html"), actor_agent_id=owner.id)
    else:
        item = await datasets.record(identity, owner.id)
        await datasets.set_grant(identity, owner.id, kind="agent", principal=reader.id,
            can_write=False, expected_lock_version=item.lock_version)
        history_model = DatasetRevision
        history_key = DatasetRevision.dataset_id
    before = await resource_info(ctx, created.uri, include_checksum=True)
    previous = await resource_read(ctx, created.uri)
    revisions = list(await db.scalars(select(history_model.id).where(history_key == identity)))
    denied_ctx = ResourceContext(agent_id=reader.id, runtime="internal")
    assert "rename" in before.capabilities
    assert "rename" not in (await resource_info(denied_ctx, created.uri)).capabilities
    with pytest.raises((documents.DocumentPermissionError, datasets.DatasetPermissionError)):
        await resource_rename(denied_ctx, created.uri, "Denied", expected_lock_version=before.lock_version)
    renamed = json.loads(await file_mcp.rename_file(McpToolContext(agent_id=owner.id, runtime="internal"),
        created.uri, " ARCHIVE — Synthetic / retained ", expected_lock_version=before.lock_version))
    after = await resource_info(ctx, created.uri, include_checksum=True)
    assert renamed["uri"] == renamed["source_uri"] == created.uri
    assert renamed["name"] == after.name == "ARCHIVE — Synthetic / retained"
    assert renamed["operation"] == "rename"
    assert renamed["lock_version"] == after.lock_version > before.lock_version
    assert after.revision == before.revision == renamed["revision"]
    assert after.checksum == before.checksum
    assert (await resource_read(ctx, created.uri)).content == previous.content
    assert (await resource_read(denied_ctx, created.uri)).content == previous.content
    assert "rename" not in (await resource_info(denied_ctx, created.uri)).capabilities
    assert (await resource_read(ctx, attachment.uri)).content == "Synthetic attachment"
    assert list(await db.scalars(select(history_model.id).where(history_key == identity))) == revisions
    hits = await resource_search(ctx, f"{scheme}://", "ARCHIVE", mode="name")
    assert created.uri in [hit.resource.uri for hit in hits.hits]
    # A title conflict cannot be detected with the unchanged content revision.
    with pytest.raises((documents.DocumentConflictError, datasets.DatasetConflictError)):
        await resource_rename(ctx, created.uri, "Stale rename", expected_lock_version=before.lock_version)
    # Changing the body also invalidates the metadata token.
    replacement = b"<p>Updated synthetic content.</p>" if scheme == "document" else b'{"updated":true}'
    await resource_write(ctx, created.uri, replacement, expected_revision=after.revision)
    with pytest.raises((documents.DocumentConflictError, datasets.DatasetConflictError)):
        await resource_rename(ctx, created.uri, "Stale after edit", expected_lock_version=after.lock_version)
    assert (await resource_info(ctx, created.uri)).name == renamed["name"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["document", "data"])
@pytest.mark.parametrize("name,version", [("Valid", None), ("   ", 1), ("x" * 501, 1), ("bad\nname", 1)])
async def test_invalid_native_rename_has_no_effect(db, agents, memory_storage, scheme, name, version):
    ctx = ResourceContext(agent_id=agents[0].id, runtime="internal")
    created = await resource_create(ctx, f"{scheme}://", b"<p>Kept.</p>" if scheme == "document" else b"{}", name="Synthetic original")
    before = await resource_info(ctx, created.uri)
    with pytest.raises(ValueError):
        await resource_rename(ctx, created.uri, name, expected_lock_version=version)
    after = await resource_info(ctx, created.uri)
    assert (after.name, after.revision, after.lock_version) == (before.name, before.revision, before.lock_version)


@pytest.mark.asyncio
async def test_rename_keeps_goal_controlled_titles_and_read_only_datasets_protected(db, agents, memory_storage):
    from app.document.schemas import DocumentItemCreate, DocumentPayload

    owner = agents[0]
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    goal_document, _ = await documents.create_item(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic Goal title", payload=DocumentPayload(text="<p>Goal content.</p>"),
        metadata={"goal_document_kind": "description"}))
    uri = f"document://{goal_document.id}"
    info = await resource_info(ctx, uri)
    assert "rename" not in info.capabilities
    with pytest.raises(documents.DocumentPermissionError, match="controlled by its Goal"):
        await resource_rename(ctx, uri, "Denied", expected_lock_version=info.lock_version)
    dataset = await datasets.create(owner.id, title="Synthetic read only", content="{}")
    await datasets.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version, values={"read_only": True})
    uri = f"data://{dataset.id}"
    info = await resource_info(ctx, uri)
    assert "rename" not in info.capabilities
    with pytest.raises(datasets.DatasetPermissionError):
        await resource_rename(ctx, uri, "Denied", expected_lock_version=info.lock_version)


@pytest.mark.asyncio
async def test_path_rename_preserves_parent_and_bytes_and_rejects_collisions(monkeypatch, tmp_path):
    transport = TemporaryFileTransport(tmp_path)
    monkeypatch.setattr(resource_service, "_console_transport", AsyncMock(return_value=transport))
    ctx = ResourceContext(agent_id=7, runtime="internal")
    (tmp_path / "Folder").mkdir()
    (tmp_path / "Folder" / "old.txt").write_bytes(b"Synthetic unchanged bytes")
    result = await resource_rename(ctx, "console://Folder/old.txt", "new é.txt")
    assert result.uri == "console://Folder/new%20%C3%A9.txt"
    assert (tmp_path / "Folder" / "new é.txt").read_bytes() == b"Synthetic unchanged bytes"
    assert not (tmp_path / "Folder" / "old.txt").exists()
    (tmp_path / "Folder" / "occupied.txt").write_bytes(b"Synthetic other file")
    with pytest.raises(FileExistsError):
        await resource_rename(ctx, result.uri, "occupied.txt")
    for name in ("../escape", "sub/name", "sub\\name", ".."):
        with pytest.raises(ValueError):
            await resource_rename(ctx, result.uri, name)
    assert (tmp_path / "Folder" / "occupied.txt").read_bytes() == b"Synthetic other file"


@pytest.mark.asyncio
async def test_rename_scope_is_an_existing_target_mutation():
    from app.agent.execution_scope import admitted_scope, preflight

    definition = next(tool for tool in load_mcp_tools() if tool.name == "file_rename")
    assert definition.conversation_policy == "short"
    allowed = f"document://{uuid4()}"
    other = f"data://{uuid4()}"
    scope = admitted_scope(uuid4(), f"Rename {allowed}")
    assert preflight(scope, definition.effect_descriptor, definition.name,
        {"uri": allowed, "name": "New title"}).decision == "allow"
    assert preflight(scope, definition.effect_descriptor, definition.name,
        {"uri": other, "name": "Denied"}).decision == "clarify"


@pytest.mark.asyncio
async def test_legacy_dataset_rename_returns_the_canonical_uri(db, agents, memory_storage):
    from app.document.tests.legacy_fixtures import legacy_dataset

    owner = agents[0]
    dataset = await legacy_dataset(owner_agent_id=owner.id, title="Synthetic legacy Dataset",
        content='{"kept":true}')
    alias = f"document://{dataset.id}"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    info = await resource_info(ctx, alias)
    renamed = await resource_rename(ctx, alias, "Synthetic renamed Dataset", expected_lock_version=info.lock_version)
    assert renamed.uri == info.uri == f"data://{dataset.id}"
    assert (await resource_info(ctx, alias)).name == renamed.name
    assert (await resource_read(ctx, alias)).content == '{"kept":true}'


@pytest.mark.asyncio
async def test_authorization_snapshot_detects_a_title_change_without_content_revision(monkeypatch):
    from app.file_share import ResourceDescriptor

    uri = f"document://{uuid4()}"
    context = McpToolContext(agent_id=7, runtime="internal")
    monkeypatch.setattr(file_mcp, "_resource_context",
        AsyncMock(return_value=ResourceContext(agent_id=7, runtime="internal")))
    descriptor = ResourceDescriptor(uri=uri, name="First", revision=1, lock_version=2)
    info = AsyncMock(return_value=descriptor)
    monkeypatch.setattr(file_mcp, "resource_info", info)
    before = await file_mcp._file_preflight(context, {"uri": uri, "name": "Intended"})
    info.return_value = descriptor.model_copy(update={"name": "Concurrent rename", "lock_version": 3})
    after = await file_mcp._file_preflight(context, {"uri": uri, "name": "Intended"})
    assert before["uri"]["revision"] == after["uri"]["revision"]
    assert before != after
