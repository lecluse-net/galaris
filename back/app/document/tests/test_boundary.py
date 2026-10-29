"""A document's persistence and permissions never require a personal Memory row."""
import pytest
from sqlalchemy import func, select
from app.document import Document, DocumentRevision
from app.document import document_service, resource_service
from app.memory.models import MemoryItem
from app.memory import service as memories
from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemorySourceCreate
from app.memory.tests.conftest import agents, memory_storage


@pytest.mark.asyncio
async def test_document_content_history_and_sharing_without_a_memory(db, agents, memory_storage):
    owner, reader=agents
    document=await document_service.create_document(owner_agent_id=owner.id,title="Synthetic launch notes",content="<p>Initial notes.</p>",task_id=None)
    identity=document.id
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id==identity)) is None
    with pytest.raises(resource_service.DocumentPermissionError):
        await document_service.read_document(identity,actor_agent_id=reader.id,task_id=None)
    await document_service.share_document(identity,owner_agent_id=owner.id,target_agent_id=reader.id,access="edit",task_id=None)
    result=await document_service.edit_document(identity,actor_agent_id=reader.id,task_id=None,old_text="Initial notes.",new_text="Revised notes.")
    assert result["revision"]==2
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id==identity))==2
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id==identity)) is None
    await document_service.share_document(identity,owner_agent_id=owner.id,target_agent_id=reader.id,access="none",task_id=None)
    with pytest.raises(resource_service.DocumentPermissionError):
        await document_service.read_document(identity,actor_agent_id=reader.id,task_id=None)
    assert "Revised notes." in str(await document_service.read_document(identity,actor_agent_id=owner.id,task_id=None))


@pytest.mark.asyncio
async def test_personal_memory_has_no_persisted_policy_and_denies_other_agent(db, agents, memory_storage):
    owner,other=agents
    memory,_=await memories.create_item(MemoryItemCreate(owner_agent_id=owner.id,payload=MemoryPayload(text="<p>Private synthetic preference.</p>"),media_type="text/html"))
    assert not {"share_id","share_kind","global_access","group_access","visibility"}&set(MemoryItem.__table__.columns.keys())
    assert (await memories.get_item(memory.id,agent_id=owner.id))[1]==b"<p>Private synthetic preference.</p>"
    with pytest.raises(memories.MemoryPermissionError):
        await memories.get_item(memory.id,agent_id=other.id)
    assert await db.scalar(select(Document.id).where(Document.id==memory.id)) is None
    from app.memory.schemas import MemoryItemUpdate
    await memories.update_memory_content(memory.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Revised private preference.</p>")), actor_agent_id=owner.id)
    assert len(await memories.list_revisions(memory.id, agent_id=owner.id)) == 2
    await memories.forget_item(memory.id, actor_agent_id=owner.id)
    with pytest.raises(memories.MemoryNotFoundError):
        await memories.get_item(memory.id, agent_id=owner.id)


@pytest.mark.asyncio
async def test_document_summary_uses_document_rights_without_content_or_keyword_history(db, agents, memory_storage):
    from app.document.schemas import DocumentPayload,DocumentUpdate
    owner,reader=agents
    document=await document_service.create_document(owner_agent_id=owner.id,title="Synthetic summary source",content="<p>Full source text.</p>",task_id=None)
    await resource_service.update_summary(document.id,DocumentUpdate(payload=DocumentPayload(text="<p>Shared documentary abstract.</p>"),expected_revision=1),actor_agent_id=owner.id)
    current = await db.get(Document, document.id)
    assert current.summary_content == "<p>Shared documentary abstract.</p>"
    assert current.revision == 1
    assert await db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.document_id == document.id)) == 1
    assert "keywords" not in DocumentRevision.__table__.columns

    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id==document.id)) is None
    with pytest.raises(resource_service.DocumentPermissionError):
        await resource_service.update_summary(document.id,DocumentUpdate(payload=DocumentPayload(text="<p>Denied.</p>")),actor_agent_id=reader.id)


@pytest.mark.asyncio
async def test_file_access_and_optional_graph_reference_preserve_document_ownership(db, agents, memory_storage):
    from app.document.file_facade import read_file_resource_text, search_file_resources
    from app.document.summary_service import read_summary
    from app.document.schemas import DocumentPayload, DocumentUpdate
    from app.memory.document_projection import refresh
    from app.memory.schemas import MemoryItemUpdate
    owner, reader = agents
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic independent notes",
        content="<p>Searchable canonical source.</p>", task_id=None)
    identity = document.id
    await resource_service.update_summary(identity, DocumentUpdate(payload=DocumentPayload(text="<p>Shared documentary summary.</p>")), actor_agent_id=owner.id)
    results = await search_file_resources(agent_id=owner.id, task_id=None, expected_kind="document", query="canonical",
        mode="text", limit=50, offset=0)
    assert [hit["id"] for hit in results["hits"]] == [str(identity)]
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id==identity)) is None
    assert "canonical source" in str(await read_file_resource_text(identity, agent_id=owner.id,
        task_id=None, expected_kind="document", offset=0, max_chars=1000))
    await refresh(identity)
    await db.commit()
    assert (await memories.get_item(identity, agent_id=owner.id, memory_content=True))[1] == b"<p>Shared documentary summary.</p>"
    with pytest.raises(memories.MemoryPermissionError):
        await memories.update_memory_content(identity, MemoryItemUpdate(payload=MemoryPayload(text="<p>Wrong owner domain.</p>")), actor_agent_id=owner.id)
    personal_source = MemorySourceCreate(source_kind="test", source_ref="synthetic:private-provenance")
    with pytest.raises(memories.MemoryPermissionError):
        await memories.add_item_source(identity, personal_source, actor_agent_id=owner.id)
    with pytest.raises(memories.MemoryPermissionError):
        await memories.link_item_source(identity, personal_source, actor_agent_id=owner.id)
    await document_service.share_document(identity, owner_agent_id=owner.id, target_agent_id=reader.id, access="edit", task_id=None)
    assert (await memories.get_item(identity, agent_id=reader.id))[1] == b"<p>Searchable canonical source.</p>"
    with pytest.raises(resource_service.DocumentPermissionError):
        await resource_service.delete_document(identity, actor_agent_id=reader.id)
    await document_service.share_document(identity, owner_agent_id=owner.id, target_agent_id=reader.id, access="none", task_id=None)
    with pytest.raises(memories.MemoryPermissionError):
        await memories.get_item(identity, agent_id=reader.id)
    reference = await memories.item_record(identity)
    await memories.forget_document_reference(reference, commit=True)
    assert (await resource_service.get_item(identity, agent_id=owner.id))[1] == b"<p>Searchable canonical source.</p>"
    assert (await read_summary(identity, actor=owner.id)).payload.text == "<p>Shared documentary summary.</p>"
    await refresh(identity)
    await db.commit()
    assert (await memories.get_item(identity, agent_id=owner.id))[0].id == identity
    await resource_service.delete_document(identity, actor_agent_id=owner.id)
    await refresh(identity)
    await db.commit()
    with pytest.raises(memories.MemoryNotFoundError):
        await memories.get_item(identity, agent_id=owner.id)
