"""Run-owned business data, file links and atomic execution receipts."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, func

from core.database import get_db
from core.params import runtime_settings
from core.storage import DiskFileDriver, StoredFile, ensure_disk_identity, file_key, fingerprint, register_file, retire_file_reference
from core.util import complete_io

from .models import ProcessRun, ProcessRunFile
from .process_service import TERMINAL_STATUSES


class RunDataConflictError(ValueError):
    """A concurrent or late write cannot replace the current run data."""


async def lock_run(run_id: UUID) -> ProcessRun:
    run = await get_db().scalar(select(ProcessRun).where(ProcessRun.id == run_id)
        .with_for_update().execution_options(populate_existing=True))
    if run is None or run.engine_code != "galaris":
        raise LookupError("Internal process run not found")
    return run


def require_active(run: ProcessRun) -> None:
    native = run.engine_metadata.get("native", {})
    if run.status in TERMINAL_STATUSES or native.get("cancel_requested") or native.get("status") in TERMINAL_STATUSES:
        raise RunDataConflictError("A stopped run cannot change its data")


def validate_run_data(data: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > 2_000_000:
        raise ValueError("Run data exceeds its JSON limit")
    pending: list[tuple[Any, int]] = [(data, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > 32 or count > 20_000:
            raise ValueError("Run data exceeds its depth or item limit")
        if isinstance(value, dict):
            pending.extend((entry, depth + 1) for entry in cast(dict[str, Any], value).values())
        elif isinstance(value, list):
            pending.extend((entry, depth + 1) for entry in cast(list[Any], value))
    return deepcopy(data)


async def run_files(run_id: UUID) -> list[dict[str, Any]]:
    rows = (await get_db().execute(select(ProcessRunFile, StoredFile).outerjoin(
        StoredFile, StoredFile.id == ProcessRunFile.file_id).where(ProcessRunFile.run_id == run_id)
        .order_by(ProcessRunFile.position, ProcessRunFile.created_at, ProcessRunFile.id))).all()
    return [{"uri": row.uri,
        **({"description": row.description} if row.description is not None else {}),
        **({"filename": stored.name} if stored is not None else {"filename": row.name} if row.name is not None else {}),
        **({"origin_uri": row.origin_uri} if row.origin_uri is not None else {}),
        **({"content_type": stored.media_type, "size": stored.size_bytes, "sha256": stored.sha256}
            if stored is not None else {})} for row, stored in rows]


async def read_run_workspace(run_id: UUID) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Internal engine read; public callers authorize through the process first."""
    run = await get_db().get(ProcessRun, run_id)
    if run is None:
        raise LookupError("Process run not found")
    return deepcopy(run.data), await run_files(run_id)


async def _replace_files(run: ProcessRun, files: list[dict[str, Any]]) -> None:
    from app.file_share import parse_resource_uri
    if len(files) > 500:
        raise ValueError("A run accepts at most 500 file references")
    entries: dict[str, dict[str, Any]] = {}
    file_ids: dict[str, UUID | None] = {}
    for entry in files:
        uri = parse_resource_uri(entry["uri"])
        if uri.is_collection:
            raise ValueError("A run file requires an exact canonical URI")
        entries.setdefault(str(uri), entry)
        identity = UUID(str(uri).removeprefix("file://")) if uri.scheme == "file" else None
        if identity is not None and await get_db().get(StoredFile, identity) is None:
            raise FileNotFoundError("Managed run file not found")
        file_ids[str(uri)] = identity
    rows = list(await get_db().scalars(select(ProcessRunFile).where(ProcessRunFile.run_id == run.id)))
    known = {row.uri: row for row in rows}
    for row in rows:
        if row.uri not in entries:
            row.soft_delete()
            if row.uri.startswith(f"galaris://processes/runs/{run.id}/attachments/"):
                await retire_file_reference(row.uri)
    for position, (uri, entry) in enumerate(entries.items()):
        if uri in known:
            known[uri].position = position
            known[uri].description = entry.get("description")
            continue
        get_db().add(ProcessRunFile(run_id=run.id, uri=uri, file_id=file_ids[uri],
            name=entry.get("filename"), description=entry.get("description"), origin_uri=entry.get("origin_uri"), position=position))
    await get_db().flush()


async def initialize_run_data(run_id: UUID, files: list[dict[str, Any]]) -> None:
    run = await lock_run(run_id)
    require_active(run)
    if not run.execution_state.get("data_initialized"):
        data = validate_run_data(run.input)
        await _replace_files(run, files)
        run.data = data
        run.execution_state = {**run.execution_state, "data_initialized": True}
    await get_db().commit()


