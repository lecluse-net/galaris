from io import BytesIO
from PIL import Image
import pytest
from sqlalchemy import select
from app.document import resource_service as service, DocumentRevision
from app.document import document_attachment_service as attachments
from app.document.document_service import create_document, read_document
from app.document.schemas import DocumentUpdate, DocumentPayload, DocumentGrantUpdate
from core.util.rich_text import RichTextError

def png():
    output = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_checklist_state_is_document_content_with_independent_revisions(agents, memory_storage, db):
    owner, reader = agents
    unchecked = '<ul class="galaris-checklist"><li data-checked="false"><p>Review draft</p></li></ul>'
    checked = unchecked.replace('data-checked="false"', 'data-checked="true"')
    document = await create_document(owner_agent_id=owner.id, title="Synthetic checklist", content=unchecked, task_id=None)
    updated = await service.update_item(document.id, DocumentUpdate(expected_revision=1, payload=DocumentPayload(text=checked)), actor_agent_id=owner.id)
    assert updated.revision == 2
    await service.set_item_grant(document.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    reopened = await read_document(document.id, actor_agent_id=reader.id, task_id=None)
    assert reopened["content"] == checked
    snapshots = (await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == document.id).order_by(DocumentRevision.revision))).all()
    assert [snapshot.revision for snapshot in snapshots] == [1, 2]
    with pytest.raises(service.DocumentPermissionError):
        await service.update_item(document.id, DocumentUpdate(expected_revision=2, payload=DocumentPayload(text=unchecked)), actor_agent_id=reader.id)
    assert (await read_document(document.id, actor_agent_id=owner.id, task_id=None))["content"] == checked

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "append", "edit", "write"])
async def test_document_writes_preserve_prose_about_a_secret(agents, memory_storage, operation):
    from app.file_share import ResourceContext, resource_service

    owner, _ = agents
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    # Entirely synthetic prose: a long valid block must not acquire an arbitrary
    # size restriction just because a common noun precedes a colon.
    passage = "<p>Voici notre secret : les étoiles éclairent le jardin. " + "Un nouveau détail. " * 250 + "</p>"
    document = await create_document(owner_agent_id=owner.id, title="Synthetic story", content="<p>Original</p>", task_id=None)
    uri = f"document://{document.id}"

    if operation == "create":
        created = await resource_service.resource_create(ctx, "document://", passage.encode(), name="Synthetic prose")
        uri = created.uri
    elif operation == "append":
        await resource_service.resource_append(ctx, uri, passage, expected_revision=1)
    elif operation == "edit":
        await resource_service.resource_edit(ctx, uri, start_line=1, end_line=1, content=passage, expected_revision=1)
    else:
        await resource_service.resource_write(ctx, uri, passage.encode(), expected_revision=1)

    current = await resource_service.resource_read(ctx, uri)
    assert passage in current.content
    assert current.revision == (1 if operation == "create" else 2)
    if operation == "append":
        assert "<p>Original</p>" in current.content

    unsafe = "<p>secret : synthetic-credential</p>"
    with pytest.raises(ValueError, match="credential-like"):
        if operation == "create":
            await resource_service.resource_create(ctx, "document://", unsafe.encode(), name="Unsafe prose")
        elif operation == "append":
            await resource_service.resource_append(ctx, uri, unsafe, expected_revision=current.revision)
        elif operation == "edit":
            await resource_service.resource_edit(ctx, uri, start_line=1, end_line=1, content=unsafe, expected_revision=current.revision)
        else:
            await resource_service.resource_write(ctx, uri, unsafe.encode(), expected_revision=current.revision)
    unchanged = await resource_service.resource_read(ctx, uri)
    assert unchanged.content == current.content
    assert unchanged.revision == current.revision


