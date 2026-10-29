"""Shared editorial summaries, governed and persisted entirely by Document."""

from uuid import UUID
from hashlib import sha256


from core.storage import get_storage
from core.user import HumanActor

from . import resource_service as service
from .schemas import DocumentDetail, DocumentUpdate


async def read_summary(
    identity: UUID, *, actor: int | HumanActor,
) -> DocumentDetail:
    item, access = await service.get_item_metadata(identity, agent_id=actor)
    provider = item.summary_provider_code
    pointer = item.summary_resource_id
    content = await get_storage(provider).read(pointer) if pointer and item.summary_size_bytes else b""
    values = service.item_to_public(item, access).model_dump()
    values.update(
        revision=item.revision,
        provider_code=provider, content_hash=sha256(content).hexdigest(),
        size_bytes=len(content), content_type="text", media_type=item.summary_media_type,
        content_profile="rich-text", content_profile_version=1,
    )
    return DocumentDetail(**values, payload=service.encode_payload(content, content_type="text", media_type=item.summary_media_type),
        source_refs=await service.source_refs(identity))


async def edit_summary(identity: UUID, data: DocumentUpdate, *, actor: int | HumanActor) -> DocumentDetail:
    await service.update_summary(identity, data, actor_agent_id=actor)
    return await read_summary(identity, actor=actor)
