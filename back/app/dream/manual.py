"""Bounded foreground Dream actions, independent of idle scheduling settings."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.agent import AgentManagementScope
from app.llm import llm_correlation_scope, llm_execution_scope
from app.llm.facade import llm_call_accounting
from app.memory import (
    MemoryItem,
    MemoryConflictError,
    detect_memory_findings,
    generate_document_attachment_thumbnail,
    read_document_thumbnail,
    DocumentThumbnailRender,
)
from app.memory.facade import (
    attachment_analysis_source,
    attachment_analysis_path,
    fill_attachment_description,
    dream_action_item,
    dream_structure_identity,
    reconcile_structure_subject,
)
from core.database import get_db
from core.document import OFFICE_EXTENSIONS
from core.preview import MODEL_EXTENSIONS, MODEL_TYPES
from core.user import HumanActor

from .attachment_processing import analyze_attachment
from .interface import file_catalogue_port
from .mechanisms.file_catalogue import FileMediaSource, media_kinds
from .models import DreamReceipt
from .schemas import MemoryDreamAction, MemoryDreamActions, MemoryDreamActionResult
from .service import claim_execution_timeout, receipt_correlation_ref


def _supports_thumbnail(descriptor: dict[str, Any]) -> bool:
    media = str(descriptor.get("media_type", "")).split(";", 1)[0].strip().lower()
    suffix = Path(str(descriptor.get("name", ""))).suffix.lower()
    return (
        media.startswith(("image/", "video/", "text/"))
        or media
        in {"application/pdf", "application/json", "application/xml", "application/javascript"}
        | MODEL_TYPES
        or suffix in OFFICE_EXTENSIONS | MODEL_EXTENSIONS | {".pdf", ".url", ".svg"}
    )


async def available_actions(
    item_id: UUID, agent_id: int, scope: AgentManagementScope
) -> MemoryDreamActions:
    item = await dream_action_item(item_id, agent_id, scope)
    actions: list[MemoryDreamAction] = []
    descriptor: dict[str, Any] = {}
    if item.node_kind in {"file", "attachment"}:
        if item.node_kind == "attachment":
            source = await attachment_analysis_source(item_id, allow_existing=True)
            descriptor = {"name": source.name, "media_type": source.media_type} if source else {}
        else:
            port = file_catalogue_port()
            file_source = await port.source_for_item(item_id, agent_id) if port else None
            descriptor = file_source["descriptor"] if file_source else {}
        kinds = media_kinds(descriptor)
        if kinds:
            actions.append("describe")
        if "document" in kinds:
            actions.append("read_document")
        if _supports_thumbnail(descriptor):
            actions.append("thumbnail")
    elif item.node_kind == "memory" and not item.source_managed:
        actions.append("findings")
    elif item.node_kind in {"document", "folder"}:
        if item.node_kind == "document" and item.document_type == "html":
            actions.append("thumbnail")
        actions.append("structure")
    return MemoryDreamActions(actions=actions)


async def _apply(
    item: MemoryItem, action: MemoryDreamAction, agent_id: int, scope: AgentManagementScope,
    snapshot: DocumentThumbnailRender | None = None,
) -> int:
    item_id = item.id
    if action == "findings":
        return len(await detect_memory_findings(item_id, manual=True))
    if action == "structure":
        return await reconcile_structure_subject(
            item.node_kind, await dream_structure_identity(item)
        )
    if item.node_kind == "document" and action == "thumbnail":
        if snapshot is None:
            raise ValueError("A saved document snapshot is required")
        actor = item.owner_agent_id if item.owner_agent_id is not None else HumanActor(scope.user_id)
        result = await read_document_thumbnail(item_id, snapshot, actor_agent_id=actor, force=True)
        if result is None:
            raise RuntimeError("Document thumbnail rendering failed")
        return 1
    if item.node_kind == "attachment":
        source = await attachment_analysis_source(item_id, allow_existing=True)
        if source is None:
            raise MemoryConflictError("Attachment source changed")
        if action == "thumbnail":
            actor = (
                source.owner_agent_id
                if source.owner_agent_id is not None
                else HumanActor(scope.user_id)
            )
            result = await generate_document_attachment_thumbnail(
                source.document_id, source.attachment_id, actor_agent_id=actor, force=True
            )
            if result is None:
                raise RuntimeError("Attachment thumbnail rendering failed")
            return 1
        kinds = media_kinds({"name": source.name, "media_type": source.media_type})
        kind = "document" if action == "read_document" else kinds[0]
        path = await attachment_analysis_path(source, max_bytes=32 * 1024**2, allow_existing=True)
        await get_db().commit()
        description = await analyze_attachment(kind, path, source)
        if not description or not description.strip():
            raise ValueError("Source produced no description")
        await dream_action_item(item_id, agent_id, scope)
        return int(await fill_attachment_description(source, description, replace_existing=True))
    port = file_catalogue_port()
    source = await port.source_for_item(item_id, agent_id) if port else None
    if port is None or source is None:
        raise MemoryConflictError("File source is no longer available")
    if action == "thumbnail":
        generated = await port.thumbnail_generate(
            {
                "item_id": str(item_id),
                "entry_id": source["identity"],
                "agent_id": agent_id,
                "uri": source["uri"],
                "version": source["version"],
                "binding_stamp": source["binding_stamp"],
                "sha256": source["file_sha256"],
            }, force=True,
        )
        if not generated:
            raise RuntimeError("File thumbnail rendering failed")
        return 1
    revision = item.revision
    source["item_id"] = str(item_id)
    source["memory_revision"] = revision
    kinds = media_kinds(source["descriptor"])
    kind = "document" if action == "read_document" else kinds[0]
    with TemporaryDirectory(prefix="dream-manual-") as temporary:
        path = Path(temporary) / "source"
        info = await port.materialize(source, path)
        if info is None:
            raise MemoryConflictError("File changed or exceeds the analysis limit")
        if source.get("file_sha256"):

            def digest() -> str:
                with path.open("rb") as stream:
                    return hashlib.file_digest(stream, "sha256").hexdigest()

            if await asyncio.to_thread(digest) != source["file_sha256"]:
                raise MemoryConflictError("File bytes changed during analysis")
        await get_db().commit()
        description = await analyze_attachment(
            kind, path, FileMediaSource(str(info["name"]), str(info["media_type"]), agent_id)
        )
        if not description or not description.strip():
            raise ValueError("Source produced no description")
    current = await dream_action_item(item_id, agent_id, scope)
    if current.revision != revision:
        raise MemoryConflictError("Memory was edited during analysis")
    return int(await port.apply_manual(source, description))


async def run_action(
    item_id: UUID, agent_id: int, action: MemoryDreamAction, scope: AgentManagementScope,
    *, snapshot: DocumentThumbnailRender | None = None,
) -> MemoryDreamActionResult:
    db = get_db()
    item = await dream_action_item(item_id, agent_id, scope)
    if action not in (await available_actions(item_id, agent_id, scope)).actions:
        raise ValueError("Action is unavailable for this node")
    if item.node_kind == "document" and action == "thumbnail" and snapshot is None:
        raise ValueError("A saved document snapshot is required")
    # Serialize duplicate foreground requests across API workers, without holding
    # a connection or source lock while inference runs.
    await db.execute(select(func.pg_advisory_xact_lock(item_id.int % (2**63 - 1))))
    now = datetime.now(timezone.utc)
    active = await db.scalar(
        select(DreamReceipt.id).where(
            DreamReceipt.mechanism_key.startswith("manual.memory."),
            DreamReceipt.subject_id.startswith(f"{item_id}:"),
            DreamReceipt.status == "running",
            DreamReceipt.lease_expires_at > now,
        )
    )
    if active is not None:
        raise MemoryConflictError("A Dream action is already running on this node")
    receipt = DreamReceipt(
        id=uuid4(),
        mechanism_key=f"manual.memory.{action}",
        subject_kind="memory_item",
        subject_id=f"{item_id}:{uuid4()}",
        attempts=1,
        lease_expires_at=now + timedelta(seconds=claim_execution_timeout() + 30),
        prepared_payload={
            "item_id": str(item_id),
            "agent_id": agent_id,
            "user_id": scope.user_id,
            "action": action,
        },
    )
    db.add(receipt)
    await db.commit()
    receipt_id = receipt.id
    result_count = 0
    with llm_call_accounting() as accounting:
        try:
            async with asyncio.timeout(claim_execution_timeout()):
                with (
                    llm_correlation_scope(receipt_correlation_ref(receipt_id)),
                    llm_execution_scope(source_kind="memory_item", source_id=str(item_id)),
                ):
                    result_count = await _apply(item, action, agent_id, scope, snapshot)
            receipt.status = "success"
            receipt.result_count = result_count
            receipt.cost = accounting.cost
            receipt.lease_expires_at = None
            await db.commit()
        except BaseException as exc:
            await db.rollback()
            record = await db.get(DreamReceipt, receipt_id, populate_existing=True)
            if record is not None:
                record.status = "error"
                record.last_error = type(exc).__name__
                record.cost = accounting.cost
                record.lease_expires_at = None
                await db.commit()
            raise
    return MemoryDreamActionResult(receipt_id=receipt_id, result_count=result_count)
