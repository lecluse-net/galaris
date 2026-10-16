"""Public Document operations used by workflow owners and durable run engines."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast
from uuid import UUID
from pathlib import Path
from copy import deepcopy
from fastapi import UploadFile
from starlette.datastructures import Headers

from sqlalchemy import func, select
from sqlalchemy.sql.selectable import Select

from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor
from core.util import complete_io

from . import document_service, document_sharing, service
from .access import effective_access, readable_workflow_document_clause
from .document_policy import dataset_write_scope
from .query_policy import prepare_memory_read
from .document_types import DocumentType
from .models import MemoryItem, DocumentUserGrant
from .schemas import MemoryItemUpdate, MemoryPayload, DocumentContentRevisionPage, DocumentSharing, DocumentSharingLevelUpdate
from .schemas import MemoryGrantUpdate


async def create_workflow_document(*, owner_agent_id: int, title: str, content: str,
                                   kind: DocumentType, command: str,
                                   owner_user_id: int | None = None,
                                   engine_dataset: bool = False,
                                   engine_managed: bool = False,
                                   process_code: str | None = None) -> MemoryItem:
    """The creation marker and content commit together; lost replies do not duplicate."""
    lock = int.from_bytes(hashlib.sha256(command.encode()).digest()[:8], "big", signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(lock)))
    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.metadata_["creation_command"].astext == command))
    if item is not None:
        expected_agent = owner_agent_id if owner_user_id is None else None
        if item.document_type != kind or item.owner_user_id != owner_user_id or item.owner_agent_id != expected_agent or bool(item.metadata_.get("engine_dataset")) != engine_dataset or bool(item.metadata_.get("engine_managed")) != engine_managed:
            raise service.MemoryConflictError("Workflow creation identity belongs to a different principal or document kind")
        if not engine_dataset:
            actor = HumanActor(owner_user_id) if owner_user_id is not None else owner_agent_id
            existing = await read_workflow_document(item.id, actor)
            if existing["content"] != content:
                raise service.MemoryConflictError("Workflow creation identity belongs to different content")
        if engine_dataset and owner_user_id is not None:
            await service.set_item_grant(item.id, owner_agent_id, MemoryGrantUpdate(can_write=True))
        return item
    if owner_user_id is not None:
        from .schemas import MemoryItemCreate
        from .document_types import document_media_type
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner_agent_id, title=title,
            payload=MemoryPayload(text=content), node_kind="document", document_type=kind,
            media_type=document_media_type(kind), visibility="private",
            metadata={"creation_command": command, "process_code": process_code, "engine_dataset": engine_dataset, "engine_managed": engine_managed, "engine_agent": owner_agent_id if engine_dataset else None}),
            owner_user_id=owner_user_id, deduplicate=False, workflow_metadata=True)
        if engine_dataset:
            await service.set_item_grant(item.id, owner_agent_id, MemoryGrantUpdate(can_write=True))
        return item
    return await document_service.create_document(owner_agent_id=owner_agent_id, title=title, content=content,
        task_id=None, document_type=kind, metadata={"creation_command": command, "process_code": process_code, "engine_dataset": engine_dataset, "engine_managed": engine_managed,
            "engine_agent": owner_agent_id if engine_dataset else None}, workflow_metadata=True)


async def read_workflow_document(document_id: UUID, actor: int | HumanActor,
                                 *, administrative: bool = False) -> dict[str, Any]:
    item, content, access, _, _ = await service.get_item(document_id, agent_id=actor, administrative=administrative)
    return {"id": str(item.id), "title": item.title, "revision": item.revision,
            "type": item.document_type, "content": content.decode("utf-8"), "can_write": access.can_write}


async def workflow_attachment_receipt(document_id: UUID, actor: int | HumanActor, key: str) -> dict[str, Any] | None:
    item, _, access, _, _ = await service.get_item(document_id, agent_id=actor)
    if not item.metadata_.get("engine_dataset") or not access.can_write:
        raise service.MemoryPermissionError("Only the run Dataset owner can prepare its attachments")
    receipt = item.metadata_.get("workflow_attachments", {}).get(key)
    return dict(receipt) if receipt is not None else None


async def create_workflow_attachment(document_id: UUID, actor: int | HumanActor, *, key: str,
                                     source_uri: str, path: Path, name: str, media_type: str) -> dict[str, Any]:
    """Register immutable bytes and their command receipt in the same metadata write."""
    lock = int.from_bytes(hashlib.sha256(f"workflow-file:{document_id}:{key}".encode()).digest()[:8], "big", signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(lock)))
    existing = await workflow_attachment_receipt(document_id, actor, key)
    if existing is not None:
        return existing
    def checksum() -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    digest = await complete_io(checksum)
    from .document_attachment_service import add_document_attachment
    with path.open("rb") as stream, dataset_write_scope(document_id):
        upload = UploadFile(stream, filename=name, headers=Headers({"content-type": media_type}))
        await add_document_attachment(document_id, actor_agent_id=actor, upload=upload,
            workflow_receipt=(key, {"origin_uri": source_uri, "filename": name, "sha256": digest}))
    receipt = await workflow_attachment_receipt(document_id, actor, key)
    assert receipt is not None
    return receipt


async def write_workflow_document(document_id: UUID, actor: int | HumanActor, content: str,
                                  *, expected_revision: int, title: str | None = None) -> MemoryItem:
    data = MemoryItemUpdate(expected_revision=expected_revision, payload=MemoryPayload(text=content))
    if title is not None:
        data.title = title
    return await service.update_item(document_id, data, actor_agent_id=actor)


async def workflow_document_actor(document_id: UUID, scope: AgentManagementScope, *, write: bool = False) -> int | HumanActor:
    return await document_sharing.document_actor(document_id, scope, write=write)


async def integrate_workflow_values(document_id: UUID, *, engine_agent_id: int, command: str,
                                    baseline: dict[str, Any], changes: dict[str, Any],
                                    files: list[dict[str, Any]], remove: list[str] | None = None,
                                    files_mode: Literal["append", "replace"] = "append",
                                    baseline_files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Atomically persist a targeted merge and receipt in the owning domain."""
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(document_id):
        await adapter.integrate(document_id, {"engine_agent_id": engine_agent_id, "command": command,
            "baseline": baseline, "changes": changes, "files": files, "remove": remove,
            "files_mode": files_mode, "baseline_files": baseline_files})
        return await read_workflow_document(document_id, engine_agent_id)
    lock = int.from_bytes(hashlib.sha256(f"workflow-data:{document_id}".encode()).digest()[:8], "big", signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(lock)))
    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.id == document_id)
        .with_for_update().execution_options(populate_existing=True))
    if item is None or not item.metadata_.get("engine_managed") or item.metadata_.get("engine_agent") != engine_agent_id:
        raise service.MemoryPermissionError("Only the owning engine can integrate run values")
    deletions = sorted(set(remove or []))
    if set(deletions).intersection(changes):
        raise ValueError("A variable cannot be changed and deleted in the same integration")
    fingerprint = hashlib.sha256(json.dumps({"changes": changes, "files": files, "remove": deletions, "files_mode": files_mode}, ensure_ascii=False,
        sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    receipts: dict[str, str] = dict(item.metadata_.get("workflow_integrations", {}))
    if command in receipts:
        if receipts[command] != fingerprint:
            raise service.MemoryConflictError("This integration command already has a different result")
        return await read_workflow_document(document_id, engine_agent_id)
    document = await read_workflow_document(document_id, engine_agent_id)
    current: dict[str, Any] = json.loads(document["content"])
    data: dict[str, Any] = current["data"]
    for name, value in changes.items():
        same_baseline = (name in data) == (name in baseline) and data.get(name) == baseline.get(name)
        if not same_baseline and (name not in data or data[name] != value):
            raise service.MemoryConflictError(f"Concurrent workflow writes conflict on variable {name}")
    for name in deletions:
        if name in data and (name not in baseline or data[name] != baseline[name]):
            raise service.MemoryConflictError(f"Concurrent workflow writes conflict on variable {name}")
    merged_files: list[dict[str, Any]] = deepcopy(current.get("files", []))
    known: set[str] = {str(entry["uri"]) for entry in merged_files}
    if files_mode == "replace":
        if merged_files != baseline_files and merged_files != files:
            raise service.MemoryConflictError("Concurrent workflow changes conflict on the file manifest")
        merged_files = []
        known = set[str]()
    for entry in files:
        if entry["uri"] not in known:
            merged_files.append(deepcopy(entry))
            known.add(entry["uri"])
    updated: dict[str, Any] = {"data": {**data, **deepcopy(changes)}, "files": merged_files}
    for name in deletions:
        updated["data"].pop(name, None)
    receipts[command] = fingerprint
    with dataset_write_scope(document_id):
        await service.update_item(document_id, MemoryItemUpdate(expected_revision=item.revision,
            payload=MemoryPayload(text=json.dumps(updated, ensure_ascii=False, allow_nan=False)),
            metadata={**item.metadata_, "workflow_integrations": receipts}), actor_agent_id=engine_agent_id)
    return await read_workflow_document(document_id, engine_agent_id)


async def workflow_document_access(document_id: UUID, actor: int | HumanActor) -> bool:
    item = await service.document_record(document_id, revisions=False)
    return item is not None and (await effective_access(item, actor)).can_read


async def workflow_document_is_orphan(document_id: UUID) -> bool:
    from .document_policy import orphan_process_clause
    return bool(await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == document_id, orphan_process_clause())))


