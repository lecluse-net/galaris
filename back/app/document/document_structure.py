"""Record changes for optional graph adapters; documents never require a graph row."""
from uuid import UUID
from sqlalchemy import select
from core.database import get_db
from .models import Document, DocumentAttachment


def _stage(kind: str, identity: UUID) -> None:
    pending: set[tuple[str, UUID]] = get_db().info.setdefault("document_projection_changes", set())
    pending.add((kind, identity))


async def sync_document_structure(item: Document, content: bytes | None = None) -> None:
    from .document_attachment_service import attachments_from_item
    db = get_db()
    active = {attachment.id for attachment in attachments_from_item(item)}
    retained = {attachment.id for attachment in attachments_from_item(item, include_retained=True)}
    records = {record.id: record for record in await db.scalars(select(DocumentAttachment).where(
        DocumentAttachment.document_id == item.id,
    ))}
    for identity in retained:
        record = records.get(identity)
        if record is None:
            db.add(DocumentAttachment(id=identity, document_id=item.id, active=identity in active))
        else:
            record.active = identity in active
    for identity, record in records.items():
        if identity not in retained:
            record.active = False
    _stage("document", item.id)


async def sync_document_classification(document_id: UUID) -> None:
    _stage("document", document_id)


async def sync_folder_structure(user_id: int) -> None:
    from sqlalchemy import select
    from .models import DocumentTag
    for identity in await get_db().scalars(select(DocumentTag.id).where(DocumentTag.user_id == user_id)):
        _stage("folder", identity)
    # Moving an ancestor revokes inherited grants in the same transaction. This
    # cannot depend on the optional native-memory graph projector.
    from .sharing_inheritance import reconcile_sharing
    await reconcile_sharing()


async def flush_projection_changes() -> None:
    from .lifecycle import notify_document
    for kind, identity in get_db().info.pop("document_projection_changes", set()):
        await notify_document(identity, kind)
