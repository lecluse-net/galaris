"""Atomic workflow merges owned by Dataset; Process owns orchestration."""

from copy import deepcopy
from typing import Any, Literal, cast
from uuid import UUID
from sqlalchemy import select
from core.database import get_db
from . import service
from .models import DatasetIntegration


async def integrate_workflow_values(document_id: UUID, *, engine_agent_id: int, command: str,
    baseline: dict[str, Any], changes: dict[str, Any], files: list[dict[str, Any]],
    remove: list[str] | None = None, files_mode: Literal["append", "replace"] = "append",
    baseline_files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    dataset = await service.record(document_id, engine_agent_id, write=True, lock=True)
    if not dataset.metadata_.get("engine_managed") or dataset.metadata_.get("engine_agent") != engine_agent_id:
        raise service.DatasetPermissionError("Only the owning engine can integrate run values")
    deletions = sorted(set(remove or []))
    if set(deletions).intersection(changes) or files_mode not in {"append", "replace"}:
        raise ValueError("Invalid workflow integration")
    digest = service.fingerprint({"changes": changes, "files": files, "remove": deletions, "files_mode": files_mode})
    previous = await get_db().scalar(select(DatasetIntegration).where(DatasetIntegration.dataset_id == document_id, DatasetIntegration.command == command))
    if previous is not None:
        if previous.fingerprint != digest:
            raise service.DatasetConflictError("This integration command already has a different result")
        return {"id": str(dataset.id), "content": dataset.content, "revision": dataset.revision}
    current = service.parse_json(dataset.content)
    data: dict[str, Any] = current["data"]
    for name, value in changes.items():
        if ((name in data) != (name in baseline) or data.get(name) != baseline.get(name)) and (name not in data or data[name] != value):
            raise service.DatasetConflictError(f"Concurrent workflow writes conflict on variable {name}")
    for name in deletions:
        if name in data and (name not in baseline or data[name] != baseline[name]):
            raise service.DatasetConflictError(f"Concurrent workflow writes conflict on variable {name}")
    merged_files: list[dict[str, Any]] = deepcopy(cast(list[dict[str, Any]], current.get("files", [])))
    if files_mode == "replace":
        if merged_files != baseline_files and merged_files != files:
            raise service.DatasetConflictError("Concurrent workflow changes conflict on the file manifest")
        merged_files = []
    known = {str(entry["uri"]) for entry in merged_files}
    for entry in files:
        if entry["uri"] not in known:
            merged_files.append(deepcopy(entry)); known.add(entry["uri"])
    updated: dict[str, Any] = {**current, "data": {**data, **deepcopy(changes)}, "files": merged_files}
    for name in deletions:
        updated["data"].pop(name, None)
    await service.replace(document_id, engine_agent_id, content=service.encode(updated), expected_revision=dataset.revision, engine=True)
    get_db().add(DatasetIntegration(dataset_id=document_id, command=command, fingerprint=digest, result={"revision": dataset.revision}))
    await get_db().flush()
    await get_db().commit()
    return {"id": str(dataset.id), "content": dataset.content, "revision": dataset.revision}
