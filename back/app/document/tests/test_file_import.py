"""Imports preserve content and create independent typed documents."""

import pytest
import json
from fastapi import HTTPException
from sqlalchemy import func, select

from app.agent import AgentManagementScope
from app.document import file_import, resource_service
from app.document.file_import import DocumentImportSource, convert_document_import, UnsupportedDocumentImport
from app.document.models import Document, DocumentRevision, DocumentSource, DocumentAttachment
from app.document.router import create_managed_document
from app.document.schemas import DocumentCreate, DocumentImportReference


@pytest.mark.asyncio
async def test_uploaded_import_http_preserves_content_and_enforces_validation_and_access(client, monkeypatch, tmp_path):
    from core.params import runtime_settings

    path = "/api/documents/import"
    upload = {"file": ("Synthetic report.md", b"# Synthetic report", "text/markdown")}
    assert (await client.post(path, files=upload)).status_code == 401
    credentials = {"email": "synthetic-upload-owner@example.com", "password": "Synthetic-upload-password-123"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    owner_id = registered.json()["id"]
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    formats = await client.get("/api/documents/import-formats", headers=headers)
    assert formats.status_code == 200
    assert {".pdf", ".docx", ".xls", ".odt"} <= set(formats.json()["extensions"])
    assert ".zip" not in formats.json()["extensions"]
    data = {"owner_kind": "user", "owner_id": owner_id, "title": "Synthetic upload"}
    samples = [
        ("report.md", "application/octet-stream", b"# Synthetic report", "text", "<h1>Synthetic report</h1>"),
        ("values.json", "application/json", b' {"value": 7}\n', "data", ' {"value": 7}\n'),
        ("page.html", "text/html", b"<!doctype html><html><body><p>Synthetic page</p></body></html>", "text", "<p>Synthetic page</p>"),
        ("active.html", "text/html", b'<html><head><script src="/local/library.js"></script></head><body><h1 onclick="run()">Synthetic heading</h1><p>Preserved paragraph</p><script src="https://unapproved.invalid/app.js"></script><script>run()</script></body></html>',
         "text", "<h1>Synthetic heading</h1><p>Preserved paragraph</p>"),
        ("archive.zip", "application/zip", b"synthetic archive", "text", ""),
    ]
    for suffix in (".pdf", ".docx"):
        raw, mime, sentinel = _converted_source(tmp_path, suffix)
        samples.append(("source" + suffix, mime, raw, "text", sentinel))
    for name, mime, content, kind, expected in samples:
        response = await client.post(path, headers=headers, data={"data": json.dumps(data)}, files={"file": (name, content, mime)})
        assert response.status_code == 201, response.text
        item = response.json()
        assert item["document_format"] == kind and item["owner_user_id"] == owner_id
        detail = await client.get(f"/api/documents/{item['id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        converted = name.endswith((".pdf", ".docx"))
        html = detail.json()["item"]["payload"]["text"]
        assert expected in html if converted else html == expected
        attachments = (await client.get(f"/api/documents/{item['id']}/attachments", headers=headers)).json()
        if converted:
            from core.util import image_references
            assert len(attachments) == 1 and attachments[0]["name"] == name
            for reference in image_references(html):
                identifier = reference.rsplit("/", 1)[-1]
                assert identifier != attachments[0]["id"]
                embedded = await client.get(f"/api/documents/{item['id']}/attachments/{identifier}", headers=headers)
                assert embedded.status_code == 200 and embedded.content
        elif name.endswith(".zip"):
            assert len(attachments) == 1 and attachments[0]["name"] == name
            original = await client.get(f"/api/documents/{item['id']}/attachments/{attachments[0]['id']}", headers=headers)
            assert original.status_code == 200 and original.content == content
        else:
            assert attachments == []

    async def document_ids():
        result = await client.post("/api/documents/library", headers=headers, json={"classification": "all"})
        assert result.status_code == 200, result.text
        return {entry["item"]["id"] for entry in result.json()["entries"]}

    before = await document_ids()
    monkeypatch.setattr(runtime_settings, "MEMORY_RESOURCE_MAX_BYTES", 1024)
    for name, mime, content, status in [
        ("invalid.json", "application/json", b'{"value":', 422),
        ("invalid.txt", "text/plain", b"\xff", 422),
        ("large.txt", "text/plain", b"x" * 1025, 422),
    ]:
        response = await client.post(path, headers=headers, data={"data": json.dumps(data)}, files={"file": (name, content, mime)})
        assert response.status_code == status, response.text
    for invalid in ({**data, "import_from": {"uri": "synthetic://source", "agent_id": 1}},
                    {**data, "owner_kind": "agent", "actor_agent_id": owner_id + 1}, {**data, "title": ""}):
        response = await client.post(path, headers=headers, data={"data": json.dumps(invalid)}, files=upload)
        assert response.status_code == 422, response.text
    assert await document_ids() == before
    monkeypatch.setattr(runtime_settings, "ALLOW_USER_REGISTRATION", True)
    other = {"email": "synthetic-upload-visitor@example.com", "password": "Synthetic-visitor-password-123"}
    assert (await client.post("/api/auth/register", json=other)).status_code == 201
    login = await client.post("/api/auth/login-json", json=other)
    headers["Authorization"] = "Bearer " + login.json()["access_token"]
    denied = await client.post(path, headers=headers, data={"data": json.dumps(data)}, files=upload)
    assert denied.status_code == 403, denied.text


@pytest.mark.parametrize("name,mime,content,kind,expected", [
    ("source.JSON", "application/octet-stream", b' {"value": 42}\n', "data", ' {"value": 42}\n'),
    ("source", "application/json; charset=utf-8", b"null", "data", "null"),
    ("source.html", "text/html", b'<!doctype html><html><head><style>p {color:red}</style></head><body><p>Text</p></body></html>',
     "text", '<style>p {color:red}</style><p>Text</p>'),
    ("source.html", "text/html", b'<!doctype html><html lang="en"><head><meta charset="UTF-8"><title>Source</title></head><body class="page"><!-- comment --><p>Text &amp; more</p><script>window.example = 1</script></body></html>',
     "text", '<div lang="en"><div class="page"><p>Text &amp; more</p></div></div>'),
    ("source.html", "text/html", b'<h1 onclick="run()">Heading</h1><script src="https://unapproved.invalid/library.js"></script><p>Kept</p><iframe src="https://example.invalid"><p>Discarded embed</p></iframe><a href="javascript:run()">Link text</a>',
     "text", '<h1>Heading</h1><p>Kept</p><p><a>Link text</a></p>'),
    ("source.md", "text/plain", b"# Heading\n\n**Important**", "text", "<h1>Heading</h1><p><strong>Important</strong></p>"),
    ("source.txt", "text/plain", b"<example> & text", "text", "<p>&lt;example&gt; &amp; text</p>"),
    ("source.txt", "application/octet-stream", b"\xef\xbb\xbfUTF-8", "text", "<p>UTF-8</p>"),
])
def test_supported_import_formats(name, mime, content, kind, expected):
    assert convert_document_import(DocumentImportSource(name, mime, content)) == (kind, expected)


def test_native_document_format_takes_precedence_over_its_title_extension():
    assert convert_document_import(DocumentImportSource("Report.json", "text/html", b"<p>Report</p>", "text")) == ("text", "<p>Report</p>")
    native = '<p>Native application</p><script>window.synthetic = 1</script>'
    assert convert_document_import(DocumentImportSource("Report.html", "text/html", native.encode(), "text")) == ("text", native)


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
    ("archive.zip", "application/zip", b"synthetic archive bytes", "text"),
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
    assert item.document_format == kind and item.revision == 1
    attached_only = name.endswith(".zip")
    assert content.decode() == ("" if attached_only else convert_document_import(DocumentImportSource(name, mime, source))[1])
    assert "synthetic://source" not in str(item.metadata_)
    assert await db.scalar(select(func.count()).select_from(DocumentSource).where(DocumentSource.document_id == item.id)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentAttachment).where(DocumentAttachment.document_id == item.id)) == int(attached_only)
    if attached_only:
        from app.document import document_attachment_service as attachments
        files = await attachments.list_document_attachments(item.id, actor_agent_id=owner.id)
        assert len(files) == 1 and files[0].name == name
        assert (await attachments.read_document_attachment(item.id, files[0].id, actor_agent_id=owner.id))[1] == source
        with pytest.raises((resource_service.DocumentPermissionError, resource_service.DocumentNotFoundError)):
            await attachments.read_document_attachment(item.id, files[0].id, actor_agent_id=other.id)
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == item.id)) == 1
    with pytest.raises((resource_service.DocumentPermissionError, resource_service.DocumentNotFoundError)):
        await resource_service.get_item(created.id, agent_id=other.id)


