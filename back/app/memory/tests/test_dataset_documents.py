"""Datasets share the document lifecycle while preserving their JSON contract."""

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.file_share import resource_service as files
from app.file_share.resource_contracts import ResourceContext
from app.memory import document_service, service
from app.memory.schemas import DocumentLibraryRequest, MemoryGrantUpdate, MemoryItemUpdate, MemoryPayload


@pytest.mark.asyncio
async def test_dataset_file_lifecycle_keeps_json_rights_and_history(agents, memory_storage):
    owner, reader = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    source = '{\n  "label": "<strong>Literal HTML</strong>",\n  "amount": 1200\n}\n'
    created = await files.resource_create(ctx, "document://", source.encode(), name="Scenarios", document_type="dataset")
    identity = UUID(created.uri.removeprefix("document://"))
    info = await files.resource_info(ctx, created.uri)
    assert info.metadata["document_type"] == "dataset"
    assert info.media_type == "application/json"
    first = await files.resource_read(ctx, created.uri, max_chars=15)
    second = await files.resource_read(ctx, created.uri, offset=first.next_offset, max_chars=2000)
    assert first.content + second.content == source
    assert first.revision == 1

    reader_ctx = ResourceContext(agent_id=reader.id, runtime="internal")
    with pytest.raises(service.MemoryPermissionError):
        await files.resource_read(reader_ctx, created.uri)
    await service.set_item_grant(identity, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert (await files.resource_read(reader_ctx, created.uri)).content == source
    with pytest.raises(service.MemoryPermissionError):
        await files.resource_write(reader_ctx, created.uri, b"{}", expected_revision=1)
    with pytest.raises(service.MemoryConflictError):
        await files.resource_write(ctx, created.uri, b"{}")

    edited = await files.resource_edit(ctx, created.uri, start_line=3, end_line=3,
        content='  "amount": 2400', expected_revision=1)
    assert edited.revision == 2
    changed = await files.resource_read(ctx, created.uri)
    assert json.loads(changed.content)["amount"] == 2400
    assert "<strong>Literal HTML</strong>" in changed.content
    with pytest.raises(service.MemoryConflictError):
        await files.resource_write(ctx, created.uri, b"{}", expected_revision=1)
    unchanged = await files.resource_write(ctx, created.uri, changed.content.encode(), expected_revision=2)
    assert unchanged.revision == 2
    restored = await service.restore_document_content_revision(identity, 1, expected_revision=2, actor_agent_id=owner.id)
    assert restored.document_type == "dataset"
    assert restored.media_type == "application/json"
    assert restored.revision == 3
    assert (await files.resource_read(reader_ctx, created.uri)).content == source
    history = await service.get_document_content_revision(identity, 2, actor_agent_id=owner.id)
    assert history.media_type == "application/json"
    assert json.loads(history.content)["amount"] == 2400

    copied = await files.resource_copy(ctx, created.uri, "document://")
    assert copied.uri != created.uri
    assert (await files.resource_info(ctx, copied.uri)).metadata["document_type"] == "dataset"
    assert (await files.resource_read(ctx, copied.uri)).content == source
    with pytest.raises(service.MemoryPermissionError):
        await files.resource_read(reader_ctx, copied.uri)
    with pytest.raises(ValueError):
        await files.resource_append(ctx, created.uri, '{"extra":true}', expected_revision=3)
    assert (await files.resource_read(ctx, created.uri)).revision == 3
    appended = await files.resource_append(ctx, created.uri, "\n", expected_revision=3)
    assert appended.revision == 4
    assert (await files.resource_read(ctx, created.uri)).content == source + "\n"
    overwritten = await files.resource_copy(ctx, copied.uri, created.uri, overwrite=True)
    assert overwritten.uri == created.uri
    assert (await files.resource_info(ctx, created.uri)).metadata["document_type"] == "dataset"
    assert (await files.resource_read(ctx, created.uri)).content == source
    await service.remove_item_grant(identity, reader.id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await service.get_document_content_revision(identity, 1, actor_agent_id=reader.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [b"", b"{", b'{"x": NaN}', b'{"x": Infinity}', b"<p>HTML</p>", b"\xff"])
async def test_invalid_dataset_never_creates_or_replaces_a_revision(agents, memory_storage, invalid):
    owner, _ = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    with pytest.raises(ValueError):
        await files.resource_create(ctx, "document://", invalid, document_type="dataset")
    created = await files.resource_create(ctx, "document://", b'{"safe":true}', document_type="dataset")
    with pytest.raises(ValueError):
        await files.resource_write(ctx, created.uri, invalid, expected_revision=1)
    current = await files.resource_read(ctx, created.uri)
    assert current.content == '{"safe":true}'
    assert current.revision == 1


@pytest.mark.asyncio
async def test_document_type_is_fixed_and_library_filters_and_sorts_both_types(agents, memory_storage):
    owner, _ = agents
    html = await document_service.create_document(owner_agent_id=owner.id, title="A report", content="<p>Report</p>", task_id=None)
    dataset = await document_service.create_document(owner_agent_id=owner.id, title="Z scenarios", content='{"amount":1200}', task_id=None, document_type="dataset")
    assert html.document_type == "html"
    for item, media, content in [(html, "application/json", "{}"), (dataset, "text/html", "<p>Invalid</p>")]:
        with pytest.raises(service.MemoryConflictError):
            await service.update_item(item.id, MemoryItemUpdate(expected_revision=1, media_type=media, payload=MemoryPayload(text=content)), actor_agent_id=owner.id)
        with pytest.raises(ValidationError):
            MemoryItemUpdate.model_validate({"document_type": "html" if item == dataset else "dataset"})
    page = await service.browse_document_library(DocumentLibraryRequest(sort_by="document_type"), managed_agent_ids=frozenset({owner.id}))
    assert [entry.item.id for entry in page.entries] == [dataset.id, html.id]
    filtered = await service.browse_document_library(DocumentLibraryRequest(document_type="dataset"), managed_agent_ids=frozenset({owner.id}))
    assert filtered.total == 1
    assert [entry.item.id for entry in filtered.entries] == [dataset.id]
    updated = await service.update_item(dataset.id, MemoryItemUpdate(title="Renamed scenarios", keywords=["finance"]), actor_agent_id=owner.id)
    assert updated.revision == 1
    assert updated.document_type == "dataset"


@pytest.mark.asyncio
async def test_document_type_option_is_rejected_outside_document_creation(agents, memory_storage):
    owner, _ = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    with pytest.raises(ValueError, match="document_type"):
        await files.resource_create(ctx, "console://sample.json", b"{}", document_type="dataset")


@pytest.mark.parametrize("source", [b"null", b"true", b"42", b'"value"', b"[1,2]", b"{}"])
def test_datasets_accept_every_json_root_type(source):
    from app.memory.document_types import validate_dataset

    validate_dataset(source)


def test_dataset_limit_rejects_oversized_json():
    from app.memory.document_types import validate_dataset

    with pytest.raises(ValueError, match="exceeds"):
        validate_dataset(b'"' + b"x" * 2_000_000 + b'"')