async def integrate_workflow_values(run_id: UUID, *, command: str,
    baseline: dict[str, Any], changes: dict[str, Any], files: list[dict[str, Any]],
    remove: list[str] | None = None, files_mode: Literal["append", "replace"] = "append",
    baseline_files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    run = await lock_run(run_id)
    deletions = sorted(set(remove or []))
    if set(deletions).intersection(changes) or files_mode not in {"append", "replace"}:
        raise ValueError("Invalid workflow integration")
    digest = hashlib.sha256(json.dumps({"changes": changes, "files": files, "remove": deletions,
        "files_mode": files_mode}, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":")).encode()).hexdigest()
    receipts: dict[str, str] = dict(run.execution_state.get("integrations", {}))
    if command in receipts:
        if receipts[command] != digest:
            raise RunDataConflictError("This integration command already has a different result")
        return {"id": str(run.id), "data": deepcopy(run.data), "revision": run.data_revision}
    require_active(run)
    data = run.data
    for name, value in changes.items():
        if ((name in data) != (name in baseline) or data.get(name) != baseline.get(name)) and (name not in data or data[name] != value):
            raise RunDataConflictError(f"Concurrent workflow writes conflict on variable {name}")
    for name in deletions:
        if name in data and (name not in baseline or data[name] != baseline[name]):
            raise RunDataConflictError(f"Concurrent workflow writes conflict on variable {name}")
    merged_files = await run_files(run.id)
    if files_mode == "replace":
        if merged_files != baseline_files and merged_files != files:
            raise RunDataConflictError("Concurrent workflow changes conflict on the file manifest")
        merged_files = []
    known = {entry["uri"] for entry in merged_files}
    for entry in files:
        if entry["uri"] not in known:
            merged_files.append(deepcopy(entry))
            known.add(entry["uri"])
    updated = {**data, **deepcopy(changes)}
    for name in deletions:
        updated.pop(name, None)
    from .values import validate_values
    updated = validate_values(updated, path="process.data")
    await _replace_files(run, merged_files)
    run.data = updated
    run.data_revision += 1
    receipts[command] = digest
    run.execution_state = {**run.execution_state, "integrations": receipts,
        "integration_results": {**run.execution_state.get("integration_results", {}),
            command: {"revision": run.data_revision}}}
    await get_db().commit()
    return {"id": str(run.id), "data": deepcopy(run.data), "revision": run.data_revision}


async def workflow_attachment_receipt(run_id: UUID, key: str) -> dict[str, Any] | None:
    state = await get_db().scalar(select(ProcessRun.execution_state).where(ProcessRun.id == run_id))
    if state is None:
        raise LookupError("Process run not found")
    receipt = state.get("attachments", {}).get(key)
    return deepcopy(receipt) if receipt is not None else None


async def stage_run_file(run: ProcessRun, path: Path, *, name: str, media_type: str,
                         file_id: UUID | None = None, source_uri: str | None = None) -> dict[str, Any]:
    from app.document import validate_attachment_content
    count = await get_db().scalar(select(func.count()).select_from(ProcessRunFile).where(ProcessRunFile.run_id == run.id)) or 0
    if count >= 500:
        raise ValueError("A run accepts at most 500 file references")
    last_position = await get_db().scalar(select(func.max(ProcessRunFile.position)).where(ProcessRunFile.run_id == run.id))
    position = 0 if last_position is None else last_position + 1
    size, digest = await complete_io(fingerprint, path)
    if size > runtime_settings.MEMORY_RESOURCE_MAX_BYTES:
        raise ValueError("Attachment exceeds its file limit")
    def validate_source() -> str:
        with path.open("rb") as stream:
            content = stream.read(runtime_settings.MEMORY_RESOURCE_MAX_BYTES + 1 if media_type.startswith("image/") else 1024 * 1024)
        return validate_attachment_content(media_type, name, content)
    media_type = await complete_io(validate_source)
    name = Path(name.replace("\\", "/")).name[:512] or "file"
    identity = file_id or uuid4()
    uri = f"galaris://processes/runs/{run.id}/attachments/{identity}"
    await ensure_disk_identity(get_db())
    await complete_io(DiskFileDriver().publish, path, file_key(identity), size=size, sha256=digest)
    await register_file(identity, name=name, media_type=media_type, alias=uri)
    get_db().add(ProcessRunFile(run_id=run.id, file_id=identity, uri=uri, name=name, origin_uri=source_uri, position=position))
    await get_db().flush()
    return {"origin_uri": source_uri, "filename": name, "sha256": digest,
        "uri": uri, "content_type": media_type, "size": size}


async def create_workflow_attachment(run_id: UUID, *, key: str, source_uri: str,
    path: Path, name: str, media_type: str) -> dict[str, Any]:
    run = await lock_run(run_id)
    receipts: dict[str, Any] = deepcopy(run.execution_state.get("attachments", {}))
    if key in receipts:
        return receipts[key]
    require_active(run)
    receipt = await stage_run_file(run, path, name=name, media_type=media_type,
        file_id=uuid5(run.id, f"input:{key}"), source_uri=source_uri)
    receipts[key] = receipt
    run.execution_state = {**run.execution_state, "attachments": receipts}
    await get_db().commit()
    return receipt