@pytest.mark.asyncio
async def test_file_mutation_diagnostics_preserve_document_content_and_revision(agents, memory_storage):
    from app.file_share.resource_contracts import ResourceContext
    from app.file_share import resource_service
    from app.file_share.resource_uri import ResourceRevisionConflict, ResourceValidationError
    from app.tools.tool_errors import classify_tool_failure

    owner, peer = agents
    document = await create_document(owner_agent_id=owner.id, title="Editable report", content="<p>First</p><p>Second</p>", task_id=None)
    uri = f"document://{document.id}"
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    before = await resource_service.resource_read(ctx, uri)
    await resource_service.resource_append(ctx, uri, "<p>Third</p>", expected_revision=before.revision)
    current = await resource_service.resource_read(ctx, uri)
    assert current.revision == before.revision + 1
    assert "Third" in current.content

    with pytest.raises(ResourceRevisionConflict) as stale:
        await resource_service.resource_edit(ctx, uri, start_line=1, end_line=1, content="<p>Stale</p>", expected_revision=before.revision)
    assert "file_read" in classify_tool_failure(stale.value).detail
    with pytest.raises(ResourceValidationError) as missing:
        await resource_service.resource_append(ctx, uri, "<p>No revision</p>")
    assert "expected_revision" in classify_tool_failure(missing.value).detail
    with pytest.raises(ResourceValidationError) as bounds:
        await resource_service.resource_edit(ctx, uri, start_line=99, end_line=99, content="<p>Outside</p>", expected_revision=current.revision)
    assert "99-99" in classify_tool_failure(bounds.value).detail
    with pytest.raises(service.DocumentPermissionError):
        await resource_service.resource_append(ResourceContext(agent_id=peer.id, runtime="internal"), uri, "<p>Forbidden</p>", expected_revision=current.revision)
    unchanged = await resource_service.resource_read(ctx, uri)
    assert unchanged.content == current.content
    assert unchanged.revision == current.revision


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type,source", [
    ("image/png", png()),
    ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4" fill="blue"/></svg>'),
])
async def test_inline_images_history_and_current_access(agents, memory_storage, db, media_type, source):
    owner, peer = agents
    document = await create_document(
        owner_agent_id=owner.id, title="Image document", content="<p>Before</p>", task_id=None
    )
    attachment = await attachments.add_document_attachment_bytes(
        document.id,
        actor_agent_id=owner.id,
        name="image.svg" if media_type == "image/svg+xml" else "image.png",
        media_type=media_type,
        content=source,
    )
    uri = f"document://{document.id}/attachments/{attachment.id}"
    body = f'<p>After</p><img src="{uri}" alt="blue" width="400">'
    updated = await service.update_item(
        document.id,
        DocumentUpdate(
            expected_revision=document.revision,
            media_type="text/html",
            payload=DocumentPayload(text=body),
        ),
        actor_agent_id=owner.id,
    )
    revision = updated.revision
    unchanged = await service.update_item(
        document.id,
        DocumentUpdate(expected_revision=revision, payload=DocumentPayload(text=body)),
        actor_agent_id=owner.id,
    )
    assert unchanged.revision == revision
    snapshot = await db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.document_id == document.id, DocumentRevision.revision == revision
        )
    )
    assert snapshot.metadata_["content_images"] == [uri]
    await service.set_item_grant(
        document.id, peer.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id
    )
    await attachments.delete_document_attachment(
        document.id, attachment.id, actor_agent_id=owner.id
    )
    assert await attachments.list_document_attachments(document.id, actor_agent_id=peer.id) == []
    assert (
        await attachments.read_document_attachment(
            document.id, attachment.id, actor_agent_id=peer.id
        )
    )[1] == source
    await service.remove_item_grant(document.id, peer.id, actor_agent_id=owner.id)
    with pytest.raises(service.DocumentPermissionError):
        await attachments.read_document_attachment(
            document.id, attachment.id, actor_agent_id=peer.id
        )
    other = await create_document(
        owner_agent_id=owner.id, title="Other", content="<p>Other</p>", task_id=None
    )
    with pytest.raises(service.DocumentPermissionError):
        await service.update_item(
            other.id, DocumentUpdate(payload=DocumentPayload(text=body)), actor_agent_id=owner.id
        )
    with pytest.raises(service.DocumentPermissionError):
        await create_document(
            owner_agent_id=owner.id,
            title="Cannot reuse another document's image on creation",
            content=body,
            task_id=None,
        )


@pytest.mark.asyncio
async def test_goal_document_rejects_images_from_every_entry(agents, memory_storage):
    owner, _ = agents
    document = await create_document(
        owner_agent_id=owner.id,
        title="Goal tracking",
        content="<p>Tracking</p>",
        task_id=None,
        metadata={"goal_document_kind": "tracking"},
        deletion_protected=True,
    )
    assert document.content_profile == "rich-text"
    with pytest.raises(service.DocumentPermissionError):
        await attachments.add_document_attachment_bytes(
            document.id,
            actor_agent_id=owner.id,
            name="image.png",
            media_type="image/png",
            content=png(),
        )


@pytest.mark.asyncio
async def test_document_pages_are_complete_blocks(agents, memory_storage):
    owner, _ = agents
    document = await create_document(
        owner_agent_id=owner.id,
        title="Blocks",
        content="<h2>One</h2><p>Two</p><p>Three</p>",
        task_id=None,
    )
    first = await read_document(document.id, actor_agent_id=owner.id, task_id=None, max_chars=20)
    assert first["content"] == "<h2>One</h2>"
    assert first["offset_unit"] == "block"
    second = await read_document(
        document.id,
        actor_agent_id=owner.id,
        task_id=None,
        max_chars=20,
        offset=first["next_offset"],
    )
    assert second["content"] == "<p>Two</p>"
