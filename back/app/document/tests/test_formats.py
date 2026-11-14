"""The same documentary guarantees apply to native and external format contributions."""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select

from app.document import (
    DocumentFormatDefinition, DocumentFormatRegistry, FormatExample, document_format_catalogue,
    document_format_definition, document_source, qualify_document_format, register_document_format,
)
from app.document import formats, resource_service as service
from app.document.document_cloning import DocumentCloneSource
from app.document.file_import import DocumentImportSource, convert_document_import
from app.document.library_queries import browse_document_library
from app.document.models import Document, DocumentRevision
from app.document.schemas import DocumentItemCreate, DocumentLibraryRequest, DocumentPayload, DocumentUpdate


def validate_outline(content):
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get("label"), str):
        raise ValueError("Outline requires a label")


def remap_outline(content, mapping):
    value = json.loads(content)
    value["assets"] = [mapping.get(uri, uri) for uri in value.get("assets", [])]
    return json.dumps(value)


@pytest.fixture
def outline(monkeypatch):
    # Independent registry per test; never publish a test plugin in the application.
    monkeypatch.setattr(formats, "registry", DocumentFormatRegistry())
    monkeypatch.setattr(formats, "_native_registered", False)
    definition = DocumentFormatDefinition(
        "example.outline", "application/vnd.example.outline+json", '{"label":"New outline"}',
        "account_tree", validate_outline, lambda content: json.loads(content)["label"],
        provider="example", references=lambda content: tuple(json.loads(content).get("assets", [])),
        remap_references=remap_outline, import_extensions=(".outline",),
    )
    register_document_format(definition)
    return definition


def test_registry_rejects_collisions_and_incompatible_contributions_without_replacing_native_formats(outline):
    original = document_format_definition("text")
    for definition in (replace(outline, code="text"), replace(outline, code="bad/code"),
                       replace(outline, code="another", contract_version=99), replace(outline, code="dataset")):
        with pytest.raises(ValueError):
            register_document_format(definition)
    assert document_format_definition("text") is original
    with pytest.raises(ValueError, match="unavailable"):
        document_format_definition("html")
    with pytest.raises(ValueError, match="unavailable"):
        document_format_definition("missing.format")
    catalogue = {entry["code"]: entry for entry in document_format_catalogue()}
    assert catalogue[outline.code]["qualification"] == "not_run"
    assert catalogue[outline.code]["capabilities"]["editor"] == "unavailable"
    assert catalogue[outline.code]["capabilities"]["embed"] == "fallback"
    assert not catalogue[outline.code]["capability_complete"]


def test_reusable_codec_qualification_detects_broken_extraction_and_reference_remapping(outline):
    example = FormatExample("synthetic-reference", '{"label":"Branch","assets":["document://a/attachments/b"]}',
        "Branch", ("document://a/attachments/b",))
    arguments = dict(invalid_contents=('{}', '{"label":12}'),
        reference_mapping={"document://a/attachments/b": "document://c/attachments/d"})
    assert all(check.status == "passed" for check in qualify_document_format(outline, (example,), **arguments))
    for broken in (replace(outline, extract=lambda _: "wrong"),
                   replace(outline, remap_references=lambda source, _: source)):
        assert qualify_document_format(broken, (example,), **arguments)[0].status == "failed"
    assert qualify_document_format(outline, ())[0].status == "not_run"


def test_conformance_requires_all_suites_for_the_exact_release(outline):
    from app.document import FormatCheck, FormatSuiteEvidence, document_format_conformance
    from app.document.format_qualification import FORMAT_QUALIFICATION_SUITES
    digest = "a" * 64
    evidence = tuple(FormatSuiteEvidence(outline.code, outline.version, outline.provider, digest,
        suite, (FormatCheck("synthetic-contract", "passed"),)) for suite in FORMAT_QUALIFICATION_SUITES)
    assert all(check.status == "passed" for check in document_format_conformance(outline, digest, evidence))
    for partial in (evidence[:-1], (replace(evidence[0], implementation_digest="b" * 64), *evidence[1:]),
                    (replace(evidence[0], format_version=2), *evidence[1:]),
                    (replace(evidence[0], checks=()), *evidence[1:]), (*evidence, evidence[0])):
        assert any(check.status != "passed" for check in document_format_conformance(outline, digest, partial))


