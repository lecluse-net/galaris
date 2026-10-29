"""Additive, resumable migration. Original rows and bytes are retained for audit."""

import hashlib
from uuid import UUID

from sqlalchemy import select

from app.document import legacy_dataset_ids, legacy_dataset_snapshot
from core.database import get_db
from core.storage import FileAlias, StoredFile

from .models import Dataset, DatasetAlias, DatasetAppConsent, DatasetAttachment, DatasetRevision, DatasetWriteBudget


async def adopt_legacy(identity: UUID) -> Dataset:
    """Promote a verified historical JSON Document without changing identity."""
    from sqlalchemy import update, Table
    from typing import cast
    from uuid import uuid4
    from ..models import Document, DocumentRevision

    db = get_db()
    existing = await db.scalar(select(Dataset).where(Dataset.id == identity)
        .execution_options(include_historized=True))
    if existing is not None:
        return existing
    source = await legacy_dataset_snapshot(identity)
    original = await db.get(Document, identity, execution_options={"include_historized": True})
    if original is None or original.document_type != "dataset":
        raise ValueError("No verified historical Data document exists")
    await db.execute(cast(Table, Document.__table__).update().where(Document.id == identity).values(
        document_type="data", provider_code="native", resource_id=str(uuid4()),
        content=source["content"], content_hash=hashlib.sha256(source["content"].encode()).hexdigest(),
        size_bytes=len(source["content"].encode()), content_profile_version=None,
        search_text=source["content"]))
    # The identity map must instantiate the new specialization after promotion.
    db.expunge(original)
    record = await db.scalar(select(Dataset).where(Dataset.id == identity)
        .execution_options(include_historized=True))
    assert record is not None
    await db.execute(update(DocumentRevision).where(DocumentRevision.document_id == identity)
        .values(document_content_version=True))
    if not await db.scalar(select(DocumentRevision.id).where(
        DocumentRevision.document_id == identity, DocumentRevision.revision == record.revision)):
        db.add(DocumentRevision(document_id=identity, revision=record.revision, content=record.content))
    for attachment in source["attachments"]:
        alias = f"document://{identity}/attachments/{attachment['id']}"
        file_id = await db.scalar(select(FileAlias.file_id).where(FileAlias.uri == alias))
        if file_id is None:
            file_id = await db.scalar(select(StoredFile.id).where(StoredFile.id == attachment["id"]))
        file = await db.get(StoredFile, file_id) if file_id else None
        db.add(DatasetAttachment(id=attachment["id"], dataset_id=identity,
            uri=f"file://{file_id}" if file_id else alias, file_id=file_id,
            name=attachment["name"], media_type=attachment["media_type"], size_bytes=attachment["size_bytes"],
            sha256=file.sha256 if file else None, created_at=attachment["created_at"]))
    for entry in source["budgets"]:
        db.add(DatasetWriteBudget(dataset_id=identity, **entry))
    for entry in source["consents"]:
        db.add(DatasetAppConsent(dataset_id=identity, **entry))
    digest = hashlib.sha256(record.content.encode()).hexdigest()
    db.add(DatasetAlias(legacy_document_id=identity, dataset_id=identity,
        source_revision=record.revision, source_hash=digest,
        manifest={"revisions": {str(r["revision"]): hashlib.sha256(r["content"].encode()).hexdigest()
            for r in source["revisions"]}}))
    await db.flush()
    return record


async def migrate_legacy() -> None:
    cursor: UUID | None = None
    while identities := await legacy_dataset_ids(after=cursor, limit=32):
        for identity in identities:
            await adopt_legacy(identity)
            # One source, all revisions, rights and the alias share a commit.
            # A later failure resumes using these durable postconditions.
            await get_db().commit()
        cursor = identities[-1]


async def migration_complete() -> bool:
    cursor: UUID | None = None
    while identities := await legacy_dataset_ids(after=cursor, limit=32):
        for identity in identities:
            alias = await get_db().scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == identity))
            if alias is None:
                return False
            rows = await get_db().scalars(select(DatasetRevision).where(DatasetRevision.dataset_id == alias.dataset_id))
            hashes = {str(entry.revision): hashlib.sha256((entry.content or "").encode()).hexdigest() for entry in rows}
            if hashes.get(str(alias.source_revision)) != alias.source_hash:
                return False
            if any(hashes.get(number) != digest for number, digest in alias.manifest.get("revisions", {}).items()):
                return False
        cursor = identities[-1]
    return True
