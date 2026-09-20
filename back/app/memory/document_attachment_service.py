"""Bounded attachments owned by mutable Memory documents."""

from __future__ import annotations

import mimetypes
from io import BytesIO
from PIL import Image, UnidentifiedImageError
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from core.database import get_db

from core.user import HumanActor

from core.params import runtime_settings

from . import service
from .contracts import ResourceTooLargeError
from .models import DocumentAttachment, MemoryItem
from .schemas import DocumentAttachmentPublic, MemoryItemUpdate
from .storage import NativeFileStorage, get_storage


ATTACHMENT_METADATA_KEY = "document_attachments"
_CHUNK_SIZE = 1024 * 1024
_MAX_ATTACHMENTS = 50
_ACTIVE_MEDIA_TYPES = {
    "application/javascript",
    "application/x-msdownload",
    "application/x-sh",
    "image/svg+xml",
    "text/javascript",
}


def _assert_document(item: MemoryItem) -> None:
    if item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")


def _safe_name(value: str | None, attachment_id: UUID) -> str:
    name = Path((value or "").replace("\\", "/")).name.strip()
    return (name or str(attachment_id))[:500]


def _validated_media_type(declared: str | None, name: str, content: bytes) -> str:
    fallback = mimetypes.guess_type(name)[0] or "application/octet-stream"
    media_type = (declared or fallback).split(";", 1)[0].strip().casefold()
    if media_type == "application/octet-stream":
        media_type = fallback.casefold()
    prefix = content[:8_192].lstrip().lower()
    if media_type in {"text/html", "application/xhtml+xml"} or prefix.startswith((b"<!doctype html", b"<html")):
        return "text/html"
    if (
        media_type in _ACTIVE_MEDIA_TYPES
        or prefix.startswith((b"<!doctype html", b"<html", b"<script", b"#!", b"<svg"))
        or (prefix.startswith(b"<?xml") and b"<svg" in prefix)
    ):
        raise ValueError("This active or executable attachment type is not accepted.")
    if media_type.startswith("image/"):
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP", "GIF"} or image.width * image.height > 40_000_000 or max(image.size) > 16_000:
                    raise ValueError("Unsupported image format or dimensions.")
                detected = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[image.format]
                image.verify()
                if detected != media_type:
                    raise ValueError("Image MIME does not match decoded content.")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid raster attachment.") from exc
    return media_type


def _attachment_from_metadata(raw: object) -> DocumentAttachmentPublic | None:
    if not isinstance(raw, dict):
        return None
    try:
        return DocumentAttachmentPublic.model_validate(raw)
    except ValueError:
        return None


def attachments_from_item(item: MemoryItem, *, include_retained: bool = False) -> list[DocumentAttachmentPublic]:
    raw_attachments_value = item.metadata_.get(ATTACHMENT_METADATA_KEY, [])
    if not isinstance(raw_attachments_value, list):
        return []
    raw_attachments = list(cast(list[object], raw_attachments_value))
    retained = item.metadata_.get("retained_document_attachments", [])
    if include_retained and isinstance(retained, list):
        raw_attachments.extend(cast(list[object], retained))
    attachments = [
        attachment
        for raw in raw_attachments
        if (attachment := _attachment_from_metadata(raw)) is not None
    ]
    return sorted(attachments, key=lambda value: (value.created_at, str(value.id)))


def _metadata_with_attachments(
    item: MemoryItem,
    attachments: list[DocumentAttachmentPublic],
) -> dict[str, Any]:
    metadata = dict(item.metadata_)
    if attachments:
        metadata[ATTACHMENT_METADATA_KEY] = [
            attachment.model_dump(mode="json", exclude={"memory_item_id"}) for attachment in attachments
        ]
    else:
        metadata.pop(ATTACHMENT_METADATA_KEY, None)
    return metadata


async def list_document_attachments(
    document_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
) -> list[DocumentAttachmentPublic]:
    item, _content, _access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
    )
    _assert_document(item)
    return await attachment_companions(attachments_from_item(item))


