"""Precompute persisted file previews without inference or changing source data."""

from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.memory import DocumentAttachment, MemoryItem, generate_document_attachment_thumbnail
from core.database import get_db, get_db_session
from core.document import OFFICE_EXTENSIONS
from core.preview import MODEL_EXTENSIONS, MODEL_TYPES
from core.user import HumanActor

from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..interface import file_catalogue_port
from ..service import claim_retry, create_running_receipt


class FileThumbnailsMechanism:
    key = "memory.file_thumbnails"

    async def is_available(self) -> bool:
        return True

    def _handled(self) -> Select[tuple[str]]:
        return select(DreamReceipt.subject_id).where(DreamReceipt.mechanism_key == self.key)

    def _attachments(self) -> Select[tuple[DocumentAttachment, MemoryItem]]:
        document = aliased(MemoryItem)
        identity = func.concat("attachment:", DocumentAttachment.id)
        media = func.lower(MemoryItem.metadata_["resource_media_type"].as_string())
        name = func.lower(MemoryItem.title)
        return select(DocumentAttachment, document).join(
            MemoryItem, MemoryItem.id == DocumentAttachment.memory_item_id,
        ).join(document, document.id == DocumentAttachment.document_id).where(
            DocumentAttachment.active.is_(True), document.deleted_at.is_(None), MemoryItem.deleted_at.is_(None),
            or_(document.owner_agent_id.is_not(None), document.owner_user_id.is_not(None)),
            or_(media.startswith("image/"), media.startswith("video/"), media.startswith("text/"),
                media.in_({"application/pdf", "application/json", "application/xml", "application/javascript"} | MODEL_TYPES),
                *[name.endswith(suffix) for suffix in OFFICE_EXTENSIONS | MODEL_EXTENSIONS | {".pdf", ".url", ".svg"}]),
            ~exists(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key,
                                                 DreamReceipt.subject_id == identity)),
        )

    async def count_pending(self) -> int:
        async with get_db_session():
            port = file_catalogue_port()
            count = await port.thumbnail_pending(self._handled()) if port is not None else 0
            attachments = await get_db().scalar(select(func.count()).select_from(self._attachments().subquery()))
            return int(count or 0) + int(attachments or 0)

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            # Serialize selection and receipt insertion across workers. Render outside this transaction.
            await get_db().execute(select(func.pg_advisory_xact_lock(731846292)))
            row = (await get_db().execute(self._attachments().order_by(DocumentAttachment.id).limit(1))).first()
            if row is not None:
                attachment, document = row
                source: dict[str, Any] = {
                    "document_id": str(document.id), "attachment_id": str(attachment.id),
                    "agent_id": document.owner_agent_id, "user_id": document.owner_user_id,
                    "uri": f"document://{document.id}/attachments/{attachment.id}",
                }
                identity = f"attachment:{attachment.id}"
                kind = "attachment_thumbnail"
            else:
                port = file_catalogue_port()
                candidate = await port.thumbnail_source(self._handled()) if port is not None else None
                if candidate is None:
                    return None
                source = candidate
                identity = str(source["identity"])
                kind = "file_thumbnail"
            claim = create_running_receipt(mechanism_key=self.key, subject_kind=kind, subject_id=identity,
                                           prepared_payload=source)
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        return DreamPrepared(payload=claim.prepared_payload or {})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        async with get_db_session():
            if claim.subject_kind == "attachment_thumbnail":
                attachment = await get_db().get(DocumentAttachment, UUID(payload["attachment_id"]))
                document = await get_db().get(MemoryItem, UUID(payload["document_id"]))
                if attachment is None or not attachment.active or document is None or document.deleted_at is not None:
                    return 0
                # Owner changes invalidate the checkpoint rather than lending access to the old owner.
                if (document.owner_agent_id, document.owner_user_id) != (payload["agent_id"], payload["user_id"]):
                    return 0
                actor = int(payload["agent_id"]) if payload["agent_id"] is not None else HumanActor(int(payload["user_id"]))
                result = await generate_document_attachment_thumbnail(document.id, attachment.id, actor_agent_id=actor)
                return int(result is not None)
            port = file_catalogue_port()
            return int(await port.thumbnail_generate(payload)) if port is not None else 0


file_thumbnails_mechanism = FileThumbnailsMechanism()
