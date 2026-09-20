from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import select

from app.memory import service, document_attachment_service as attachments
from app.memory.document_service import create_document, read_document
from app.memory.models import MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemoryGrantUpdate, MemorySearchRequest
from core.util.rich_text import RichTextError


def png():
    output = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "memory_type,node_kind", [(kind, "memory") for kind in ["core", "working", "episodic", "semantic", "procedural", "social"]] + [("working", "document")]
)
async def test_all_editorial_categories_normalize_and_index_visible_text(
    agents, memory_storage, memory_type, node_kind
):
    owner, _ = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Corpus",
            memory_type=memory_type,
            node_kind=node_kind,
            media_type="text/html",
            payload=MemoryPayload(text="<h2>Été</h2><p><u>Visible</u></p>"),
        )
    )
    assert item.media_type == "text/html"
    assert item.content_profile == ("document" if node_kind == "document" else "rich-text")
    assert item.search_text == "Été\nVisible"
    assert item.content_profile_version == 1
    results = await service.search_items(MemorySearchRequest(agent_id=owner.id, query="Visible"))
    assert [hit.item.id for hit in results.hits] == [item.id]
    assert "summary" not in results.hits[0].item.model_dump()
    assert "Visible" in results.hits[0].excerpt
    revisions = await service.list_revisions(item.id, agent_id=owner.id)
    assert all("summary" not in revision.model_dump() for revision in revisions)
    original_revision = item.revision
    identical = await service.update_item(
        item.id,
        MemoryItemUpdate(
            expected_revision=original_revision,
            media_type="text/html",
            payload=MemoryPayload(text="<h2>Été</h2><p><u>Visible</u></p>"),
        ),
        actor_agent_id=owner.id,
    )
    assert identical.revision == original_revision
    with pytest.raises(RichTextError):
        await service.update_item(
            item.id,
            MemoryItemUpdate(
                payload=MemoryPayload(text='<img src="https://example.com/image.png">')
            ),
            actor_agent_id=owner.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("node_kind,protected", [("document", True), ("memory", False)])
async def test_interactive_content_remains_forbidden_outside_regular_documents(agents, memory_storage, node_kind, protected):
    owner, _ = agents
    data = MemoryItemCreate(owner_agent_id=owner.id, title="Report", memory_type="working", node_kind=node_kind,
        media_type="text/html", payload=MemoryPayload(text='<p>Report</p><script>alert(1)</script>'))
    with pytest.raises(RichTextError):
        await service.create_item(data, deletion_protected=protected)


@pytest.mark.asyncio
async def test_inline_images_history_and_current_access(agents, memory_storage, db):
    owner, peer = agents
    document = await create_document(
        owner_agent_id=owner.id, title="Image document", content="<p>Before</p>", task_id=None
    )
    attachment = await attachments.add_document_attachment_bytes(
        document.id,
        actor_agent_id=owner.id,
        name="image.png",
        media_type="image/png",
        content=png(),
    )
    uri = f"document://{document.id}/attachments/{attachment.id}"
    body = f'<p>After</p><img src="{uri}" alt="blue" width="400">'
    updated = await service.update_item(
        document.id,
        MemoryItemUpdate(
            expected_revision=document.revision,
            media_type="text/html",
            payload=MemoryPayload(text=body),
        ),
        actor_agent_id=owner.id,
    )
    revision = updated.revision
    unchanged = await service.update_item(
        document.id,
        MemoryItemUpdate(expected_revision=revision, payload=MemoryPayload(text=body)),
        actor_agent_id=owner.id,
    )
    assert unchanged.revision == revision
    snapshot = await db.scalar(
        select(MemoryRevision).where(
            MemoryRevision.item_id == document.id, MemoryRevision.revision == revision
        )
    )
    assert snapshot.metadata_["content_images"] == [uri]
    await service.set_item_grant(
        document.id, peer.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id
    )
    await attachments.delete_document_attachment(
        document.id, attachment.id, actor_agent_id=owner.id
    )
    assert await attachments.list_document_attachments(document.id, actor_agent_id=peer.id) == []
    assert (
        await attachments.read_document_attachment(
            document.id, attachment.id, actor_agent_id=peer.id
        )
    )[1] == png()
    await service.remove_item_grant(document.id, peer.id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryPermissionError):
        await attachments.read_document_attachment(
            document.id, attachment.id, actor_agent_id=peer.id
        )
    other = await create_document(
        owner_agent_id=owner.id, title="Other", content="<p>Other</p>", task_id=None
    )
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(
            other.id, MemoryItemUpdate(payload=MemoryPayload(text=body)), actor_agent_id=owner.id
        )
    with pytest.raises(service.MemoryPermissionError):
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
    with pytest.raises(service.MemoryPermissionError):
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


@pytest.mark.asyncio
async def test_active_html_file_is_not_an_editorial_fragment(agents, memory_storage):
    from app.memory.acquisition_service import create_manual_item

    owner, _ = agents
    source = "<html><script>window.example = true</script><body>Artifact</body></html>"
    item = await create_manual_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Native HTML",
            content_type="file",
            media_type="text/html",
            payload=MemoryPayload(text=source),
        )
    )
    assert item.content_profile_version is None
    _, body, _, _, _ = await service.get_item(item.id, agent_id=owner.id)
    assert body.decode() == source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "format_change",
    [
        {"media_type": "text/xml"},
        {"media_type": "application/json", "content_type": "json"},
        {"content_type": "binary"},
    ],
)
async def test_editorial_format_cannot_be_changed_to_bypass_image_validation(
    agents, memory_storage, format_change
):
    owner, _ = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Protected editorial format",
            memory_type="semantic",
            media_type="text/html",
            payload=MemoryPayload(text="<p>Original</p>"),
        )
    )
    with pytest.raises(service.MemoryConflictError, match="text/html profile"):
        await service.update_item(
            item.id,
            MemoryItemUpdate(
                **format_change,
                payload=MemoryPayload(text='<img src="https://example.com/image.png">'),
            ),
            actor_agent_id=owner.id,
        )
    assert item.media_type == "text/html"
    assert item.revision == 1
