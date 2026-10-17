"""Live Dataset references attached to authored Documents, without copying JSON."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor
from . import service
from .models import MemoryItem
from .schemas import MemoryItemUpdate

DatasetAttachmentActor = int | HumanActor | AgentManagementScope


@dataclass(frozen=True, slots=True)
class DatasetAttachmentReference:
    uri: str
    title: str | None
    available: bool = True


DatasetAttachmentReader = Callable[[UUID, DatasetAttachmentActor], Awaitable[DatasetAttachmentReference]]
_reader: DatasetAttachmentReader | None = None
_KEY = "dataset_attachments"
_LIMIT = 50


def register_dataset_attachment_reader(reader: DatasetAttachmentReader) -> None:
    global _reader
    _reader = reader


async def _reference(identity: UUID, actor: DatasetAttachmentActor) -> DatasetAttachmentReference:
    if _reader is None:
        raise service.MemoryNotFoundError("Dataset service unavailable")
    return await _reader(identity, actor)


def _identities(document: MemoryItem) -> list[UUID]:
    raw = cast(object, document.metadata_.get(_KEY, []))
    if not isinstance(raw, list):
        raise service.MemoryConflictError("Invalid Dataset attachment manifest")
    values = cast(list[object], raw)
    if len(values) > _LIMIT:
        raise service.MemoryConflictError("Invalid Dataset attachment manifest")
    targets: list[UUID] = []
    for uri in values:
        try:
            target = UUID(uri.removeprefix("data://")) if isinstance(uri, str) else None
        except ValueError as exc:
            raise service.MemoryConflictError("Invalid Dataset attachment reference") from exc
        if target is None or uri != f"data://{target}":
            raise service.MemoryConflictError("Invalid Dataset attachment reference")
        if target not in targets:
            targets.append(target)
    return targets


async def _document(identity: UUID, actor: int | HumanActor, *, write: bool = False) -> MemoryItem:
    if write:
        await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == identity).with_for_update())
    document = await service.document_record(identity, revisions=False)
    if document is None or document.document_type != "html" or document.content_profile != "document":
        raise service.MemoryNotFoundError("Authored Document not found")
    await service.assert_item_access(document, actor, write=write)
    return document


async def list_references(identity: UUID, actor: int | HumanActor, *, dataset_actor: DatasetAttachmentActor) -> tuple[list[DatasetAttachmentReference], int]:
    document = await _document(identity, actor)
    references: list[DatasetAttachmentReference] = []
    for target in _identities(document):
        try:
            references.append(await _reference(target, dataset_actor))
        except (FileNotFoundError, PermissionError):
            references.append(DatasetAttachmentReference(uri=f"data://{target}", title=None, available=False))
    return references, document.lock_version


async def change_reference(identity: UUID, target: UUID, actor: int | HumanActor, *, dataset_actor: DatasetAttachmentActor,
    expected_lock_version: int, remove: bool = False) -> tuple[list[DatasetAttachmentReference], int]:
    document = await _document(identity, actor, write=True)
    targets = _identities(document)
    changed = (target in targets) if remove else (target not in targets)
    if not changed:
        return await list_references(identity, actor, dataset_actor=dataset_actor)
    if expected_lock_version != document.lock_version:
        raise service.MemoryConflictError("The Document changed; reload before changing attachments")
    if remove:
        targets.remove(target)
    else:
        try:
            await _reference(target, dataset_actor)
        except (FileNotFoundError, PermissionError) as exc:
            raise service.MemoryNotFoundError("Dataset not found") from exc
        if len(targets) >= _LIMIT:
            raise ValueError("A Document supports at most 50 attached Datasets")
        targets.append(target)
    metadata = {**document.metadata_, _KEY: [f"data://{entry}" for entry in targets]}
    await service.update_item(identity, MemoryItemUpdate(expected_lock_version=expected_lock_version, metadata=metadata), actor_agent_id=actor)
    return await list_references(identity, actor, dataset_actor=dataset_actor)