async def share_workflow_document(document_id: UUID, *, owner_agent_id: int, target_agent_id: int,
                                  access: Literal["read", "edit", "none"], task_id: UUID | None) -> dict[str, object]:
    return await document_service.share_document(document_id, owner_agent_id=owner_agent_id,
        target_agent_id=target_agent_id, access=access, task_id=task_id)


async def grant_workflow_dataset_access(document_id: UUID, *, engine_agent_id: int, actor: int | HumanActor) -> None:
    """Give every run participant access to the same editable JSON and attachments."""
    item = await service.document_record(document_id, revisions=False)
    if item is None or not item.metadata_.get("engine_dataset") or item.metadata_.get("engine_agent") != engine_agent_id:
        raise service.MemoryPermissionError("Only the owning workflow engine can grant Dataset participants")
    if isinstance(actor, int):
        if item.owner_agent_id != actor:
            await service.set_item_grant(document_id, actor, MemoryGrantUpdate(can_write=True))
    elif item.owner_user_id != actor.user_id:
        from .dataset_port import dataset_compatibility
        adapter = dataset_compatibility()
        if adapter is not None and await adapter.contains(document_id):
            await adapter.grant(document_id, engine_agent_id, "user", actor.user_id, True)
            return
        grant = await get_db().scalar(select(DocumentUserGrant).where(
            DocumentUserGrant.item_id == document_id, DocumentUserGrant.user_id == actor.user_id))
        if grant is None:
            get_db().add(DocumentUserGrant(item_id=document_id, user_id=actor.user_id, can_write=True))
        else:
            grant.can_write = True
        if item.visibility != "public":
            item.visibility = "shared"
        item.lock_version += 1
        await get_db().commit()