async def attachment_companions(attachments: list[DocumentAttachmentPublic]) -> list[DocumentAttachmentPublic]:
    """Enrich an already authorized manifest with its persisted 1:1 pointers."""
    pointers = {row.id: row.memory_item_id for row in await get_db().scalars(
        select(DocumentAttachment).where(DocumentAttachment.id.in_([attachment.id for attachment in attachments])),
    )}
    return [attachment.model_copy(update={"memory_item_id": pointers.get(attachment.id)}) for attachment in attachments]


async def add_document_attachment(
    document_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
    upload: UploadFile,
) -> DocumentAttachmentPublic:
    item, _content, access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
    )
    _assert_document(item)
    if not access.can_write:
        raise service.MemoryPermissionError("Document edit access denied.")
    if item.content_profile != "document":
        raise service.MemoryPermissionError("Attachments cannot be added to Goal documents.")
    if len(attachments_from_item(item)) >= _MAX_ATTACHMENTS:
        raise ValueError(f"A document accepts at most {_MAX_ATTACHMENTS} attachments.")
    limit = runtime_settings.MEMORY_RESOURCE_MAX_BYTES
    if upload.size is not None and upload.size > limit:
        raise ValueError(f"The attachment exceeds the {limit}-byte limit.")
    first_chunk = await upload.read(_CHUNK_SIZE)
    attachment_id = uuid4()
    safe_name = _safe_name(upload.filename, attachment_id)
    declared_media_type = upload.content_type or mimetypes.guess_type(safe_name)[0]
    validated_media_type = declared_media_type or "application/octet-stream"
    if not validated_media_type.startswith("image/"):
        validated_media_type = _validated_media_type(declared_media_type, safe_name, first_chunk)

    async def chunks() -> AsyncIterator[bytes]:
        if first_chunk:
            yield first_chunk
        while chunk := await upload.read(_CHUNK_SIZE):
            yield chunk

    provider = get_storage("native")
    if not isinstance(provider, NativeFileStorage):
        raise service.MemoryConflictError(
            "Document attachments require the native storage provider."
        )
    try:
        resource_id, size = await provider.create_stream(chunks())
    except ResourceTooLargeError as exc:
        raise ValueError(f"The attachment exceeds the {limit}-byte limit.") from exc
    try:
        if validated_media_type.startswith("image/"):
            validated_media_type = _validated_media_type(validated_media_type, safe_name, await provider.read(resource_id))
    except BaseException:
        await provider.delete(resource_id)
        raise
    attachment = DocumentAttachmentPublic(
        id=UUID(resource_id),
        name=safe_name,
        media_type=validated_media_type,
        size_bytes=size,
        created_at=datetime.now(timezone.utc),
    )
    return await _register_document_attachment(
        document_id,
        actor_agent_id=actor_agent_id,
        attachment=attachment,
    )


async def add_document_attachment_bytes(
    document_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
    name: str | None,
    media_type: str | None,
    content: bytes,
) -> DocumentAttachmentPublic:
    limit = runtime_settings.MEMORY_RESOURCE_MAX_BYTES
    if len(content) > limit:
        raise ValueError(f"The attachment exceeds the {limit}-byte limit.")
    attachment_id = uuid4()
    safe_name = _safe_name(name, attachment_id)
    validated_media_type = _validated_media_type(media_type, safe_name, content)
    attachment = DocumentAttachmentPublic(
        id=attachment_id,
        name=safe_name,
        media_type=validated_media_type,
        size_bytes=len(content),
        created_at=datetime.now(timezone.utc),
    )
    provider = get_storage("native")
    resource_id = await provider.create(content)
    if resource_id != str(attachment_id):
        attachment = attachment.model_copy(update={"id": UUID(resource_id)})
    return await _register_document_attachment(
        document_id,
        actor_agent_id=actor_agent_id,
        attachment=attachment,
    )


