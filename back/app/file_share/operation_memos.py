"""Short search replay and content-bound conversion receipts with live source ACLs."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db
from core.storage import fingerprint
from core.util import complete_io
from .models import FileOperationMemo
from .resource_contracts import ResourceContext, ResourceSearchResult
from .resource_service import resource_info, resource_search


def memo_key(ctx: ResourceContext, operation: str, parameters: object) -> str:
    return hashlib.sha256(json.dumps([ctx.runtime, str(ctx.task_id), operation, parameters],
        ensure_ascii=False, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


async def _read(ctx: ResourceContext, key: str) -> dict[str, Any] | None:
    row = await get_db().scalar(select(FileOperationMemo).where(FileOperationMemo.agent_id == ctx.agent_id,
        FileOperationMemo.key == key, FileOperationMemo.expires_at > datetime.now(timezone.utc)))
    return row.result if row else None


async def _write(ctx: ResourceContext, key: str, result: dict[str, Any], lifetime: timedelta) -> None:
    if len(json.dumps(result, ensure_ascii=False).encode()) > 256_000:
        return
    db = get_db()
    now = datetime.now(timezone.utc)
    await db.execute(insert(FileOperationMemo).values(agent_id=ctx.agent_id, key=key, result=result, expires_at=now + lifetime)
        .on_conflict_do_update(constraint="uq_file_operation_memo", set_={"result": result, "expires_at": now + lifetime}))
    # A hard per-agent cap also bounds long-lived installations with many contexts.
    excess = select(FileOperationMemo.id).where(FileOperationMemo.agent_id == ctx.agent_id).order_by(
        FileOperationMemo.expires_at.desc(), FileOperationMemo.id).offset(200)
    await db.execute(delete(FileOperationMemo).where(FileOperationMemo.agent_id == ctx.agent_id,
        (FileOperationMemo.expires_at <= now) | FileOperationMemo.id.in_(excess)))
    await db.commit()


async def conversion_key(ctx: ResourceContext, source: Path, *, uri: str, name: str, media_type: str,
                         destination: str, operation: str, parameters: object = None) -> str:
    # Always materialize/authorize the source first; a URI alone never identifies content.
    _, digest = await complete_io(fingerprint, source)
    return memo_key(ctx, operation, [uri, digest, name, media_type, destination, parameters])


async def converted_resource(ctx: ResourceContext, key: str) -> dict[str, Any] | None:
    stored = await _read(ctx, key)
    if stored is None:
        return None
    try:
        current = await resource_info(ctx, stored["receipt"]["uri"])
    except (PermissionError, LookupError, ValueError):
        return None
    # A modified or unversioned destination must never masquerade as the derivative.
    if not current.checksum or current.checksum != stored["checksum"]:
        return None
    return {**stored["receipt"], "reused": True}


async def remember_conversion(ctx: ResourceContext, key: str, receipt: dict[str, Any], content: bytes) -> None:
    await _write(ctx, key, {"receipt": receipt, "checksum": hashlib.sha256(content).hexdigest()}, timedelta(days=30))


async def conversion_origins(agent_id: int, checksums: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Batch lookup of trusted conversion receipts; callers already validated the outputs."""
    if not checksums:
        return {}
    rows = await get_db().scalars(select(FileOperationMemo).where(FileOperationMemo.agent_id == agent_id,
        FileOperationMemo.result["receipt"]["uri"].as_string().in_(checksums),
        FileOperationMemo.expires_at > datetime.now(timezone.utc)).order_by(FileOperationMemo.expires_at))
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        receipt = row.result.get("receipt", {})
        uri = receipt.get("uri")
        source = receipt.get("source_uri")
        if uri not in checksums or row.result.get("checksum") != checksums[uri] or not isinstance(source, str):
            continue
        result[uri] = {"method": "pdf_page" if "page" in receipt else "pdf_export",
            "source": {"reference": source}, "operation_key": row.key,
            **({"page": receipt["page"]} if "page" in receipt else {})}
    return result


async def search_with_replay(ctx: ResourceContext, uri: str, query: str, *, mode: Literal["name", "text", "semantic"],
                             recursive: bool, max_results: int | None, cursor: str | None,
                             refresh: bool = False) -> ResourceSearchResult:
    turn = ctx.conversation_turn
    scope = [str(getattr(turn, "round_id", "")), getattr(turn, "source_request", None), getattr(turn, "messages", None)]
    # Only conversation input collection needs this short-lived loop protection.
    enabled = bool(turn is not None and any(item.get("kind") == "process_input_preparation"
        for item in getattr(turn, "pending_interactions", ())))
    key = memo_key(ctx, "search/v1", [scope, uri, query, mode, recursive, max_results, cursor])
    stored = await _read(ctx, key) if enabled and not refresh else None
    if stored is not None:
        try:
            await resource_info(ctx, uri)
            result = ResourceSearchResult.model_validate(stored)
            for hit in result.hits:
                current = await resource_info(ctx, hit.resource.uri)
                before, after = hit.resource, current
                if (before.revision, before.checksum, before.etag, before.modified_at) != (after.revision, after.checksum, after.etag, after.modified_at):
                    raise ValueError("Search source changed")
                if not any((after.revision, after.checksum, after.etag, after.modified_at)):
                    raise ValueError("Unversioned search source")
            return result
        except (PermissionError, LookupError, ValueError):
            pass
    result = await resource_search(ctx, uri, query, mode=mode,
        recursive=recursive, max_results=max_results, cursor=cursor)
    if enabled and not result.degraded:
        await _write(ctx, key, result.model_dump(mode="json"), timedelta(seconds=30))
    return result
