"""Public Memory metadata projection, without storage or persistence effects."""

from copy import deepcopy

from .contracts import MemoryAccess
from .models import MemoryItem
from .schemas import MemoryAccessPublic, MemoryItemPublic


def item_to_public(item: MemoryItem, access: MemoryAccess) -> MemoryItemPublic:
    return MemoryItemPublic.model_validate(
        {
            "id": item.id,
            "revision": item.revision,
            "lock_version": item.lock_version,
            "semantic_fingerprint": item.semantic_fingerprint,
            "owner_agent_id": item.owner_agent_id,
            "owner_user_id": item.owner_user_id,
            "provider_code": item.provider_code,
            "title": item.title,
            "memory_type": item.memory_type,
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
            "size_bytes": item.size_bytes,
            "last_accessed_at": item.last_accessed_at,
            "access_count": item.access_count,
            "valid_from": item.valid_from,
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
    )