@pytest.mark.asyncio
@pytest.mark.parametrize("code,first,second", [
    ("text", "<p>First</p>", "<p>Second</p>"),
    ("data", '{"first":1}', '{"second":2}'),
    ("example.outline", '{"label":"First"}', '{"label":"Second"}'),
])
async def test_common_format_lifecycle_preserves_policy_conflicts_history_and_missing_plugin_source(
    db, agents, memory_storage, revision_clock, outline, code, first, second,
):
    owner, outsider = agents
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic format contract", document_format=code, payload=DocumentPayload(text=first)))
    identity = item.id
    assert item.document_format == code and item.format_version == 1
    public = service.item_to_public(item, await service.effective_access(item, owner.id)).model_dump()
    assert public["document_format"] == code
    assert "document_type" not in public
    page = await browse_document_library(DocumentLibraryRequest(document_format=code),
        managed_agent_ids=(owner.id,), user_id=owner.user_id)
    assert identity in [entry.item.id for entry in page.entries]
    with pytest.raises((service.DocumentNotFoundError, service.DocumentPermissionError)):
        await document_source(identity, outsider.id)
    updated = await service.update_item(identity, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(text=second)), actor_agent_id=owner.id)
    assert updated.revision == 2
    if code == outline.code:
        assert updated.search_text == "Second"
    with pytest.raises(service.DocumentConflictError):
        await service.update_item(identity, DocumentUpdate(expected_revision=1,
            payload=DocumentPayload(text=first)), actor_agent_id=owner.id)
    await revision_clock.settle()
    restored = await service.restore_document_content_revision(identity, 1, actor_agent_id=owner.id, expected_revision=2)
    assert (await document_source(identity, owner.id))[0] == first.encode()
    await revision_clock.settle()
    versions = list(await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == identity)))
    assert len(versions) == 3 and all(version.format_version == 1 for version in versions)
    if code == outline.code:
        formats.registry._formats.pop(code)
        db.expunge_all()
        # An unknown format loads through the generic Document envelope, never an HTML conversion.
        reloaded = await db.get(Document, identity)
        assert reloaded.document_format == code
        assert (await document_source(identity, owner.id))[0] == first.encode()
        with pytest.raises(ValueError, match="unavailable"):
            await service.update_item(identity, DocumentUpdate(expected_revision=restored.revision,
                payload=DocumentPayload(text=second)), actor_agent_id=owner.id)
        page = await browse_document_library(DocumentLibraryRequest(document_format=code),
            managed_agent_ids=(owner.id,), user_id=owner.user_id)
        assert identity in [entry.item.id for entry in page.entries]


def test_import_routes_a_registered_file_format_and_preserves_native_identity(outline):
    source = '{"label":"Imported outline"}'
    for name, mime in (("synthetic.outline", "application/octet-stream"), ("opaque", outline.media_type)):
        assert convert_document_import(DocumentImportSource(name, mime, source.encode())) == (outline.code, source)
    with pytest.raises(ValueError):
        convert_document_import(DocumentImportSource("synthetic.outline", outline.media_type, b"{}"))
    with pytest.raises(ValueError):
        DocumentItemCreate.model_validate({"owner_agent_id": 1, "title": "Synthetic old field",
            "document_type": "data", "payload": {"text": "[]"}})


@pytest.mark.asyncio
async def test_structured_format_copy_owns_and_remaps_its_attachments(db, agents, memory_storage, outline):
    from app.document.document_attachment_service import add_document_attachment_bytes, read_document_attachment
    owner, _ = agents
    original, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic source", document_format=outline.code, payload=DocumentPayload(text=outline.initial_content)))
    attachment = await add_document_attachment_bytes(original.id, actor_agent_id=owner.id,
        name="synthetic.txt", media_type="text/plain", content=b"Synthetic asset")
    original_uri = f"document://{original.id}/attachments/{attachment.id}"
    content = json.dumps({"label": "Copied branch", "assets": [original_uri]})
    copied, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner.id,
        title="Synthetic copy", document_format=outline.code, payload=DocumentPayload(text=content)),
        clone_source=DocumentCloneSource(original.id, owner.id))
    payload = json.loads((await document_source(copied.id, owner.id))[0])
    assert payload["assets"][0].startswith(f"document://{copied.id}/attachments/")
    assert original_uri not in payload["assets"]
    from uuid import UUID
    copied_attachment = UUID(payload["assets"][0].rsplit("/", 1)[-1])
    assert (await read_document_attachment(copied.id, copied_attachment, actor_agent_id=owner.id))[1] == b"Synthetic asset"


