"""Directory discovery and versioned analysis through one catalogue port."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
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


def analysis_identity(source: dict[str, Any], kind: str) -> str:
    if source.get("file_sha256"):
        return f"{source['agent_id']}:{source['file_sha256']}:{kind}:v2"
    return f"{source['identity']}:{source['version']}:{kind}:v1"


class FileCatalogueMechanism:
    key = "memory.file_catalogue"

    async def is_available(self) -> bool:
        return file_catalogue_port() is not None

    async def count_pending(self) -> int:
        port = file_catalogue_port()
        if port is None or not await self.is_available():
            return 0
        async with get_db_session():
            receipts = await get_db().scalars(select(DreamReceipt).where(
                DreamReceipt.mechanism_key == self.key,
                DreamReceipt.subject_kind == "file_directory",
                DreamReceipt.status.in_(("running", "retry", "error")),
            ))
            claimed = [{**discovery_subject(receipt.prepared_payload or {}),
                "status": receipt.status} for receipt in receipts]
            count = await port.discovery_pending(claimed)
            for source in await port.fingerprints():
                if await get_db().scalar(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "file_fingerprint", DreamReceipt.subject_id == f"{source['identity']}:{source['version']}:sha256")) is None:
                    count += 1
            if not enrichment_enabled():
                return count
            candidates = await port.candidates()
            for source in candidates:
                if not source.get("file_sha256"):
                    continue
                for kind in media_kinds(source["descriptor"]):
                    if not getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"):
                        continue
                    subject = analysis_identity(source, kind)
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
            receipts = await get_db().scalars(select(DreamReceipt).where(
                DreamReceipt.mechanism_key == self.key,
                DreamReceipt.subject_kind == "file_directory",
                DreamReceipt.status.in_(("running", "retry", "error")),
            ))
            unavailable = [{**discovery_subject(receipt.prepared_payload or {}),
                "status": receipt.status} for receipt in receipts]
            for subject in await port.discovery_subjects(unavailable):
                existing = await get_db().scalar(select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "file_directory",
                    DreamReceipt.subject_id == subject["identity"],
                ))
                if existing is not None:
                    continue
                claim = create_running_receipt(mechanism_key=self.key,
                    subject_kind="file_directory", subject_id=subject["identity"],
                    prepared_payload={"discovery": subject, "uri": subject["uri"]})
                await get_db().flush()
                return claim
            for source in await port.fingerprints():
                subject = f"{source['identity']}:{source['version']}:sha256"
                if await get_db().scalar(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "file_fingerprint", DreamReceipt.subject_id == subject)) is None:
                    claim = create_running_receipt(mechanism_key=self.key, subject_kind="file_fingerprint",
                        subject_id=subject, prepared_payload=source)
                    await port.claimed(str(source["identity"]))
                    await get_db().flush()
                    return claim
            if not enrichment_enabled():
                return None
            for source in await port.candidates():
                if not source.get("file_sha256"):
                    continue
                # Unsupported/disabled versions must not monopolize the bounded
                # candidate window and starve later analysable files.
                await port.claimed(str(source["identity"]))
                for kind in media_kinds(source["descriptor"]):
                    if not getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind.upper()}_ENABLED"):
                        continue
                    subject = analysis_identity(source, kind)
                    if await get_db().scalar(select(DreamReceipt.id).where(DreamReceipt.mechanism_key == self.key, DreamReceipt.subject_id == subject)) is not None:
                        continue
                    claim = create_running_receipt(mechanism_key=self.key, subject_kind="file", subject_id=subject,
                        prepared_payload={**source, "_dream_stage": "evidence", "kind": kind})
                    await get_db().flush()
                    return claim
        return None

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        if claim.subject_kind == "file_directory":
            return DreamPrepared(payload=claim.prepared_payload or {})
        port = file_catalogue_port()
        source = claim.prepared_payload or {}
        if claim.subject_kind == "file_fingerprint":
            if port is None:
                return DreamPrepared(payload={"skipped": "disabled"})
            async with get_db_session():
                digest = await port.fingerprint(source)
            return DreamPrepared(payload={**source, "sha256": digest})
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
        if claim.subject_kind == "file_fingerprint":
            if port is None or not payload.get("sha256"):
                return 0
            async with get_db_session():
                return int(await port.identify(payload["identity"], payload["version"], payload["sha256"]))
        if claim.subject_kind == "file_directory":
            if port is None:
                return 0
            async with get_db_session():
                # Keep ownership locked until the directory and its child queue
                # have committed. A late worker cannot apply an expired claim.
                receipt = await get_db().scalar(select(DreamReceipt).where(
                    DreamReceipt.id == claim.receipt_id,
                    DreamReceipt.status == "running",
                    DreamReceipt.lease_token == claim.lease_token,
                ).with_for_update())
                if receipt is None:
                    raise RuntimeError("Dream receipt lease was lost.")
                previous = (receipt.prepared_payload or {}).get("discovery_result")
                if isinstance(previous, int):
                    return previous
                count = await port.discover(discovery_subject(payload),
                    attempt=claim.attempts, max_attempts=runtime_settings.DREAM_MAX_ATTEMPTS)
                receipt.prepared_payload = {**payload, "discovery_result": count}
                return count
        kind = payload.get("kind", (claim.prepared_payload or {}).get("kind"))
        if port is None or not payload.get("description") or kind not in {"text", "document", "image", "video"} or not getattr(runtime_settings, f"DREAM_ATTACHMENT_{str(kind).upper()}_ENABLED"):
            return 0
        async with get_db_session():
            return int(await port.apply(str(payload["identity"]), str(payload["version"]), str(payload["description"])))


def enrichment_enabled() -> bool:
    return any(bool(getattr(runtime_settings, f"DREAM_ATTACHMENT_{kind}_ENABLED"))
        for kind in ("TEXT", "DOCUMENT", "IMAGE", "VIDEO"))


def discovery_subject(payload: dict[str, Any]) -> dict[str, str]:
    value = payload.get("discovery")
    if not isinstance(value, dict):
        raise ValueError("Missing directory discovery checkpoint")
    result: dict[str, str] = {}
    for key in ("identity", "run_id", "uri", "cursor", "scanned"):
        field = cast(dict[str, object], value).get(key)
        if not isinstance(field, str):
            raise ValueError("Invalid directory discovery checkpoint")
        result[key] = field
    return result


file_catalogue_mechanism = FileCatalogueMechanism()
