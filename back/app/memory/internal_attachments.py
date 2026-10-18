"""Document membership in file-share resources, with independent source permissions."""

from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

from core.user import HumanActor
from app.agent import AgentManagementScope
from app.process import process_reference
from . import service
from .dataset_attachments import document_for_references
from .models import MemoryItem
from .schemas import MemoryItemUpdate

AttachmentReader = Callable[[str, int, AgentManagementScope | None], Awaitable[dict[str, Any]]]
_reader: AttachmentReader | None = None
_KEYS = ("resource_attachments", "dataset_attachments", "process_attachments")


def register_internal_attachment_reader(reader: AttachmentReader) -> None:
    global _reader
    _reader = reader


def internal_attachment_uris(document: MemoryItem) -> list[str]:
    values: list[str] = []
    for key in _KEYS:
        raw = document.metadata_.get(key, [])
        if (not isinstance(raw, list) or len(cast(list[object], raw)) > 50
            or any(not isinstance(uri, str) or len(uri) > 4096 for uri in cast(list[object], raw))):
            raise service.MemoryConflictError("Invalid internal attachment manifest")
        values.extend(cast(list[str], raw))
    return list(dict.fromkeys(values))


async def _read(uri: str, agent_id: int, scope: AgentManagementScope | None) -> dict[str, Any]:
    if _reader is None:
        raise service.MemoryNotFoundError("File sharing unavailable")
    return await _reader(uri, agent_id, scope)


async def references(identity: UUID, actor: int | HumanActor, resource_agent_id: int,
    *, scope: AgentManagementScope | None = None) -> dict[str, Any]:
    document = await document_for_references(identity, actor)
    items: list[dict[str, Any]] = []
    for uri in internal_attachment_uris(document):
        try:
            items.append({**await _read(uri, resource_agent_id, scope), "available": True})
        except (OSError, TimeoutError, PermissionError, ValueError, LookupError, NotImplementedError,
                service.MemoryPermissionError, service.MemoryNotFoundError):
            items.append({"uri": uri, "name": None, "available": False})
    return {"items": items, "lock_version": document.lock_version}


async def change_references(identity: UUID, actor: int | HumanActor, resource_agent_id: int,
    *, uris: list[str], expected_lock_version: int, remove: bool = False, scope: AgentManagementScope | None = None) -> dict[str, Any]:
    document = await document_for_references(identity, actor, write=True)
    current = internal_attachment_uris(document)
    # Validate every new source before changing membership; a failed batch changes nothing.
    targets = list(dict.fromkeys(uris))
    if not remove:
        try:
            resolved = [str((await _read(uri, resource_agent_id, scope))["uri"]) for uri in targets]
            targets = list(dict.fromkeys(resolved))
        except (FileNotFoundError, PermissionError, LookupError, service.MemoryPermissionError) as exc:
            raise service.MemoryNotFoundError("Internal attachment unavailable") from exc
    updated = [uri for uri in current if uri not in targets] if remove else list(dict.fromkeys([*current, *targets]))
    if updated == current:
        return await references(identity, actor, resource_agent_id, scope=scope)
    if document.lock_version != expected_lock_version:
        raise service.MemoryConflictError("The Document changed; reload before changing attachments")
    if len(updated) > 150:
        raise ValueError("A Document supports at most 150 internal attachments")
    metadata = dict(document.metadata_)
    if remove:
        for key in _KEYS:
            metadata[key] = [uri for uri in metadata.get(key, []) if uri not in targets]
    else:
        for uri in targets:
            if uri in current:
                continue
            key = "resource_attachments"
            if uri.startswith("data://") and "/" not in uri.removeprefix("data://"):
                key = "dataset_attachments"
            else:
                try:
                    if process_reference(uri)[2] == uri:
                        key = "process_attachments"
                except ValueError:
                    pass
            entries = [*metadata.get(key, []), uri]
            if len(entries) > 50:
                raise ValueError("A Document supports at most 50 attachments of each resource family")
            metadata[key] = entries
    await service.update_item(identity, MemoryItemUpdate(expected_lock_version=expected_lock_version,
        metadata=metadata), actor_agent_id=actor)
    return await references(identity, actor, resource_agent_id, scope=scope)
