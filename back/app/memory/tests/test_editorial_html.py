from io import BytesIO

from PIL import Image
import pytest
from sqlalchemy import select

from app.memory import service
from app.document import document_attachment_service as attachments
from app.document.document_service import create_document, read_document
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemorySearchRequest
from app.document.schemas import DocumentGrantUpdate
from core.util.rich_text import RichTextError


def png():
    output = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(output, format="PNG")
    return output.getvalue()






@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_kind", ["memory"]
)
async def test_all_editorial_categories_normalize_and_index_visible_text(
    agents, memory_storage, node_kind
):
    owner, _ = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="Corpus",
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
    from app.document.schemas import DocumentItemCreate, DocumentPayload
    from app.document import resource_service as documents
    create = documents.create_item if node_kind == "document" else service.create_item
    model = DocumentItemCreate if node_kind == "document" else MemoryItemCreate
    payload = DocumentPayload if node_kind == "document" else MemoryPayload
    data = model(owner_agent_id=owner.id, title="Report",  node_kind=node_kind,
        media_type="text/html", payload=payload(text='<p>Report</p><script>alert(1)</script>'))
    with pytest.raises(RichTextError):
        await create(data, deletion_protected=protected)








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
