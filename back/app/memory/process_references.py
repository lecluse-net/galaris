"""Document membership stores only native Process URIs; Process retains every ACL."""

from typing import Any, cast
from uuid import UUID

from app.agent import AgentManagementScope
from app.process import process_reference, process_resource_preview
from core.user import HumanActor

from . import service
from .dataset_attachments import document_for_references
from .models import MemoryItem
from .schemas import MemoryItemUpdate

_KEY = "process_attachments"


def _targets(document: MemoryItem) -> list[str]:
    raw = document.metadata_.get(_KEY, [])
    if not isinstance(raw, list):
        raise service.MemoryConflictError("Invalid Process attachment manifest")
    values = cast(list[object], raw)
    if len(values) > 50:
        raise service.MemoryConflictError("Invalid Process attachment manifest")
    targets: list[str] = []
    for uri in values:
        if not isinstance(uri, str):
            raise service.MemoryConflictError("Invalid Process attachment reference")
        try:
            _, _, canonical = process_reference(uri)
        except ValueError as exc:
            raise service.MemoryConflictError("Invalid Process attachment reference") from exc
        if canonical != uri:
            raise service.MemoryConflictError("Invalid Process attachment reference")
        if canonical not in targets:
            targets.append(canonical)
    return targets


async def references(identity: UUID, actor: int | HumanActor, process_actor: int | AgentManagementScope) -> dict[str, Any]:
    document = await document_for_references(identity, actor)
    items: list[dict[str, Any]] = []
    for uri in _targets(document):
        try:
            kind, _, canonical = process_reference(uri)
            preview = await process_resource_preview(canonical, process_actor)
            items.append({"uri": canonical, "kind": kind, "title": preview["title"], "available": True})
        except (ValueError, LookupError, PermissionError):
            items.append({"uri": uri, "title": None, "available": False})
    return {"items": items, "lock_version": document.lock_version}


async def change_reference(identity: UUID, actor: int | HumanActor, process_actor: int | AgentManagementScope,
    *, uri: str, expected_lock_version: int, remove: bool = False) -> dict[str, Any]:
    _, _, canonical = process_reference(uri)
    document = await document_for_references(identity, actor, write=True)
    targets = _targets(document)
    changed = canonical in targets if remove else canonical not in targets
    if not changed:
        return await references(identity, actor, process_actor)
    if document.lock_version != expected_lock_version:
        raise service.MemoryConflictError("The Document changed; reload before changing attachments")
    if remove:
        targets.remove(canonical)
    else:
        try:
            await process_resource_preview(canonical, process_actor)
        except (LookupError, PermissionError) as exc:
            raise service.MemoryNotFoundError("Process reference unavailable") from exc
        if len(targets) >= 50:
            raise ValueError("A Document supports at most 50 Process references")
        targets.append(canonical)
    await service.update_item(identity, MemoryItemUpdate(expected_lock_version=expected_lock_version,
        metadata={**document.metadata_, _KEY: targets}), actor_agent_id=actor)
    return await references(identity, actor, process_actor)