@pytest.mark.asyncio
async def test_import_failures_create_no_document(db, agents, memory_storage, monkeypatch):
    from app.document import router
    owner, other = agents
    async def scope():
        return AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    async def invalid(*args):
        return DocumentImportSource("invalid.pdf", "application/pdf", b"invalid")
    monkeypatch.setattr(router, "current_management_scope", scope)
    monkeypatch.setattr(file_import, "_reader", invalid)
    before = await db.scalar(select(func.count()).select_from(Document))
    for source_agent, expected in ((owner.id, 422), (other.id, 404)):
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
    # Saving an embedded image retains its bytes without duplicating the visible file list.
    assert await attachments.list_document_attachments(source_id, actor_agent_id=actor) == []
    async def read(uri, agent_id, actual_scope):
        return await file_import.read_native_document_import(source_id, actual_scope)
    monkeypatch.setattr(file_import, "_reader", read)
    monkeypatch.setattr(router, "current_management_scope", current_scope)
    clone = await create_managed_document(DocumentCreate(owner_kind="user", owner_id=owner.user_id,
        title="Synthetic copied image", import_from=DocumentImportReference(uri=f"document://{source_id}", agent_id=owner.id)))
    assert await attachments.list_document_attachments(clone.id, actor_agent_id=actor) == []
    item, content, *_ = await resource_service.get_item(clone.id, agent_id=actor)
    copied = attachments.attachments_from_item(item, include_retained=True)
    assert len(copied) == 1 and copied[0].id != image.id
    copied_uri = f"document://{clone.id}/attachments/{copied[0].id}"
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


