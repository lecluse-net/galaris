"""Document metadata contains no personal memory payload."""
from copy import deepcopy
from collections.abc import Sequence
from .models import Document
from .contracts import DocumentAccess
from .schemas import DocumentPublic, DocumentAccessPublic


def item_to_public(item: Document, access: DocumentAccess, *, memory_content: bool = False, urls: Sequence[str] | None = None) -> DocumentPublic:
    return DocumentPublic.model_validate(dict(
        id=item.id, topic_id=item.topic_id, document_id=item.id, thumbnail_id=item.thumbnail_id,
        document_revision=item.revision,
        summary_outdated=bool(item.summary_pending and item.summary_size_bytes),
        revision=item.revision, lock_version=item.lock_version,
        owner_agent_id=item.owner_agent_id, owner_user_id=item.owner_user_id,
        provider_code=item.provider_code, title=item.title, node_kind="document",
        document_type=item.document_type, content_type=item.content_type, media_type=item.media_type,
        content_profile=item.content_profile, content_profile_version=item.content_profile_version,
        filename=item.filename, keywords=list(item.keywords), metadata=deepcopy(item.metadata_),
        visibility=item.visibility, global_access=item.global_access, read_only=item.read_only,
        deletion_protected=item.deletion_protected, source_managed=False,
        managed_source_kind=None, managed_source_ref=None, content_hash=item.content_hash,
        primary_url=f"document://{item.id}", urls=sorted(set(urls) if urls is not None else {row.url for row in item.url_relations}), size_bytes=item.size_bytes,
        last_accessed_at=item.last_accessed_at, access_count=item.access_count,
        valid_from=item.valid_from, valid_until=item.valid_until, temporal=item.temporal,
        old_at=None, old_reason=None, created_at=item.created_at, updated_at=item.updated_at,
        access=DocumentAccessPublic(can_read=access.can_read, can_write=access.can_write),
        grants=[{"agent_id": grant.agent_id,"can_write":grant.can_write} for grant in item.grants if grant.agent_id is not None],
    ))
