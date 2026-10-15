"""Dataset references share the managed file registry and retain external URIs."""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.file_share import ResourceContext, parse_resource_uri, resource_info
from app.memory import validate_attachment_content
from core.database import get_db
from core.params import runtime_settings
from core.storage import DiskFileDriver, StoredFile, file_key, fingerprint, register_file, ensure_disk_identity
from core.util import complete_io

from .contracts import DataActor, DatasetPermissionError
from .models import DatasetAttachment
from . import service


async def attach_existing(identity: UUID, actor: DataActor, *, uri: str, agent_id: int,
                          name: str | None = None) -> DatasetAttachment:
    dataset = await service.record(identity, actor, write=True, lock=True)
    if dataset.metadata_.get("engine_managed"):
        raise DatasetPermissionError("Only the engine publishes attachments for this run")
    if not isinstance(actor, int):
        from app.agent import AgentManagementScope
        if not isinstance(actor, AgentManagementScope):
            raise DatasetPermissionError("An explicit managed Agent is required for an external provider")
        actor.require(agent_id)
    elif actor != agent_id:
        raise DatasetPermissionError("A resource must use its caller's connections")
    reference = parse_resource_uri(uri)
    descriptor = await resource_info(ResourceContext(agent_id=agent_id, runtime="internal"), str(reference))
    if descriptor.is_collection:
        raise ValueError("An attachment references an exact resource")
    record = DatasetAttachment(dataset_id=identity, uri=str(reference), name=(name or descriptor.name)[:512],
        media_type=descriptor.media_type, size_bytes=descriptor.size, sha256=descriptor.checksum,
        file_id=UUID(reference.locator) if reference.scheme == "file" else None)
    get_db().add(record)
    await get_db().flush()
    if record.file_id is not None:
        await register_file(record.file_id, name=record.name, media_type=record.media_type,
            alias=f"data://{identity}/attachments/{record.id}")
    return record


async def add_staged(identity: UUID, actor: DataActor, path: Path, *, name: str, media_type: str,
                     file_id: UUID | None = None, engine: bool = False) -> DatasetAttachment:
    dataset = await service.record(identity, actor, write=True, lock=True)
    if dataset.metadata_.get("engine_managed") and not (engine and actor == dataset.metadata_.get("engine_agent")):
        raise DatasetPermissionError("Only the engine publishes attachments for this run")
    db = get_db()
    identity_file = file_id or uuid4()
    existing = await db.scalar(select(DatasetAttachment).where(DatasetAttachment.dataset_id == identity,
        DatasetAttachment.file_id == identity_file))
    if existing is not None:
        return existing
    size, digest = await complete_io(fingerprint, path)
    if size > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
        raise ValueError("Attachment exceeds its file limit")
    await ensure_disk_identity(db)
    await complete_io(DiskFileDriver().publish, path, file_key(identity_file), size=size, sha256=digest)
    record = DatasetAttachment(id=uuid4(), dataset_id=identity, file_id=identity_file, uri=f"file://{identity_file}",
        name=Path(name.replace("\\", "/")).name[:512] or "file", media_type=media_type, size_bytes=size, sha256=digest)
    await register_file(identity_file, name=record.name, media_type=media_type,
        alias=f"data://{identity}/attachments/{record.id}")
    db.add(record)
    await db.flush()
    return record


async def add_bytes(identity: UUID, actor: DataActor, content: bytes, *, name: str) -> DatasetAttachment:
    if len(content) > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
        raise ValueError("Attachment exceeds its file limit")
    mime = validate_attachment_content(None, name, content)
    await ensure_disk_identity(get_db())
    with TemporaryDirectory(prefix=".dataset-", dir=DiskFileDriver().root) as directory:
        path = Path(directory) / "upload"
        await complete_io(path.write_bytes, content)
        record = await add_staged(identity, actor, path, name=name, media_type=mime)
        await get_db().commit()
        return record


async def list_attachments(identity: UUID, actor: DataActor) -> list[dict[str, Any]]:
    await service.record(identity, actor)
    rows = await get_db().scalars(select(DatasetAttachment).where(DatasetAttachment.dataset_id == identity).order_by(DatasetAttachment.created_at, DatasetAttachment.id))
    return [{"id": str(row.id), "uri": row.uri, "name": row.name, "media_type": row.media_type,
        "size_bytes": row.size_bytes, "sha256": row.sha256} for row in rows]


async def native_path(identity: UUID, attachment_id: UUID, actor: DataActor) -> tuple[dict[str, Any], Path] | None:
    await service.record(identity, actor)
    item = await get_db().scalar(select(DatasetAttachment).where(DatasetAttachment.id == attachment_id, DatasetAttachment.dataset_id == identity))
    if item is None or item.file_id is None:
        return None
    stored = await get_db().get(StoredFile, item.file_id)
    if stored is None or stored.backend != "disk" or stored.size_bytes > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
        raise ValueError("Dataset attachment unavailable or exceeds the read limit")
    return {"id": str(item.id), "name": item.name, "media_type": item.media_type,
        "size_bytes": stored.size_bytes, "created_at": item.created_at}, DiskFileDriver().path(stored.storage_key)


async def read_native(identity: UUID, attachment_id: UUID, actor: DataActor) -> tuple[dict[str, Any], bytes] | None:
    result = await native_path(identity, attachment_id, actor)
    if result is None:
        return None
    metadata, path = result
    def read() -> bytes:
        with path.open("rb") as stream:
            content = stream.read(runtime_settings.MEMORY_RESOURCE_MAX_BYTES + 1)
        if len(content) != metadata["size_bytes"]:
            raise ValueError("Dataset attachment size changed")
        return content
    return metadata, await complete_io(read)