def _converted_source(tmp_path, suffix):
    from io import BytesIO
    import subprocess
    from PIL import Image
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject

    if suffix == ".xls":
        from tests.test_legacy_spreadsheets import synthetic_xls
        path = tmp_path / "source.xls"
        synthetic_xls(path)
        return path.read_bytes(), "application/vnd.ms-excel", "1200.5"
    image = Image.new("RGB", (40, 30), "red")
    if suffix == ".tiff":
        output = BytesIO()
        image.save(output, format="TIFF")
        return output.getvalue(), "image/tiff", ""
    if suffix != ".pdf":
        image.save(tmp_path / "picture.png")
        markdown = tmp_path / "source.md"
        markdown.write_text("# Synthetic imported heading\n\nA synthetic paragraph with **editable emphasis**.\n\n"
                            "![Synthetic illustration](picture.png)\n\n| Item | Value |\n| --- | --- |\n| Synthetic | 42 |\n")
        output = tmp_path / ("source" + suffix)
        subprocess.run(["pandoc", str(markdown), "-o", str(output)], cwd=tmp_path, check=True, capture_output=True)
        return output.read_bytes(), "application/octet-stream", "Synthetic imported heading"
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    raster = DecodedStreamObject()
    raster.set_data(image.tobytes())
    raster.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                   NameObject("/Width"): NumberObject(40), NameObject("/Height"): NumberObject(30),
                   NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
    for number in (1, 2):
        page = writer.add_blank_page(width=300, height=200)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
            NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(raster)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 10 Tf 10 170 Td (Synthetic page {number} with editable text and a red illustration.) Tj ET\nq 80 0 0 60 20 20 cm /Im1 Do Q".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), "application/pdf", "Synthetic page 2"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix,owner_kind", [(".pdf", "user"), (".docx", "agent"), (".odt", "user"), (".xls", "agent"), (".tiff", "user")])
