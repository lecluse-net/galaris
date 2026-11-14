"""Native binary snapshots share the managed file store and revision lifetime."""

from uuid import UUID

from core.database import get_db
from core.storage import StoredFile, register_file

from .models import Document


async def prepare_binary_content(content: bytes, *, name: str, media_type: str, document_id: UUID, revision: int) -> UUID:
    from core.storage import get_attachment_storage
    storage = get_attachment_storage()
    file_id = UUID(await storage.create(content))
    try:
        async with get_db().begin_nested():
            await register_file(file_id, name=name, media_type=media_type,
                alias=f"document://{document_id}/content-revisions/{revision}")
    except BaseException:
        await storage.delete(str(file_id))
        raise
    return file_id


async def bind_binary_content(document: Document, file_id: UUID) -> None:
    """Bind an already authorized immutable file inside the caller's transaction.

    The owning command authorizes the Document and obtains the source file.
    Keeping one alias per content revision protects historical bytes when the
    source or the current document stops referring to that file.
    """
    file = await get_db().get(StoredFile, file_id)
    if file is None:
        raise FileNotFoundError("Managed document content file not found")
    await register_file(file_id, name=file.name, media_type=file.media_type,
        alias=f"document://{document.id}/content-revisions/{document.revision}")
    document.storage_kind, document.file_id, document.content = "file", file_id, None
    document.provider_code, document.resource_id = "native", str(file_id)
    document.content_type, document.media_type = "binary", file.media_type
    document.content_profile_version = None
    document.content_hash, document.size_bytes = file.sha256, file.size_bytes
