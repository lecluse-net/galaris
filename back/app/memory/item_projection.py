"""Public Memory metadata projection, without storage or persistence effects."""

from copy import deepcopy

from .contracts import MemoryAccess
from .models import MemoryItem
from .schemas import MemoryAccessPublic, MemoryItemPublic


def item_to_public(
    item: MemoryItem, access: MemoryAccess, *, memory_content: bool = False
) -> MemoryItemPublic:
    values = {
        "document_id": item.document.id if item.document is not None else None,
        "thumbnail_id": item.document.thumbnail_id if item.document is not None else None,
        "document_revision": item.document.revision if item.document is not None else None,
        "summary_document_revision": item.summary_document_revision,
        "summary_outdated": item.document is not None
        and item.summary_document_revision is not None
        and item.summary_document_revision != item.document.revision,
        "id": item.id,
        "revision": item.revision,
        "lock_version": item.lock_version,
        "semantic_fingerprint": item.semantic_fingerprint,
        "owner_agent_id": item.owner_agent_id,
        "owner_user_id": item.owner_user_id,
        "provider_code": item.provider_code,
        "title": item.title,
        "node_kind": item.node_kind,
        "document_type": item.document_type,
        "content_type": item.content_type,
        "media_type": item.media_type,
        "content_profile": item.content_profile,
        "content_profile_version": item.content_profile_version,
        "filename": item.filename,
        "keywords": list(item.keywords),
        "metadata": deepcopy(item.metadata_),
        "visibility": item.visibility,
        "global_access": item.global_access,
        "read_only": item.read_only,
        "deletion_protected": item.deletion_protected,
        "source_managed": item.source_managed,
        "managed_source_kind": item.managed_source_kind,
        "managed_source_ref": item.managed_source_ref,
        "content_hash": item.content_hash,
        "file_sha256": item.file_sha256,
        "file_media_type": item.file_media_type,
        "file_size_bytes": item.file_size_bytes,
        "primary_url": item.primary_url,
        "urls": sorted({location.url for location in item.url_relations}),
        "size_bytes": item.size_bytes,
        "last_accessed_at": item.last_accessed_at,
        "access_count": item.access_count,
        "valid_from": item.valid_from,
        "temporal": item.temporal,
        "valid_until": item.valid_until,
        "old_at": item.old_at,
        "old_reason": item.old_reason,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "access": MemoryAccessPublic(can_read=access.can_read, can_write=access.can_write),
        "grants": [
            {"agent_id": grant.agent_id, "can_write": grant.can_write}
            for grant in sorted(item.grants, key=lambda value: value.agent_id)
        ],
    }
    if memory_content and item.document is not None:
        values.update(
            revision=item.memory_revision,
            provider_code=item.memory_provider_code,
            document_type="html",
            content_type="text",
            media_type="text/html",
            content_profile="rich-text",
            content_profile_version=1,
            filename=None,
            content_hash=item.memory_content_hash,
            size_bytes=item.memory_size_bytes,
        )
    return MemoryItemPublic.model_validate(values)
