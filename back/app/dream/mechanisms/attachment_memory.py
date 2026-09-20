"""Fill one empty attachment companion per Dream turn, independently by media kind."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select

from app.memory import MemoryItem
from app.llm import LLMCall
from app.memory.facade import (
    AttachmentAnalysisSource, attachment_analysis_path, attachment_analysis_source,
    empty_attachment_items, fill_attachment_description,
)
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..attachment_extract import OFFICE_SUFFIXES, TEXT_TYPES
from ..attachment_processing import AttachmentKind, analyze_attachment
from ..contracts import DreamClaim, DreamPrepared
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt, receipt_correlation_ref


def _snapshot(source: AttachmentAnalysisSource) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, UUID) else value for key, value in asdict(source).items()}


def _source(payload: dict[str, Any]) -> AttachmentAnalysisSource:
    return AttachmentAnalysisSource(
        item_id=UUID(payload["item_id"]), attachment_id=UUID(payload["attachment_id"]),
        document_id=UUID(payload["document_id"]), revision=int(payload["revision"]),
        owner_agent_id=payload["owner_agent_id"], owner_user_id=payload["owner_user_id"],
        name=str(payload["name"]), media_type=str(payload["media_type"]), size_bytes=int(payload["size_bytes"]),
    )


class AttachmentMemoryMechanism:
    def __init__(self, kind: AttachmentKind) -> None:
        self.kind: AttachmentKind = kind
        self.key = f"memory.attachment_{kind}"

    async def is_available(self) -> bool:
        return bool(getattr(runtime_settings, f"DREAM_ATTACHMENT_{self.kind.upper()}_ENABLED"))

    def _pending(self) -> Select[tuple[MemoryItem]]:
        media = func.lower(MemoryItem.metadata_["resource_media_type"].as_string())
        plain = or_(media.startswith("text/"), media.in_(TEXT_TYPES))
        convertible = or_(media == "application/pdf", *[
            func.lower(MemoryItem.title).endswith(suffix) for suffix in OFFICE_SUFFIXES | {".pdf"}
        ])
        match self.kind:
            case "image":
                media_filter = media.startswith("image/")
            case "video":
                media_filter = media.startswith("video/")
            case "text":
                media_filter = or_(plain, convertible)
            case "document":
                media_filter = ~or_(plain, media.startswith("image/"), media.startswith("video/"), media.startswith("audio/"))
        subject = func.concat(MemoryItem.id, ":", MemoryItem.revision)
        return empty_attachment_items().where(media_filter, ~exists(select(DreamReceipt.id).where(
            DreamReceipt.mechanism_key == self.key, DreamReceipt.subject_kind == "attachment",
            DreamReceipt.subject_id == subject,
        )))

    async def count_pending(self) -> int:
        if not await self.is_available():
            return 0
        async with get_db_session():
            return int(await get_db().scalar(select(func.count()).select_from(self._pending().subquery())) or 0)

    async def claim_one(self) -> DreamClaim | None:
        if not await self.is_available():
            return None
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            item = await get_db().scalar(self._pending().order_by(MemoryItem.id).limit(1)
                                         .with_for_update(of=MemoryItem, skip_locked=True))
            if item is None:
                return None
            source = await attachment_analysis_source(item.id)
            if source is None:
                return None
            claim = create_running_receipt(
                mechanism_key=self.key, subject_kind="attachment",
                subject_id=f"{item.id}:{item.revision}",
                prepared_payload={"_dream_stage": "evidence", "source": _snapshot(source)},
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        if not await self.is_available():
            raise asyncio.CancelledError("Attachment analysis was disabled")
        source = _source((claim.prepared_payload or {})["source"])
        async with get_db_session():
            if await attachment_analysis_source(source.item_id) != source:
                return DreamPrepared(payload={"skipped": "source_changed"})
            path = await attachment_analysis_path(source, max_bytes=(
                1_000_000_000 if self.kind == "video" else 32 * 1024 * 1024
            ))
        description = await analyze_attachment(self.kind, path, source)
        async with get_db_session():
            cost = float(await get_db().scalar(select(func.sum(LLMCall.cost)).where(
                LLMCall.correlation_ref == receipt_correlation_ref(claim.receipt_id),
            )) or 0.0)
        return DreamPrepared(payload={"source": _snapshot(source), "description": description}, cost=cost)

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        del claim
        if not await self.is_available():
            raise asyncio.CancelledError("Attachment analysis was disabled")
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            return 0
        async with get_db_session():
            return int(await fill_attachment_description(_source(payload["source"]), description))


_KINDS: tuple[AttachmentKind, ...] = (
    "text", "document", "image", "video",
)
attachment_memory_mechanisms = tuple(AttachmentMemoryMechanism(kind) for kind in _KINDS)