async def _register_document_attachment(
    document_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
    attachment: DocumentAttachmentPublic,
) -> DocumentAttachmentPublic:
    provider = get_storage("native")
    try:
        for _attempt in range(3):
            item, _content, access, _content_type, _media_type = await service.get_item(
                document_id,
                agent_id=actor_agent_id,
            )
            _assert_document(item)
            if not access.can_write:
                raise service.MemoryPermissionError("Document edit access denied.")
            if item.content_profile != "document":
                raise service.MemoryPermissionError("Attachments cannot be added to Goal documents.")
            attachments = attachments_from_item(item)
            if len(attachments) >= _MAX_ATTACHMENTS:
                raise ValueError(
                    f"A document accepts at most {_MAX_ATTACHMENTS} attachments."
                )
            try:
                await service.update_item(
                    item.id,
                    MemoryItemUpdate(
                        expected_revision=item.revision,
                        expected_lock_version=item.lock_version,
                        metadata=_metadata_with_attachments(
                            item,
                            [*attachments, attachment],
                        ),
                    ),
                    actor_agent_id=actor_agent_id,
                    preserve_document_attachments=False,
                )
                return (await attachment_companions([attachment]))[0]
            except service.MemoryConflictError:
                continue
        raise service.MemoryConflictError(
            "The document changed while the attachment was being added."
        )
    except BaseException:
        await provider.delete(str(attachment.id))
        raise


async def read_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
) -> tuple[DocumentAttachmentPublic, bytes]:
    item, _content, _access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
    )
    _assert_document(item)
    attachment = next(
        (value for value in attachments_from_item(item, include_retained=True) if value.id == attachment_id),
        None,
    )
    if attachment is None:
        raise service.MemoryNotFoundError("Document attachment not found.")
    return attachment, await get_storage("native").read(str(attachment.id))


async def document_attachment_path(
    document_id: UUID,
    attachment_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
) -> tuple[DocumentAttachmentPublic, Path]:
    """Resolve one authorized native attachment to a streaming response path."""

    item, _content, _access, _type, _mime = await service.get_item(document_id, agent_id=actor_agent_id)
    _assert_document(item)
    attachments = attachments_from_item(item, include_retained=True)
    attachment = next((value for value in attachments if value.id == attachment_id), None)
    if attachment is None:
        raise service.MemoryNotFoundError("Document attachment not found.")
    provider = get_storage("native")
    if not isinstance(provider, NativeFileStorage):
        raise service.MemoryConflictError(
            "Document attachments require the native storage provider."
        )
    return attachment, await provider.path_for_read(str(attachment.id))


async def delete_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    *,
    actor_agent_id: int | HumanActor,
) -> None:
    attachment: DocumentAttachmentPublic | None = None
    for _attempt in range(3):
        item, _content, access, _content_type, _media_type = await service.get_item(
            document_id,
            agent_id=actor_agent_id,
        )
        _assert_document(item)
        if not access.can_write:
            raise service.MemoryPermissionError("Document edit access denied.")
        attachments = attachments_from_item(item)
        attachment = next(
            (value for value in attachments if value.id == attachment_id),
            None,
        )
        if attachment is None:
            raise service.MemoryNotFoundError("Document attachment not found.")
        try:
            await service.update_item(
                item.id,
                MemoryItemUpdate(
                    expected_revision=item.revision,
                    expected_lock_version=item.lock_version,
                    metadata={
                        **_metadata_with_attachments(item, [value for value in attachments if value.id != attachment_id]),
                        "retained_document_attachments": [
                            *item.metadata_.get("retained_document_attachments", []),
                            attachment.model_dump(mode="json"),
                        ],
                    },
                ),
                actor_agent_id=actor_agent_id,
                preserve_document_attachments=False,
            )
            break
        except service.MemoryConflictError:
            continue
    else:
        raise service.MemoryConflictError(
            "The document changed while the attachment was being removed."
        )
    # Immutable revisions and drafts may retain this reference. Bytes remain owned
    # by the document and are purged only when the document itself is forgotten.



__all__ = [
    "ATTACHMENT_METADATA_KEY",
    "add_document_attachment",
    "add_document_attachment_bytes",
    "attachments_from_item",
    "delete_document_attachment",
    "list_document_attachments",
    "read_document_attachment",
]
