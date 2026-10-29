import pytest
from sqlalchemy import select

from app.dataset import service as datasets
from app.document import resource_service as service
from app.document import dataset_attachments, document_service
from app.document import Document
from app.document.schemas import DocumentGrantUpdate


@pytest.mark.asyncio
async def test_attached_dataset_remains_independent_live_and_does_not_inherit_document_sharing(db, agents, memory_storage):
    owner, reader = agents
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic report", content="<p>Report</p>", task_id=None)
    dataset = await datasets.create(owner.id, title="Synthetic live budget", content='{"amount":100}')
    assert (await db.get(Document, dataset.id)).document_type == "data"
    before = document.revision
    refs, version = await dataset_attachments.change_reference(document.id, dataset.id, owner.id,
        dataset_actor=owner.id, expected_lock_version=document.lock_version)
    assert refs[0].uri == f"data://{dataset.id}" and refs[0].title == dataset.title
    assert document.revision == before and dataset.revision == 1
    from app.file_share import ResourceContext, resource_list
    collection = f"document://{document.id}/attachments/"
    listed = await resource_list(ResourceContext(agent_id=owner.id, runtime="internal"), collection)
    assert listed.entries == []
    # An identical retry creates no extra reference and does not need a fresh lock.
    duplicate, same_version = await dataset_attachments.change_reference(document.id, dataset.id, owner.id,
        dataset_actor=owner.id, expected_lock_version=1)
    assert duplicate == refs and same_version == version
    # Legacy live references remain readable through their API, never as uploaded files.
    from app.document.document_attachment_service import add_document_attachment_bytes
    upload = await add_document_attachment_bytes(document.id, actor_agent_id=owner.id,
        name="Synthetic notes.txt", media_type="text/plain", content=b"Synthetic uploaded notes")
    listed = await resource_list(ResourceContext(agent_id=owner.id, runtime="internal"), collection)
    assert [entry.uri for entry in listed.entries] == [f"{collection}{upload.id}"]
    assert listed.entries[0].name == "Synthetic notes.txt"
    await service.set_item_grant(document.id, reader.id, DocumentGrantUpdate(can_write=True), actor_agent_id=owner.id)
    hidden, _ = await dataset_attachments.list_references(document.id, reader.id, dataset_actor=reader.id)
    assert hidden[0].title is None and not hidden[0].available
    assert [entry.uri for entry in (await resource_list(ResourceContext(agent_id=reader.id, runtime="internal"), collection)).entries] == [f"{collection}{upload.id}"]
    with pytest.raises(datasets.DatasetNotFoundError):
        await datasets.record(dataset.id, reader.id)
    await datasets.set_grant(dataset.id, owner.id, kind="agent", principal=reader.id, can_write=False, expected_lock_version=dataset.lock_version)
    await datasets.metadata(dataset.id, owner.id, expected_lock_version=dataset.lock_version, values={"title": "Synthetic current budget"})
    visible, _ = await dataset_attachments.list_references(document.id, reader.id, dataset_actor=reader.id)
    assert visible[0].title == "Synthetic current budget" and visible[0].available
    await datasets.replace(dataset.id, owner.id, content='{"amount":200}', expected_revision=1)
    assert (await datasets.record(dataset.id, reader.id)).content == '{"amount":200}'
    assert await db.scalar(select(Document.id).where(Document.id == dataset.id)) == dataset.id
    with pytest.raises(service.DocumentConflictError):
        await dataset_attachments.change_reference(document.id, dataset.id, reader.id,
            dataset_actor=reader.id, expected_lock_version=1, remove=True)
    _, current_version = await dataset_attachments.list_references(document.id, reader.id, dataset_actor=reader.id)
    detached, _ = await dataset_attachments.change_reference(document.id, dataset.id, reader.id,
        dataset_actor=reader.id, expected_lock_version=current_version, remove=True)
    assert detached == []
    assert (await datasets.record(dataset.id, owner.id)).content == '{"amount":200}'


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_manifest", [None, ["data://00000000-0000-4000-8000-000000000001"] * 51])
async def test_attaching_dataset_requires_both_document_edit_and_independent_dataset_read(agents, memory_storage, invalid_manifest):
    owner, other = agents
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic private report", content="<p>Report</p>", task_id=None)
    dataset = await datasets.create(other.id, title="Synthetic private data", content="null")
    with pytest.raises(service.DocumentNotFoundError):
        await dataset_attachments.change_reference(document.id, dataset.id, owner.id,
            dataset_actor=owner.id, expected_lock_version=document.lock_version)
    await service.set_item_grant(document.id, other.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    with pytest.raises(service.DocumentPermissionError):
        await dataset_attachments.change_reference(document.id, dataset.id, other.id,
            dataset_actor=other.id, expected_lock_version=document.lock_version)
    document.metadata_ = {**document.metadata_, "dataset_attachments": invalid_manifest}
    from core.database import get_db
    await get_db().flush()
    with pytest.raises(service.DocumentConflictError):
        await dataset_attachments.list_references(document.id, owner.id, dataset_actor=owner.id)
