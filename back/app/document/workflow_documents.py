"""Public legacy Document operations, including idempotent Lab fixtures."""

from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.sql.selectable import Select

from app.agent import AgentManagementScope
from core.database import get_db
from core.user import HumanActor

from . import document_service, document_sharing, resource_service as service
from .access import effective_access, readable_workflow_document_clause
from .query_policy import prepare_document_read
from .document_types import DocumentType
from .models import Document
from .schemas import DocumentUpdate, DocumentPayload, DocumentContentRevisionPage, DocumentSharing, DocumentSharingLevelUpdate


async def create_workflow_document(*, owner_agent_id: int, title: str, content: str,
                                   kind: DocumentType, command: str,
                                   owner_user_id: int | None = None,
                                   process_code: str | None = None) -> Document:
    """The creation marker and content commit together; lost replies do not duplicate."""
    lock = int.from_bytes(hashlib.sha256(command.encode()).digest()[:8], "big", signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(lock)))
    item = await get_db().scalar(select(Document).where(Document.metadata_["creation_command"].astext == command))
    if item is not None:
        expected_agent = owner_agent_id if owner_user_id is None else None
        if item.document_type != kind or item.owner_user_id != owner_user_id or item.owner_agent_id != expected_agent:
            raise service.DocumentConflictError("Workflow creation identity belongs to a different principal or document kind")
        actor = HumanActor(owner_user_id) if owner_user_id is not None else owner_agent_id
        existing = await read_workflow_document(item.id, actor)
        if existing["content"] != content:
            raise service.DocumentConflictError("Workflow creation identity belongs to different content")
        return item
    if owner_user_id is not None:
        from .schemas import DocumentItemCreate
        from .document_types import document_media_type
        item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner_agent_id, title=title,
            payload=DocumentPayload(text=content), node_kind="document", document_type=kind,
            media_type=document_media_type(kind), visibility="private",
            metadata={"creation_command": command, "process_code": process_code}),
            owner_user_id=owner_user_id, deduplicate=False, workflow_metadata=True)
        return item
    return await document_service.create_document(owner_agent_id=owner_agent_id, title=title, content=content,
        task_id=None, document_type=kind, metadata={"creation_command": command, "process_code": process_code}, workflow_metadata=True)


async def read_workflow_document(document_id: UUID, actor: int | HumanActor,
                                 *, administrative: bool = False) -> dict[str, Any]:
    item, content, access, _, _ = await service.get_item(document_id, agent_id=actor, administrative=administrative)
    return {"id": str(item.id), "title": item.title, "revision": item.revision,
            "type": item.document_type, "content": content.decode("utf-8"), "can_write": access.can_write}


async def write_workflow_document(document_id: UUID, actor: int | HumanActor, content: str,
                                  *, expected_revision: int, title: str | None = None) -> Document:
    data = DocumentUpdate(expected_revision=expected_revision, payload=DocumentPayload(text=content))
    if title is not None:
        data.title = title
    return await service.update_item(document_id, data, actor_agent_id=actor)


async def workflow_document_actor(document_id: UUID, scope: AgentManagementScope, *, write: bool = False) -> int | HumanActor:
    return await document_sharing.document_actor(document_id, scope, write=write)


async def workflow_document_access(document_id: UUID, actor: int | HumanActor) -> bool:
    item = await service.document_record(document_id, revisions=False)
    return item is not None and (await effective_access(item, actor)).can_read


async def workflow_document_is_orphan(document_id: UUID) -> bool:
    from .document_policy import orphan_process_clause
    return bool(await get_db().scalar(select(Document.id).where(Document.id == document_id, orphan_process_clause())))


async def share_workflow_document(document_id: UUID, *, owner_agent_id: int, target_agent_id: int,
                                  access: Literal["read", "edit", "none"], task_id: UUID | None) -> dict[str, object]:
    return await document_service.share_document(document_id, owner_agent_id=owner_agent_id,
        target_agent_id=target_agent_id, access=access, task_id=task_id)


async def prepare_workflow_document_read() -> None:
    """Apply Memory's transaction-local planner policy to document-backed catalogues."""
    await prepare_document_read()


def workflow_document_readable_ids(actor: int | AgentManagementScope) -> Select[tuple[UUID]]:
    """Use exact Document ACLs without unrelated folder ancestry and attachment branches."""
    return select(Document.id).where(readable_workflow_document_clause(actor))


def workflow_document_policy_ids(actor: int | AgentManagementScope) -> Select[tuple[UUID]]:
    """Apply the format visibility policy to documentary resource consumers."""
    from .document_policy import document_policy_clause
    return select(Document.id).where(Document.node_kind == "document",
        document_policy_clause(actor.user_id if isinstance(actor, AgentManagementScope) else None))


def workflow_document_titles() -> Select[tuple[UUID, str]]:
    """Live documentary titles for a consumer's resource-scoped SQL catalogue."""
    return select(Document.id, Document.title.label("title")).where(Document.node_kind == "document")


async def workflow_history(document_id: UUID, actor: int | HumanActor, *, limit: int = 50, offset: int = 0, before_revision: int | None = None) -> DocumentContentRevisionPage:
    return await service.list_document_content_revisions(document_id, actor_agent_id=actor, limit=limit, offset=offset, before_revision=before_revision)


async def workflow_revision(document_id: UUID, actor: int | HumanActor, revision: int) -> dict[str, Any]:
    return {"detail": (await service.get_document_content_revision(document_id, revision, actor_agent_id=actor)).model_dump(mode="json"),
        "diff": (await service.diff_document_content_revision(document_id, revision, actor_agent_id=actor)).model_dump(mode="json")}


async def restore_workflow_document(document_id: UUID, actor: int | HumanActor, revision: int, expected_revision: int) -> Document:
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
