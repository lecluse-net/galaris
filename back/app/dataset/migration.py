"""Additive, resumable migration. Original rows and bytes are retained for audit."""

from app.share import ShareGrant

from copy import deepcopy
import hashlib
from uuid import UUID

from sqlalchemy import select

from app.document import legacy_dataset_ids, legacy_dataset_snapshot
from core.database import get_db
from core.storage import FileAlias, StoredFile

from .models import Dataset, DatasetAlias, DatasetAppConsent, DatasetAppearance, DatasetAttachment, DatasetRevision, DatasetTag, DatasetTagAssignment, DatasetWriteBudget


async def adopt_legacy(identity: UUID) -> Dataset:
    db = get_db()
    existing = await db.scalar(select(Dataset).where(Dataset.id == identity).execution_options(include_historized=True))
    if existing is not None:
        alias = await db.scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == identity, DatasetAlias.dataset_id == identity))
        if alias is None:
            raise ValueError("Dataset identity conflicts with a legacy document; migration stopped")
        return existing
    source = await legacy_dataset_snapshot(identity)
    # The source lock fences concurrent legacy writers until alias and all
    # history/ACL rows commit. A partially copied Dataset is never published.
    existing = await db.scalar(select(Dataset).where(Dataset.id == identity).execution_options(include_historized=True))
    if existing is not None:
        return existing
    record = Dataset(id=identity, title=source["title"], content=source["content"], revision=source["revision"],
        lock_version=source["lock_version"], owner_agent_id=source["owner_agent_id"], owner_user_id=source["owner_user_id"],
        global_access=source["global_access"], group_access=source["group_access"], read_only=source["read_only"],
        keywords=deepcopy(source["keywords"]), metadata_=deepcopy(source["metadata"]),
        creation_key=source["metadata"].get("creation_command"),
        **{key: source[key] for key in ("created_at", "created_by", "updated_at", "updated_by", "deleted_at", "deleted_by")})
    db.add(record)
    await db.flush()
    numbers: set[int] = set()
    hashes: dict[str, str] = {}
    for revision in source["revisions"]:
        db.add(DatasetRevision(dataset_id=identity, revision=revision["revision"], content=revision["content"],
            document_source_revision_id=revision["id"], author_agent_id=revision["author_agent_id"], created_at=revision["created_at"]))
        numbers.add(revision["revision"])
        hashes[str(revision["revision"])] = hashlib.sha256(revision["content"].encode()).hexdigest()
    if record.revision not in numbers:
        db.add(DatasetRevision(dataset_id=identity, revision=record.revision, content=record.content))
    for grant in source["grants"]:
        db.add(ShareGrant(share_id=Dataset.share_for(identity), **grant))
    for attachment in source["attachments"]:
        alias = f"document://{identity}/attachments/{attachment['id']}"
        file_id = await db.scalar(select(FileAlias.file_id).where(FileAlias.uri == alias))
        # Legacy native storage uses the attachment UUID itself. No external
        # source is fetched or promoted by this structural migration.
        if file_id is None:
            file_id = await db.scalar(select(StoredFile.id).where(StoredFile.id == attachment["id"]))
        file = await db.get(StoredFile, file_id) if file_id else None
        uri = f"file://{file_id}" if file_id else alias
        db.add(DatasetAttachment(id=attachment["id"], dataset_id=identity, uri=uri,
            name=attachment["name"], media_type=attachment["media_type"], size_bytes=attachment["size_bytes"],
            file_id=file_id, sha256=file.sha256 if file else None, created_at=attachment["created_at"]))
    for entry in source["budgets"]:
        db.add(DatasetWriteBudget(dataset_id=identity, **entry))
    for entry in source["consents"]:
        db.add(DatasetAppConsent(dataset_id=identity, **entry))
    pending = list(source["tags"])
    while pending:
        progressed = False
        for tag in pending[:]:
            if tag["parent_id"] is not None and await db.get(DatasetTag, tag["parent_id"], execution_options={"include_historized": True}) is None:
                continue
            if await db.get(DatasetTag, tag["id"], execution_options={"include_historized": True}) is None:
                db.add(DatasetTag(**tag))
                await db.flush()
            pending.remove(tag)
            progressed = True
        if not progressed:
            raise ValueError("Dataset classification contains a cycle or missing parent")
    for tag_id in source["tag_ids"]:
        db.add(DatasetTagAssignment(dataset_id=identity, tag_id=tag_id))
    for user_id in set(source["icons"]) | set(source["positions"]):
        db.add(DatasetAppearance(dataset_id=identity, user_id=user_id, icon=source["icons"].get(user_id), position=source["positions"].get(user_id, 0)))
    source_hash = hashlib.sha256(record.content.encode()).hexdigest()
    db.add(DatasetAlias(legacy_document_id=identity, dataset_id=identity, source_revision=record.revision,
        source_hash=source_hash, manifest={"revisions": hashes, "grants": len(source["grants"]),
            "attachments": len(source["attachments"]), "budgets": len(source["budgets"]), "consents": len(source["consents"])}))
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
            hashes = {str(entry.revision): hashlib.sha256(entry.content.encode()).hexdigest() for entry in rows}
            if hashes.get(str(alias.source_revision)) != alias.source_hash:
                return False
            if any(hashes.get(number) != digest for number, digest in alias.manifest.get("revisions", {}).items()):
                return False
        cursor = identities[-1]
    return True
