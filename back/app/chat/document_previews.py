"""Title-only tombstones for document references in authorized Chat messages."""

from uuid import UUID

from app.conversation import resolve_conversation_document_metadata
from app.messenger import MessageResourcePreview


async def with_deleted_document_previews(
    references: tuple[str, ...],
    previews: list[MessageResourcePreview],
) -> list[MessageResourcePreview]:
    """Complete message previews without treating denied or missing resources as deleted.

    Call only with references extracted from a message the viewer can read.
    Historical titles are presentation metadata; this never restores resource access.
    """
    by_uri = {preview.uri: preview for preview in previews}
    missing: dict[str, UUID] = {}
    for uri in references:
        if uri in by_uri or not uri.startswith("document://"):
            continue
        try:
            missing[uri] = UUID(uri.removeprefix("document://"))
        except ValueError:
            continue
    if not missing:
        return previews
    metadata = await resolve_conversation_document_metadata(tuple(missing.values()))
    for uri, document_id in missing.items():
        document = metadata.get(document_id)
        if document is not None and document.deleted:
            by_uri[uri] = MessageResourcePreview(
                uri=uri, kind="document", title=document.title, deleted=True,
            )
    return [by_uri[uri] for uri in references if uri in by_uri]