@pytest.mark.asyncio
async def test_binary_format_retains_immutable_files_and_restores_exact_bytes(db, agents, memory_storage, outline):
    import base64
    from app.document.document_service import create_document
    from core.storage import StoredFile

    def validate_binary(content):
        if not content.startswith(b"B\x00"):
            raise ValueError("Invalid synthetic binary")

    binary = DocumentFormatDefinition("example.binary", "application/x-example-binary", "", "insert_drive_file",
        lambda _: None, lambda _: "", storage_kind="file", provider="example", initial_binary=b"B\x00one\xff",
        validate_binary=validate_binary, extract_binary=lambda _: "Synthetic binary")
    register_document_format(binary)
    assert all(check.status == "passed" for check in qualify_document_format(binary,
        (FormatExample("synthetic-binary", b"B\x00one\xff", "Synthetic binary"),), invalid_contents=(b"invalid",)))
    owner, _ = agents
    item = await create_document(owner_agent_id=owner.id, title="Synthetic binary", document_format=binary.code,
        content="", task_id=None)
    identity, first_file = item.id, item.file_id
    assert item.storage_kind == "file" and item.content is None
    assert (await document_source(identity, owner.id))[0] == b"B\x00one\xff"
    from app.file_share import ResourceContext, resource_read, resource_write
    mutation = await resource_write(ResourceContext(agent_id=owner.id, runtime="internal"),
        f"document://{identity}", b"B\x00two\xfe", expected_revision=1)
    assert mutation.revision == 2
    updated = await db.get(Document, identity)
    assert updated.file_id != first_file
    page = await resource_read(ResourceContext(agent_id=owner.id, runtime="internal"),
        f"document://{identity}", offset=1, max_chars=2)
    assert page.encoding == "base64" and base64.b64decode(page.content, validate=True) == b"\x00t"
    assert (page.start, page.end, page.total, page.next_offset) == (1, 3, 6, 3)
    assert await db.get(StoredFile, first_file) is not None
    assert (await document_source(identity, owner.id, revision=1))[0] == b"B\x00one\xff"
    detail = await service.get_document_content_revision(identity, 1, actor_agent_id=owner.id)
    assert base64.b64decode(detail.payload.base64) == b"B\x00one\xff"
    assert (await service.diff_document_content_revision(identity, 1, actor_agent_id=owner.id)).binary_changed
    await service.restore_document_content_revision(identity, 1, expected_revision=2, actor_agent_id=owner.id)
    assert (await document_source(identity, owner.id))[0] == b"B\x00one\xff"


@pytest.mark.asyncio
async def test_failed_binary_publication_discards_unpublished_bytes_and_preserves_the_previous_source(db, agents, memory_storage, outline, monkeypatch):
    import base64
    from app.document import content as content_storage
    from core.storage import file_path
    binary = DocumentFormatDefinition("example.binary", "application/x-example-binary", "", "insert_drive_file",
        lambda _: None, lambda _: "", storage_kind="file", provider="example", initial_binary=b"initial",
        validate_binary=lambda _: None)
    register_document_format(binary)
    from app.document.document_service import create_document
    owner, _ = agents
    owner_id = owner.id
    item = await create_document(owner_agent_id=owner.id, title="Synthetic failed binary", document_format=binary.code,
        content="", task_id=None)
    identity = item.id
    created = []
    prepare = content_storage.prepare_binary_content
    async def capture(*args, **kwargs):
        file_id = await prepare(*args, **kwargs)
        created.append(file_id)
        return file_id
    async def fail_commit():
        raise RuntimeError("Synthetic commit failure")
    with monkeypatch.context() as failure:
        failure.setattr(content_storage, "prepare_binary_content", capture)
        failure.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Synthetic commit failure"):
            await service.update_item(identity, DocumentUpdate(expected_revision=1,
                payload=DocumentPayload(base64=base64.b64encode(b"unpublished").decode())), actor_agent_id=owner.id)
    assert len(created) == 1 and not file_path(created[0]).exists()
    assert (await document_source(identity, owner_id))[0] == b"initial"


@pytest.mark.asyncio
async def test_format_http_catalogue_creation_source_and_export_keep_live_authorization(client, outline, monkeypatch):
    from app.document import document_export
    assert (await client.get("/api/documents/formats")).status_code in {401, 403}
    credentials = {"email": "synthetic-format-owner@example.com", "password": "Synthetic-format-password-123"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    owner = registered.json()["id"]
    catalogue = await client.get("/api/documents/formats", headers=headers)
    assert catalogue.status_code == 200, catalogue.text
    assert outline.code in [entry["code"] for entry in catalogue.json()]
    assert (await client.get("/api/documents/types", headers=headers)).status_code in {403, 404, 405, 422}
    created = await client.post("/api/documents", headers=headers, json={"owner_kind": "user", "owner_id": owner,
        "title": "Synthetic contributed document", "document_format": outline.code})
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    assert created.json()["document_format"] == outline.code
    assert "document_type" not in created.json()
    uri = f"/api/documents/{identity}/source"
    source = await client.get(uri, headers=headers)
    assert source.status_code == 200 and source.text == outline.initial_content
    assert (await client.get(uri)).status_code in {401, 403}
    async def render(html, **_kwargs):
        assert "Synthetic static export" in html
        return b"%PDF-Synthetic boundary"
    monkeypatch.setattr(document_export, "render_html_pdf", render)
    exported = await client.post(f"/api/documents/{identity}/export-pdf", headers=headers,
        json={"html": "<p>Synthetic static export</p>"})
    assert exported.status_code == 200 and exported.content.startswith(b"%PDF-")
