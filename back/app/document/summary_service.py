"""Shared editorial summaries, governed and persisted entirely by Document."""

from uuid import UUID
from hashlib import sha256

from sqlalchemy import select

from core.database import get_db
from core.storage import get_storage
from core.user import HumanActor

from . import resource_service as service
from .models import DocumentSummaryRevision
from .schemas import DocumentDetail, DocumentUpdate


async def read_summary(
    identity: UUID, *, actor: int | HumanActor, revision: int | None = None,
) -> DocumentDetail:
    item, access = await service.get_item_metadata(identity, agent_id=actor)
    selected = None
    if revision is not None and revision != item.summary_revision:
        selected = await get_db().scalar(select(DocumentSummaryRevision).where(
            DocumentSummaryRevision.document_id == identity,
            DocumentSummaryRevision.revision == revision,
        ))
        if selected is None and revision != 1:
            raise service.DocumentNotFoundError("Document summary revision not found")
    provider = selected.provider_code if selected is not None else item.summary_provider_code
    pointer = selected.resource_id if selected is not None else item.summary_resource_id
    if revision == 1 and item.summary_revision != 1 and selected is None:
        pointer = ""
    content = await get_storage(provider).read(pointer) if pointer else b""
    values = service.item_to_public(item, access).model_dump()
    values.update(
        revision=revision or item.summary_revision,
        provider_code=provider, content_hash=sha256(content).hexdigest(),
        size_bytes=len(content), content_type="text", media_type="text/html",
        content_profile="rich-text", content_profile_version=1,
    )
    if selected is not None:
        values.update(keywords=list(selected.keywords), temporal=selected.temporal)
    return DocumentDetail(**values, payload=service.encode_payload(content, content_type="text", media_type="text/html"),
        source_refs=await service.source_refs(identity))


async def edit_summary(identity: UUID, data: DocumentUpdate, *, actor: int | HumanActor) -> DocumentDetail:
    await service.update_summary(identity, data, actor_agent_id=actor)
    return await read_summary(identity, actor=actor)
