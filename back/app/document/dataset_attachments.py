"""Live Dataset references attached to authored Documents, without copying JSON."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor
from . import resource_service as service
from .models import Document
from .schemas import DocumentUpdate

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
        raise service.DocumentNotFoundError("Dataset service unavailable")
    return await _reader(identity, actor)


def _identities(document: Document) -> list[UUID]:
    raw = cast(object, document.metadata_.get(_KEY, []))
    if not isinstance(raw, list):
        raise service.DocumentConflictError("Invalid Dataset attachment manifest")
    values = cast(list[object], raw)
    if len(values) > _LIMIT:
        raise service.DocumentConflictError("Invalid Dataset attachment manifest")
    targets: list[UUID] = []
    for uri in values:
        try:
            target = UUID(uri.removeprefix("data://")) if isinstance(uri, str) else None
        except ValueError as exc:
            raise service.DocumentConflictError("Invalid Dataset attachment reference") from exc
        if target is None or uri != f"data://{target}":
            raise service.DocumentConflictError("Invalid Dataset attachment reference")
        if target not in targets:
            targets.append(target)
    return targets


async def document_for_references(identity: UUID, actor: int | HumanActor, *, write: bool = False) -> Document:
    if write:
        await get_db().scalar(select(Document.id).where(Document.id == identity).with_for_update())
    document = await service.document_record(identity, revisions=False)
    if document is None or document.document_type != "html" or document.content_profile != "document":
        raise service.DocumentNotFoundError("Authored Document not found")
    await service.assert_item_access(document, actor, write=write)
    return document


async def list_references(identity: UUID, actor: int | HumanActor, *, dataset_actor: DatasetAttachmentActor) -> tuple[list[DatasetAttachmentReference], int]:
    document = await document_for_references(identity, actor)
    references: list[DatasetAttachmentReference] = []
    for target in _identities(document):
        try:
            references.append(await _reference(target, dataset_actor))
        except (FileNotFoundError, PermissionError):
            references.append(DatasetAttachmentReference(uri=f"data://{target}", title=None, available=False))
    return references, document.lock_version


async def change_reference(identity: UUID, target: UUID, actor: int | HumanActor, *, dataset_actor: DatasetAttachmentActor,
    expected_lock_version: int, remove: bool = False) -> tuple[list[DatasetAttachmentReference], int]:
    document = await document_for_references(identity, actor, write=True)
    targets = _identities(document)
    changed = (target in targets) if remove else (target not in targets)
    if not changed:
        return await list_references(identity, actor, dataset_actor=dataset_actor)
    if expected_lock_version != document.lock_version:
        raise service.DocumentConflictError("The Document changed; reload before changing attachments")
    if remove:
        targets.remove(target)
    else:
        try:
            await _reference(target, dataset_actor)
        except (FileNotFoundError, PermissionError) as exc:
            raise service.DocumentNotFoundError("Dataset not found") from exc
        if len(targets) >= _LIMIT:
            raise ValueError("A Document supports at most 50 attached Datasets")
        targets.append(target)
    metadata = {**document.metadata_, _KEY: [f"data://{entry}" for entry in targets]}
    await service.update_item(identity, DocumentUpdate(expected_lock_version=expected_lock_version, metadata=metadata), actor_agent_id=actor)
    return await list_references(identity, actor, dataset_actor=dataset_actor)
