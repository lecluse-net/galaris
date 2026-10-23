"""Set up real Documents and consume their optional native graph projection."""

from app.document import document_service, resource_service as documents
from app.document import document_attachment_service as attachments, DocumentAttachment
from app.document.schemas import DocumentItemCreate, DocumentUpdate
from app.memory import service as memories
from app.memory.document_projection import refresh
from core.database import get_db


async def project_document(identity):
    await refresh(identity)
    await get_db().commit()
    return await memories.item_record(identity)


async def finish_document_deletion(identity, **kwargs):
    from app.document.automation import process_next
    result = await documents.delete_document(identity, **kwargs)
    await project_document(identity)
    for _ in range(200):
        if not await process_next():
            break
    else:
        raise AssertionError("Document cleanup did not drain")
    return result


async def create_document_reference(data, **kwargs):
    document, created = await documents.create_item(DocumentItemCreate.model_validate(data.model_dump()), **kwargs)
    return await project_document(document.id), created


async def create_indexed_document(**kwargs):
    document = await document_service.create_document(**kwargs)
    return await project_document(document.id)


async def create_indexed_attachment(document_id, **kwargs):
    attachment = await attachments.add_document_attachment_bytes(document_id, **kwargs)
    await project_document(document_id)
    reference = await get_db().get(DocumentAttachment, attachment.id)
    return attachment.model_copy(update={"memory_item_id": reference.memory_item_id})


async def edit_document_reference(identity, data, **kwargs):
    await documents.update_item(identity, DocumentUpdate.model_validate(data.model_dump(exclude_unset=True)), **kwargs)
    return await project_document(identity)


async def edit_document_summary(identity, data, **kwargs):
    await documents.update_summary(identity, DocumentUpdate.model_validate(data.model_dump(exclude_unset=True)), **kwargs)
    return await project_document(identity)
