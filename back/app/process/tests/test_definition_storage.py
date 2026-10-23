"""BPMN persistence never creates an editorial Document, including upgrades."""

from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.memory import service as memory
from app.document import document_service
from app.document import resource_service as documents, DocumentRevision
from app.document.schemas import DocumentUpdate, DocumentPayload
from app.memory.models import MemoryItem, MemoryRevision
from app.document import Document
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload
from app.document.schemas import DocumentGrantUpdate
from app.document.schemas import DocumentLibraryRequest
from app.process.definition_migration import needs_transfer, transfer_complete, transfer_definitions
from app.process.models import ProcessDefinition, ProcessDefinitionRevision
from app.process.native_definitions import create, read, update, history
from app.process.tests.test_native_bpmn import graph, native  # noqa: F401
from app.process.bpmn import to_bpmn
from app.share import ShareGrant
from core.dbadmin import SchemaTransitionSet


def test_memory_document_creation_cannot_be_used_for_bpmn():
    with pytest.raises(ValidationError):
        MemoryItemCreate(node_kind="document", document_type="process", media_type="application/bpmn+xml",
            owner_agent_id=1, title="Synthetic workflow", payload=MemoryPayload(text="<definitions/>"))


@pytest.mark.asyncio
async def test_native_bpmn_is_owned_by_process_rows_and_never_by_documents(db, native):
    owner, reader = native
    before = await db.scalar(select(func.count()).select_from(Document).execution_options(include_historized=True))
    record = await create(actor_agent_id=owner.id, title="Synthetic standalone BPMN", graph=graph())
    assert record.document_id is None
    assert record.bpmn_xml and "definitions" in record.bpmn_xml
    assert "document_id" not in await read(record.code, owner.id)
    saved = await update(record.code, owner.id, graph=graph("Synthetic revision"), expected_revision=1)
    assert saved["revision"] == 2
    assert await db.scalar(select(func.count()).select_from(ProcessDefinitionRevision).where(
        ProcessDefinitionRevision.process_id == record.id)) == 2
    assert await db.scalar(select(func.count()).select_from(Document).execution_options(include_historized=True)) == before
    assert (await documents.browse_document_library(DocumentLibraryRequest(), managed_agent_ids={owner.id})).total == 0
    with pytest.raises(PermissionError):
        await read(record.code, reader.id)


async def legacy_definition(db, owner, reader, *, valid=True):
    """Synthetic pre-upgrade rows written through the old physical representation."""
    source = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic legacy workflow",
        content="<p>Synthetic fixture</p>", task_id=None)
    await documents.set_item_grant(source.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    await documents.update_item(source.id, DocumentUpdate(expected_revision=1,
        payload=DocumentPayload(text="<p>Synthetic second revision</p>")), actor_agent_id=owner.id)
    code = "synthetic_" + uuid4().hex
    content = to_bpmn(graph("Synthetic saved instructions"), code) if valid else "<invalid/>"
    source.document_type, source.media_type, source.content_profile_version = "process", "application/bpmn+xml", None
    source.content, source.content_hash, source.size_bytes = content, sha256(content.encode()).hexdigest(), len(content.encode())
    source.metadata_ = {"process_code": code}
    for entry in await db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == source.id)):
        entry.content = to_bpmn(graph(), code) if entry.revision == 1 else content
        entry.content_hash = sha256(entry.content.encode()).hexdigest()
        entry.media_type, entry.content_profile_version = source.media_type, None
    tool = await db.scalar(select(ProcessDefinition.tool_id).where(ProcessDefinition.code.is_not(None)).limit(1))
    if tool is None:
        from app.tools import ToolModel
        tool = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
    record = ProcessDefinition(agent_id=owner.id, tool_id=tool, code=code, engine_process_id=code,
        label=source.title, document_id=source.id)
    db.add(record)
    await db.commit()
    return source, record, content


def test_definition_transfer_is_triggered_only_by_its_schema_expansion():
    assert needs_transfer(SchemaTransitionSet(added_columns=frozenset({"process_definitions.bpmn_xml"})))
    assert not needs_transfer(SchemaTransitionSet())
    assert not needs_transfer(SchemaTransitionSet(added_columns=frozenset({"process_runs.execution_state"})))


@pytest.mark.asyncio
async def test_existing_bpmn_rights_history_and_source_retirement_transfer_idempotently(db, native):
    owner, reader = native
    source, record, content = await legacy_definition(db, owner, reader)
    source_id = source.id
    delta = SchemaTransitionSet()
    assert not await transfer_complete(db, delta)
    await transfer_definitions(db, delta)
    assert await transfer_complete(db, delta)
    await transfer_definitions(db, delta)
    await db.refresh(record)
    assert record.document_id is None and record.bpmn_xml == content
    assert (await read(record.code, reader.id))["can_write"] is False
    assert [entry["revision"] for entry in (await history(record.code, owner.id))["items"]] == [2, 1]
    from app.process.native_definitions import revision_detail
    assert (await revision_detail(record.code, owner.id, 1))["detail"]["content"] == to_bpmn(graph(), record.code)
    assert await db.scalar(select(func.count()).select_from(ShareGrant).where(
        ShareGrant.share_id == ProcessDefinition.share_for(record.id))) == 1
    assert await db.scalar(select(Document.id).where(Document.id == source_id)) is None
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == source_id)) is None
    archived = await db.scalar(select(Document).where(Document.id == source_id).execution_options(include_historized=True))
    assert archived.deleted_at and archived.content == content
    with pytest.raises(memory.MemoryNotFoundError):
        await memory.get_item(source_id, agent_id=owner.id)


@pytest.mark.asyncio
async def test_invalid_bpmn_prevents_partial_source_retirement(db, native):
    owner, reader = native
    first, first_definition, _ = await legacy_definition(db, owner, reader)
    second, second_definition, _ = await legacy_definition(db, owner, reader, valid=False)
    definition_ids, document_ids = [first_definition.id, second_definition.id], [first.id, second.id]
    with pytest.raises(ValueError):
        await transfer_definitions(db, SchemaTransitionSet())
    await db.rollback()
    rows = (await db.execute(select(ProcessDefinition.bpmn_xml, ProcessDefinition.document_id).where(
        ProcessDefinition.id.in_(definition_ids)))).all()
    assert len(rows) == 2 and all(content is None and document_id is not None for content, document_id in rows)
    assert await db.scalar(select(func.count()).select_from(Document).where(Document.id.in_(document_ids))) == 2
