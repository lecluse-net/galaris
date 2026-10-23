"""Text payloads owned directly by current Memory/Document rows and revisions."""

from uuid import uuid4

from sqlalchemy import text

from core.database import get_db

from .contracts import ResourceStorageError


async def prepare_content(
    content: bytes, provider_code: str = "native", *, content_type: str = "text",
) -> tuple[str, str | None]:
    """Prepare a row-owned text value, retaining providers for binary/external data.

    The caller assigns the returned text to the owning row in its transaction.
    The opaque reference remains stable for old consumers and archived snapshots.
    """
    from core.storage import NativeFileStorage, get_storage

    provider = get_storage(provider_code)
    if provider_code == "native" and content_type in {"text", "json"} and type(provider) is NativeFileStorage:
        provider._validate_content(content)  # pyright: ignore[reportPrivateUsage]
        try:
            value = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ResourceStorageError("Memory text must be valid UTF-8") from None
        if "\x00" in value:
            raise ResourceStorageError("Memory text cannot contain NUL characters")
        return str(uuid4()), value
    return await provider.create(content), None


async def read_inline_content(resource_ref: str) -> bytes | None:
    """Compatibility lookup for native pointers, after the owning domain's ACL.

    Explicit column projections keep text out of ordinary metadata/list queries.
    Unflushed owners are visible without prematurely flushing their relations.
    """
    try:
        db = get_db()
    except RuntimeError:
        return None
    from .models import MemoryItem, MemoryRevision
    for record in (*db.new,*db.dirty):
        values=record.__dict__
        if isinstance(record,MemoryItem):
            if values.get("memory_provider_code")=="native" and values.get("memory_resource_id")==resource_ref and isinstance(values.get("memory_content"),str):
                return str(values["memory_content"]).encode()
        elif isinstance(record,MemoryRevision):
            if values.get("provider_code")=="native" and values.get("resource_id")==resource_ref and isinstance(values.get("content"),str):
                return str(values["content"]).encode()
    with db.no_autoflush:
        value=await db.scalar(text("SELECT content FROM memory_items WHERE provider_code='native' AND resource_id=:ref UNION ALL SELECT content FROM memory_revisions WHERE provider_code='native' AND resource_id=:ref LIMIT 1"),{"ref":resource_ref})
        return str(value).encode() if value is not None else None
