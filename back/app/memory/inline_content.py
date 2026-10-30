"""Text payloads owned directly by current Memory/Document rows and revisions."""

from uuid import UUID, uuid4

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
            if values.get("memory_resource_id") == resource_ref and values.get("source_managed") and values.get("managed_source_kind") == "messenger_contact":
                from .contact_directory import read_contact_json
                return await read_contact_json(record.id)
            if values.get("memory_provider_code")=="native" and values.get("memory_resource_id")==resource_ref and isinstance(values.get("memory_content"),str):
                return str(values["memory_content"]).encode()
        elif isinstance(record,MemoryRevision):
            if values.get("resource_id") == resource_ref and values.get("metadata_", {}).get("source_kind") == "messenger_contact":
                from .contact_directory import read_contact_json
                return await read_contact_json(record.item_id)
            if values.get("provider_code")=="native" and values.get("resource_id")==resource_ref and isinstance(values.get("content"),str):
                return str(values["content"]).encode()
    with db.no_autoflush:
        row = (await db.execute(text(
            "SELECT item.content, item.id, item.source_managed AND "
            "item.managed_source_kind='messenger_contact' AS live_contact "
            "FROM memory_items item WHERE item.provider_code='native' AND item.resource_id=:ref "
            "UNION ALL SELECT revision.content, item.id, item.source_managed AND "
            "item.managed_source_kind='messenger_contact' AS live_contact "
            "FROM memory_revisions revision JOIN memory_items item ON item.id=revision.item_id "
            "WHERE revision.provider_code='native' AND revision.resource_id=:ref LIMIT 1"
        ), {"ref": resource_ref})).first()
    if row is None:
        return None
    if row.live_contact:
        from .contact_directory import read_contact_json
        return await read_contact_json(UUID(str(row.id)))
    return str(row.content).encode() if row.content is not None else None