async def test_converted_import_preserves_editable_text_owned_images_and_original(
    db, agents, memory_storage, monkeypatch, tmp_path, suffix, owner_kind,
):
    from io import BytesIO
    from PIL import Image
    from core.user import HumanActor
    from core.util import image_references
    from app.document import document_attachment_service as attachments, router

    owner, stranger = agents
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    source, mime, sentinel = _converted_source(tmp_path, suffix)
    async def current_scope():
        return scope
    async def read(*_args):
        return DocumentImportSource("source" + suffix, mime, source)
    monkeypatch.setattr(router, "current_management_scope", current_scope)
    monkeypatch.setattr(file_import, "_reader", read)
    created = await create_managed_document(DocumentCreate(owner_kind=owner_kind,
        owner_id=owner.user_id if owner_kind == "user" else owner.id,
        actor_agent_id=owner.id if owner_kind == "agent" else None,
        title="Synthetic converted document", import_from=DocumentImportReference(uri="synthetic://binary", agent_id=owner.id)))
    actor = HumanActor(owner.user_id) if owner_kind == "user" else owner.id
    monkeypatch.setattr(file_import, "_reader", None)
    item, raw, *_ = await resource_service.get_item(created.id, agent_id=actor)
    html = raw.decode()
    assert item.document_format == "text" and item.revision == 1 and sentinel in html
    assert "synthetic://binary" not in html and "data:image" not in html and "/tmp/" not in html
    visible = await attachments.list_document_attachments(created.id, actor_agent_id=actor)
    assert len(visible) == 1 and visible[0].name == "source" + suffix
    files = attachments.attachments_from_item(item, include_retained=True)
    original = next(file for file in files if file.name == "source" + suffix)
    assert (await attachments.read_document_attachment(created.id, original.id, actor_agent_id=actor))[1] == source
    assert f"document://{created.id}/attachments/{original.id}" not in html
    assert "<h2>Page " not in html
    assert "[OCR;" not in html and "Page images preserve" not in html and "Le texte extrait" not in html
    assert "formula_tokens" not in html and "number_format" not in html
    references = image_references(html)
    # This synthetic spreadsheet has no illustrations; its former mandatory page
    # screenshot is intentionally retired. Text, original bytes and ACLs stay covered.
    assert bool(references) == (suffix != ".xls")
    assert all(uri.startswith(f"document://{created.id}/attachments/") for uri in references)
    assert not references.intersection(f"document://{created.id}/attachments/{file.id}" for file in visible)
    for file in files:
        if f"document://{created.id}/attachments/{file.id}" not in references:
            continue
        image_bytes = (await attachments.read_document_attachment(created.id, file.id, actor_agent_id=actor))[1]
        with Image.open(BytesIO(image_bytes)) as image:
            assert image.width > 0 and image.height > 0
            if suffix != ".xls":
                assert any(r > 180 and g < 80 and b < 80 for r, g, b in image.convert("RGB").getdata())
            if suffix == ".pdf":
                assert not any(max(pixel) < 80 for pixel in image.convert("RGB").get_flattened_data()), (
                    "Imported illustrations must not contain the page's editable black paragraph"
                )
    if suffix in {".docx", ".odt"}:
        assert "<h1>" in html and "<table>" in html and "<strong>editable emphasis</strong>" in html
    with pytest.raises((resource_service.DocumentPermissionError, resource_service.DocumentNotFoundError)):
        await attachments.read_document_attachment(created.id, original.id, actor_agent_id=stranger.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["conversion", "creation", "cancelled"])
async def test_converted_import_failure_keeps_no_document_or_unpublished_media(
    db, agents, memory_storage, monkeypatch, tmp_path, failure,
):
    import asyncio
    from core import settings
    from app.document import document_service, router
    owner, _ = agents
    async def scope():
        return AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    source, mime, _ = _converted_source(tmp_path, ".docx")
    async def read(*_args):
        return DocumentImportSource("source.docx", mime, b"invalid" if failure == "conversion" else source)
    async def fail_creation(*_args, **_kwargs):
        if failure == "cancelled":
            raise asyncio.CancelledError()
        raise ValueError("Synthetic creation failure")
    monkeypatch.setattr(router, "current_management_scope", scope)
    monkeypatch.setattr(file_import, "_reader", read)
    if failure != "conversion":
        monkeypatch.setattr(document_service, "create_document", fail_creation)
    root = settings.GALARIS_FILE_ROOT
    from pathlib import Path
    before = set(Path(root).rglob("*"))
    count = await db.scalar(select(func.count()).select_from(Document))
    expected = asyncio.CancelledError if failure == "cancelled" else HTTPException
    with pytest.raises(expected):
        await create_managed_document(DocumentCreate(owner_kind="agent", owner_id=owner.id, actor_agent_id=owner.id,
            title="Synthetic failed import", import_from=DocumentImportReference(uri="synthetic://binary", agent_id=owner.id)))
    assert await db.scalar(select(func.count()).select_from(Document)) == count
    assert not [path for path in set(Path(root).rglob("*")) - before if path.is_file()]


def test_imported_html_keeps_media_and_rejects_unowned_images():
    from app.document.converted_import import _editable_html
    uri = "document://00000000-0000-4000-8000-000000000001/attachments/00000000-0000-4000-8000-000000000002"
    result = _editable_html('<h1 onclick="bad()">Title</h1><script>bad()</script><p><img src="assets/image.png" alt="Chart"></p>',
                            {"assets/image.png": uri})
    assert "<h1>Title</h1>" in result and uri in result and "onclick" not in result and "bad()" not in result
    for source in ("https://example.invalid/image.png", "file:///private/image.png", "assets/missing.png", uri):
        with pytest.raises(ValueError, match="outside"):
            _editable_html(f'<p><img src="{source}"></p>', {})
