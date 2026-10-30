"""Imports preserve content and create independent typed documents."""

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.agent import AgentManagementScope
from app.document import file_import, resource_service
from app.document.file_import import DocumentImportSource, convert_document_import, UnsupportedDocumentImport
from app.document.models import Document, DocumentRevision, DocumentSource, DocumentAttachment
from app.document.router import create_managed_document
from app.document.schemas import DocumentCreate, DocumentImportReference


@pytest.mark.parametrize("name,mime,content,kind,expected", [
    ("source.JSON", "application/octet-stream", b' {"value": 42}\n', "data", ' {"value": 42}\n'),
    ("source", "application/json; charset=utf-8", b"null", "data", "null"),
    ("source.html", "text/html", b'<!doctype html><html><head><style>p {color:red}</style></head><body><p>Text</p></body></html>',
     "text", '<style>p {color:red}</style><p>Text</p>'),
    ("source.html", "text/html", b'<!doctype html><html lang="en"><head><meta charset="UTF-8"><title>Source</title></head><body class="page"><!-- comment --><p>Text &amp; more</p><script>window.example = 1</script></body></html>',
     "text", '<div lang="en"><div class="page"><p>Text &amp; more</p><script>window.example = 1</script></div></div>'),
    ("source.md", "text/plain", b"# Heading\n\n**Important**", "text", "<h1>Heading</h1><p><strong>Important</strong></p>"),
    ("source.txt", "text/plain", b"<example> & text", "text", "<p>&lt;example&gt; &amp; text</p>"),
    ("source.txt", "application/octet-stream", b"\xef\xbb\xbfUTF-8", "text", "<p>UTF-8</p>"),
])
def test_supported_import_formats(name, mime, content, kind, expected):
    assert convert_document_import(DocumentImportSource(name, mime, content)) == (kind, expected)


def test_native_document_type_takes_precedence_over_its_title_extension():
    assert convert_document_import(DocumentImportSource("Report.json", "text/html", b"<p>Report</p>", "text")) == ("text", "<p>Report</p>")


@pytest.mark.parametrize("kind", ["text", "data"])
def test_document_import_uses_the_configured_resource_quota(monkeypatch, kind):
    from core.params import runtime_settings
    monkeypatch.setattr(runtime_settings, "MEMORY_RESOURCE_MAX_BYTES", 1024)
    source = DocumentImportSource("source.html" if kind == "text" else "source.json",
        "text/html" if kind == "text" else "application/json", b"a" * 1025)
    with pytest.raises(ValueError, match="configured.*quota"):
        convert_document_import(source)


@pytest.mark.parametrize("name,mime,content,error", [
    ("source.png", "image/png", b"PNG", UnsupportedDocumentImport),
    ("source.json", "application/json", b'{"invalid":', ValueError),
    ("source.json", "application/json", b'{"key":1,"key":2}', ValueError),
    ("source.txt", "text/plain", b"\xff", UnicodeError),
    ("source.txt", "text/plain", b"\x00", ValueError),
])
def test_invalid_import_is_rejected(name, mime, content, error):
    with pytest.raises(error):
        convert_document_import(DocumentImportSource(name, mime, content))


@pytest.mark.asyncio
@pytest.mark.parametrize("name,mime,source,kind", [
    ("report.md", "text/markdown", b"# Synthetic report", "text"),
    ("values.json", "application/json", b' {"value": 7}\n', "data"),
])
async def test_creation_is_a_snapshot_without_source_link(db, agents, memory_storage, monkeypatch, name, mime, source, kind):
    from app.document import router
    owner, other = agents
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    async def current_scope():
        return scope
    async def read(uri, agent_id, actual_scope):
        assert uri == "synthetic://source" and agent_id == owner.id and actual_scope == scope
        return DocumentImportSource(name, mime, source)
    monkeypatch.setattr(router, "current_management_scope", current_scope)
    monkeypatch.setattr(file_import, "_reader", read)
    request = DocumentCreate(owner_kind="agent", owner_id=owner.id, actor_agent_id=owner.id,
        title="Synthetic imported document", import_from=DocumentImportReference(uri="synthetic://source", agent_id=owner.id))
    created = await create_managed_document(request)
    # Losing the source after creation cannot change the imported document or its history.
    monkeypatch.setattr(file_import, "_reader", None)
    item, content, *_ = await resource_service.get_item(created.id, agent_id=owner.id)
    assert item.document_type == kind and item.revision == 1
    assert content.decode() == convert_document_import(DocumentImportSource(name, mime, source))[1]
    assert "synthetic://source" not in str(item.metadata_)
    assert await db.scalar(select(func.count()).select_from(DocumentSource).where(DocumentSource.document_id == item.id)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentAttachment).where(DocumentAttachment.document_id == item.id)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == item.id)) == 1
    with pytest.raises((resource_service.DocumentPermissionError, resource_service.DocumentNotFoundError)):
        await resource_service.get_item(created.id, agent_id=other.id)