async def read_run_workspace(document_id: UUID, actor: int | HumanActor) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read current data and attachment references; scheduler state stays in Process."""
    document = await read_workflow_document(document_id, actor)
    value = json.loads(document["content"])
    if not isinstance(value, dict):
        raise ValueError("The shared run Dataset must contain a JSON object")
    from .dataset_port import dataset_compatibility
    adapter = dataset_compatibility()
    if adapter is not None and await adapter.contains(document_id):
        files = [{"uri": item["uri"], "filename": item["name"], "content_type": item["media_type"], "size": item["size_bytes"]}
            for item in await adapter.attachments(document_id, actor)]
        return cast(dict[str, Any], value), files
    from .document_attachment_service import list_document_attachments
    files = [{"uri": f"document://{document_id}/attachments/{attachment.id}",
        "filename": attachment.name, "content_type": attachment.media_type, "size": attachment.size_bytes}
        for attachment in await list_document_attachments(document_id, actor_agent_id=actor)]
    return cast(dict[str, Any], value), files


async def prepare_workflow_document_read() -> None:
    """Apply Memory's transaction-local planner policy to document-backed catalogues."""
    await prepare_memory_read()


def workflow_document_readable_ids(actor: int | AgentManagementScope) -> Select[tuple[UUID]]:
    """Use exact Document ACLs without unrelated folder ancestry and attachment branches."""
    return select(MemoryItem.id).where(readable_workflow_document_clause(actor))


def workflow_document_policy_ids(actor: int | AgentManagementScope) -> Select[tuple[UUID]]:
    """Apply format visibility independently of a Run's separate Dataset ACL."""
    from .document_policy import document_policy_clause
    return select(MemoryItem.id).where(MemoryItem.node_kind == "document",
        document_policy_clause(actor.user_id if isinstance(actor, AgentManagementScope) else None))


def workflow_document_titles() -> Select[tuple[UUID, str]]:
    """Live documentary titles for a consumer's resource-scoped SQL catalogue."""
    return select(MemoryItem.id, MemoryItem.search_title.label("title")).where(MemoryItem.node_kind == "document")


async def workflow_history(document_id: UUID, actor: int | HumanActor, *, limit: int = 50, offset: int = 0, before_revision: int | None = None) -> DocumentContentRevisionPage:
    return await service.list_document_content_revisions(document_id, actor_agent_id=actor, limit=limit, offset=offset, before_revision=before_revision)


async def workflow_revision(document_id: UUID, actor: int | HumanActor, revision: int) -> dict[str, Any]:
    return {"detail": (await service.get_document_content_revision(document_id, revision, actor_agent_id=actor)).model_dump(mode="json"),
        "diff": (await service.diff_document_content_revision(document_id, revision, actor_agent_id=actor)).model_dump(mode="json")}


async def restore_workflow_document(document_id: UUID, actor: int | HumanActor, revision: int, expected_revision: int) -> MemoryItem:
    return await service.restore_document_content_revision(document_id, revision, expected_revision=expected_revision, actor_agent_id=actor)


async def delete_workflow_revision(document_id: UUID, actor: int | HumanActor, revision: int) -> None:
    await service.delete_process_content_revision(document_id, revision, actor_agent_id=actor)


async def workflow_sharing(document_id: UUID, scope: AgentManagementScope) -> DocumentSharing:
    return await document_sharing.sharing(document_id, scope)


async def workflow_sharing_preview(scope: AgentManagementScope, *, owner_agent_id: int | None) -> DocumentSharing:
    from .item_sharing import sharing_preview
    return await sharing_preview(scope, owner_agent_id=owner_agent_id)


async def resource_sharing_directory(*, owner_agent_id: int | None, owner_user_id: int | None) -> DocumentSharing:
    """Directory shared by resource owners; the caller authorizes its resource first."""
    from .item_sharing import sharing_directory
    return await sharing_directory(owner_agent_id=owner_agent_id, owner_user_id=owner_user_id)


async def update_workflow_sharing(document_id: UUID, scope: AgentManagementScope, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    return await document_sharing.update_level(document_id, data, scope)
