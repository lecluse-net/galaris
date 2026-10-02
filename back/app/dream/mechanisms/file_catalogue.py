"""Versioned external file analysis through a composition-owned catalogue port."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from sqlalchemy import select, func

from core.database import get_db, get_db_session
from core.params import runtime_settings
from ..attachment_processing import AttachmentKind, analyze_attachment
from ..attachment_extract import OFFICE_SUFFIXES, TEXT_TYPES
from ..contracts import DreamClaim, DreamPrepared
from ..interface import file_catalogue_port
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt


@dataclass(frozen=True)
class FileMediaSource:
    name: str
    media_type: str
    owner_agent_id: int


def media_kind(descriptor: dict[str, Any]) -> AttachmentKind | None:
    mime = str(descriptor.get("media_type", ""))
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/") or mime.startswith("audio/"):
        return "video"
    if mime.startswith("text/") or mime in TEXT_TYPES or mime == "application/pdf" or Path(str(descriptor.get("name", ""))).suffix.lower() in OFFICE_SUFFIXES | {".pdf"}:
        return "text"
    return None


def media_kinds(descriptor: dict[str, Any]) -> tuple[AttachmentKind, ...]:
    kind = media_kind(descriptor)
    if kind is None:
        return ()
    suffix = Path(str(descriptor.get("name", ""))).suffix.lower()
    if kind == "text" and (descriptor.get("media_type") == "application/pdf" or suffix in OFFICE_SUFFIXES | {".pdf"}):
        return ("text", "document")
    return (kind,)


class FileCatalogueMechanism:
    key = "memory.file_catalogue"

    async def is_available(self) -> bool:
        return file_catalogue_port() is not None and any(bool(getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind}_ENABLED")) for kind in ("TEXT", "DOCUMENT", "IMAGE", "VIDEO"))

    async def count_pending(self) -> int:
        port = file_catalogue_port()
        if port is None or not await self.is_available():
            return 0
        async with get_db_session():
            candidates = await port.candidates()
            count = 0
            for source in candidates:
                for kind in media_kinds(source["descriptor"]):
                    if not getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"):
                        continue
                    subject = f"{source['identity']}:{source['version']}:{kind}:v1"
                    if await get_db().scalar(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key, DreamReceipt.subject_id == subject)) is None:
                        count += 1
                        break
            return count

    async def claim_one(self) -> DreamClaim | None:
        port = file_catalogue_port()
        if port is None or not await self.is_available():
            return None
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            await get_db().execute(select(func.pg_advisory_xact_lock(731846291)))
            for source in await port.candidates():
                # Unsupported/disabled versions must not monopolize the bounded
                # candidate window and starve later analysable files.
                await port.claimed(str(source["identity"]))
                for kind in media_kinds(source["descriptor"]):
                    if not getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"):
                        continue
                    subject = f"{source['identity']}:{source['version']}:{kind}:v1"
                    if await get_db().scalar(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key, DreamReceipt.subject_id == subject)) is not None:
                        continue
                    claim = create_running_receipt(mechanism_key=self.key, subject_kind="file", subject_id=subject,
                        prepared_payload={**source, "_dream_stage": "evidence", "kind": kind})
                    await get_db().flush()
                    return claim
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        port = file_catalogue_port()
        source = claim.prepared_payload or {}
        kind: AttachmentKind = source["kind"]
        if port is None or not getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"):
            return DreamPrepared(payload={"skipped": "disabled"})
        with TemporaryDirectory(prefix="dream-file-") as temporary:
            path = Path(temporary) / "source"
            async with get_db_session():
                info = await port.materialize(source, path)
            if info is None:
                return DreamPrepared(payload={"skipped": "source_changed_or_too_large"})
            description = await analyze_attachment(kind, path, FileMediaSource(str(info["name"]), str(info["media_type"]), int(info["agent_id"])))
        return DreamPrepared(payload={"identity": source["identity"], "version": source["version"], "description": description, "kind": kind})

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        port = file_catalogue_port()
        kind = payload.get("kind", (claim.prepared_payload or {}).get("kind"))
        if port is None or not payload.get("description") or kind not in {"text", "document", "image", "video"} or not getattr(runtime_settings, f"DREAM_ATTACHMENT_{str(kind).upper()}_ENABLED"):
            return 0
        async with get_db_session():
            return int(await port.apply(str(payload["identity"]), str(payload["version"]), str(payload["description"])))


file_catalogue_mechanism = FileCatalogueMechanism()