@pytest.mark.asyncio
async def test_import_failures_create_no_document(db, agents, memory_storage, monkeypatch):
    from app.document import router
    owner, other = agents
    async def scope():
        return AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    async def unsupported(*args):
        return DocumentImportSource("image.png", "image/png", b"synthetic")
    monkeypatch.setattr(router, "current_management_scope", scope)
    monkeypatch.setattr(file_import, "_reader", unsupported)
    before = await db.scalar(select(func.count()).select_from(Document))
    for source_agent, expected in ((owner.id, 415), (other.id, 404)):
        with pytest.raises(HTTPException) as failure:
            await create_managed_document(DocumentCreate(owner_kind="agent", owner_id=owner.id,
                actor_agent_id=owner.id, title="Rejected import", import_from=DocumentImportReference(uri="synthetic://source", agent_id=source_agent)))
        assert failure.value.status_code == expected
    assert await db.scalar(select(func.count()).select_from(Document)) == before


@pytest.mark.asyncio
async def test_native_document_copy_keeps_its_own_images_and_attachments(db, agents, memory_storage, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from core.user import HumanActor
    from core.storage import file_path
    from app.document import document_service, document_attachment_service as attachments, router
    from app.document.document_cloning import DocumentCloneSource, prepare_document_clone
    from app.document.schemas import DocumentPayload, DocumentUpdate
    owner, _ = agents
    actor = HumanActor(owner.user_id)
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    async def current_scope():
        return scope
    source = await document_service.create_user_document(owner_user_id=owner.user_id, editor_agent_id=None,
        title="Synthetic source.json", content="<p>Image</p>")
    output = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    image = await attachments.add_document_attachment_bytes(source.id, actor_agent_id=actor,
        name="Synthetic.png", media_type="image/png", content=output.getvalue())
    old_uri = f"document://{source.id}/attachments/{image.id}"
    source = await resource_service.update_item(source.id, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(text=f'<p>Image</p><img src="{old_uri}" alt="Synthetic">')), actor_agent_id=actor)
    source_id = source.id
    # Removing an attachment from the visible list retains images still cited in the body.
    await attachments.delete_document_attachment(source_id, image.id, actor_agent_id=actor)
    async def read(uri, agent_id, actual_scope):
        return await file_import.read_native_document_import(source_id, actual_scope)
    monkeypatch.setattr(file_import, "_reader", read)
    monkeypatch.setattr(router, "current_management_scope", current_scope)
    clone = await create_managed_document(DocumentCreate(owner_kind="user", owner_id=owner.user_id,
        title="Synthetic copied image", import_from=DocumentImportReference(uri=f"document://{source_id}", agent_id=owner.id)))
    copied = await attachments.list_document_attachments(clone.id, actor_agent_id=actor)
    assert len(copied) == 1 and copied[0].id != image.id
    copied_uri = f"document://{clone.id}/attachments/{copied[0].id}"
    item, content, *_ = await resource_service.get_item(clone.id, agent_id=actor)
    assert item.revision == 1 and copied_uri in content.decode() and old_uri not in content.decode()
    assert (await attachments.read_document_attachment(clone.id, copied[0].id, actor_agent_id=actor))[1] == output.getvalue()
    # Failed preparation must remove unpublished copies and retain the original bytes.
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        async with prepare_document_clone(DocumentCloneSource(source_id, actor), f'<img src="{old_uri}" alt="Synthetic">') as abandoned:
            abandoned_files = [file_path(attachment.id) for attachment in abandoned.attachments]
            raise RuntimeError("Synthetic interruption")
    assert abandoned_files and all(not path.exists() for path in abandoned_files)
    assert file_path(image.id).is_file()
    await resource_service.delete_document(source_id, actor_agent_id=actor)
    assert (await attachments.read_document_attachment(clone.id, copied[0].id, actor_agent_id=actor))[1] == output.getvalue()
