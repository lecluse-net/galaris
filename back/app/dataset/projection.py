"""Optional metadata projection; it never provides a competing write path."""

from app.share import ShareGrant

import hashlib

from sqlalchemy import select
from app.memory.contracts import DatasetDocumentGrant, DatasetDocumentProjection, DatasetProjectionWriter
from core.database import get_db
from .models import Dataset, DatasetAlias

_writer: DatasetProjectionWriter | None = None


def register_projection_writer(writer: DatasetProjectionWriter) -> None:
    global _writer
    _writer = writer


async def changed(dataset: Dataset) -> None:
    if _writer is None:
        return
    alias = (await get_db().execute(
        select(DatasetAlias.legacy_document_id, Dataset.deleted_at)
        .join(Dataset, Dataset.id == DatasetAlias.dataset_id)
        .where(DatasetAlias.dataset_id == dataset.id)
        .execution_options(include_historized=True)
    )).one_or_none()
    if alias is None:
        return
    # soft_delete() uses a SQL timestamp expression; read its value asynchronously
    # in this query rather than triggering an implicit load of an expired attribute.
    legacy = alias.legacy_document_id
    if alias.deleted_at is not None:
        await _writer(legacy, None)
        return
    grants = await get_db().scalars(select(ShareGrant).where(ShareGrant.share_id == dataset.share_id))
    content = dataset.content.encode("utf-8")
    await _writer(legacy, DatasetDocumentProjection(
        title=dataset.title, revision=dataset.revision, lock_version=dataset.lock_version,
        content_hash=hashlib.sha256(content).hexdigest(), size_bytes=len(content),
        owner_agent_id=dataset.owner_agent_id, owner_user_id=dataset.owner_user_id,
        global_access=dataset.global_access, group_access=dataset.group_access,
        read_only=dataset.read_only, keywords=tuple(dataset.keywords), metadata=dict(dataset.metadata_),
        grants=tuple(DatasetDocumentGrant(
            agent_id=entry.agent_id, user_id=entry.user_id, team_id=entry.team_id, can_write=entry.can_write,
        ) for entry in grants),
    ))
