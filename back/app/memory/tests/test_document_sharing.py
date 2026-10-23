from __future__ import annotations
from app.document import resource_service as documents
from app.document.schemas import DocumentPayload, DocumentSourceCreate
from app.document.schemas import DocumentItemCreate
from app.memory.tests.document_fixtures import create_document_reference, edit_document_summary, project_document
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile
import json

import pytest
from sqlalchemy import select, delete

from app.agent import AgentManagementScope, AgentTeamModel
from app.memory import service
from app.document import resource_service as documents
from app.document import document_sharing, item_sharing, document_attachment_service, document_export
from app.memory.access import effective_access, readable_item_clause
from app.memory.models import MemoryItem
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemorySourceCreate
from app.document.schemas import DocumentLibraryRequest, DocumentSharingUpdate
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel


async def user(db):
    human = UserModel(email=f"doc-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    return human


async def document(owner):
    item, _ = await create_document_reference(DocumentItemCreate(owner_agent_id=owner.id, title="Shared document", node_kind="document",  media_type="text/html", payload=DocumentPayload(text="<p>Initial</p>")))
    return item


@pytest.mark.asyncio
@pytest.mark.parametrize("with_source", [False, True])
async def test_human_can_delete_own_document_but_not_a_shared_document(db, agents, memory_storage, monkeypatch, with_source):
    from fastapi import HTTPException
    from app.memory import router
    from app.document import router as document_router
    from app.document.schemas import DocumentSharingLevelUpdate

    owner, _ = agents
    human = await user(db)
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(document_router, "current_management_scope", AsyncMock(return_value=scope))
    shared = await document(owner)
    await document_sharing.update_level(shared.id, DocumentSharingLevelUpdate(
        level="private", expected_lock_version=shared.lock_version,
        grants=[{"kind": "user", "id": human.id, "can_write": True}],
    ), AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id})))
    with pytest.raises(HTTPException) as denied:
        await router.forget_memory_item(shared.id, actor_agent_id=None)
    assert denied.value.status_code == 403
    assert (await service.get_item(shared.id, agent_id=HumanActor(human.id)))[0].id == shared.id
    with pytest.raises(HTTPException) as denied:
        await document_router.delete_managed_document(shared.id, actor_agent_id=None)
    assert denied.value.status_code == 403

    source = None
    if with_source:
        from .conftest import create_memory_task

        task_id = await create_memory_task(db, owner.id)
        source = DocumentSourceCreate(
            source_kind="task", source_ref=f"task:{task_id}",
        )
    own, _ = await create_document_reference(DocumentItemCreate(
        owner_agent_id=owner.id, title="Personal document", node_kind="document",
        payload=DocumentPayload(text="Personal content"), source=source,
    ), owner_user_id=human.id)
    with pytest.raises(HTTPException) as denied:
        await router.forget_memory_item(own.id, actor_agent_id=None)
    assert denied.value.status_code == 403
    assert (await service.get_item(own.id, agent_id=HumanActor(human.id), memory_content=True))[0].id == own.id
    await document_router.delete_managed_document(own.id, actor_agent_id=None)
    await project_document(own.id)
    with pytest.raises(service.MemoryNotFoundError):
        await service.get_item(own.id, agent_id=HumanActor(human.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("administrative", [False, True])
async def test_document_memory_cannot_be_forgotten_or_merged(db, agents, memory_storage, administrative):
    from app.memory import mcp
    from app.tools.mcp_loader import McpToolContext

    owner, _ = agents
    item = await document(owner)
    resource_id = item.resource_id
    summary = await edit_document_summary(item.id, MemoryItemUpdate(
        payload=MemoryPayload(text="<p>Preserved synthesis.</p>"),
    ), actor_agent_id=owner.id)
    for forget in [
        lambda: service.forget_item(item.id, actor_agent_id=owner.id, administrative=administrative),
        lambda: service.forget_merged_item(item.id),
    ]:
        with pytest.raises(service.MemoryPermissionError):
            await forget()
    result = json.loads(await mcp.memory_forget(McpToolContext(agent_id=owner.id, runtime="internal"), str(item.id)))
    assert "error" in result
    _, content, *_ = await service.get_item(item.id, agent_id=owner.id, memory_content=True)
    assert content == b"<p>Preserved synthesis.</p>"
    assert summary.resource_id == resource_id


@pytest.mark.asyncio
async def test_forgetting_a_contact_cannot_erase_its_document_or_clear_references(db, agents, memory_storage):
    from app.memory import MessengerContactObservation, observe_messenger_contact, forget_messenger_contact
    from app.memory.models import MemoryContactItem

    owner, _ = agents
    contact_id = await observe_messenger_contact(MessengerContactObservation(
        owner_agent_id=owner.id, messaging_id="matrix", user_id="@synthetic-reader:example.test",
        display_name="Synthetic reader",
    ))
    item = await document(owner)
    db.add(MemoryContactItem(owner_agent_id=owner.id, contact_item_id=contact_id, item_id=item.id,
        source_kind="synthetic-test", source_ref="synthetic-document-reference"))
    await db.commit()
    clear_references = AsyncMock(return_value={})
    with pytest.raises(service.MemoryConflictError):
        await forget_messenger_contact(contact_item_id=contact_id, clear_references=clear_references)
    clear_references.assert_not_awaited()
    assert (await service.get_item(item.id, agent_id=owner.id))[1] == b"<p>Initial</p>"
    assert await service.item_record(contact_id) is not None


@pytest.mark.asyncio
async def test_legacy_merge_finding_cannot_transfer_or_delete_document_data(db, agents, memory_storage):
    from app.memory import maintenance
    from app.memory.models import MemoryFinding
    from app.document import DocumentSource
    from app.memory.schemas import MemorySourceCreate

    owner, _ = agents
    items = []
    for label in ("first", "second"):
        item, _ = await create_document_reference(DocumentItemCreate(
            owner_agent_id=owner.id, node_kind="document", title=f"Synthetic {label}",
            media_type="text/html",
            payload=DocumentPayload(text=f"<p>Preserved {label} document.</p>"),
            source=DocumentSourceCreate(source_kind="synthetic-test", source_ref=label),
        ))
        items.append(item)
    first, second = items
    finding = MemoryFinding(kind="duplicate", primary_item_id=first.id, related_item_id=second.id,
        primary_revision=first.revision, related_revision=second.revision, threshold=0.9,
        proposed_action="merge", fingerprint=uuid4().hex, details={})
    db.add(finding)
    await db.commit()
    with pytest.raises(service.MemoryConflictError):
        await maintenance.apply_finding(finding.id, canonical_item_id=first.id)
    for item, label in zip(items, ("first", "second"), strict=True):
        assert (await service.get_item(item.id, agent_id=owner.id))[1] == f"<p>Preserved {label} document.</p>".encode()
        assert list(await db.scalars(select(DocumentSource.source_ref).where(DocumentSource.document_id == item.id))) == [label]
    assert finding.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("sharing_kind", ["agent", "team", "public"])
async def test_document_memory_lifetime_follows_document_access(db, agents, memory_storage, sharing_kind):
    from app.memory.schemas import MemoryGraphRootsRequest, MemorySearchRequest
    from app.document import DocumentSummaryRevision
    from core.storage import get_storage
    from app.memory.contracts import ResourceNotFoundError

    owner, reader = agents
    human = await user(db)
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    item = await document(owner)
    await edit_document_summary(item.id, MemoryItemUpdate(
        payload=MemoryPayload(text="<p>Synthesis with retained history.</p>"),
    ), actor_agent_id=owner.id)
    summary_resource = item.document.summary_resource_id
    if sharing_kind == "team":
        team = TeamModel(name="Synthetic memory readers")
        db.add(team)
        await db.flush()
        db.add(AgentTeamModel(agent_id=reader.id, team_id=team.id))
        await db.commit()
        grants = [{"kind": "team", "id": team.id, "can_write": False}]
    else:
        grants = [{"kind": "agent", "id": reader.id, "can_write": False}] if sharing_kind == "agent" else []
    await level(item, scope, "public" if sharing_kind == "public" else "groups" if sharing_kind == "team" else "private", grants=grants)

    async def visible(agent_id):
        search = await service.search_items(MemorySearchRequest(agent_id=agent_id))
        graph = await service.list_graph_roots(MemoryGraphRootsRequest(agent_id=agent_id))
        assert [hit.item.id for hit in search.hits] == [node.id for node in graph.nodes]
        return [hit.item.id for hit in search.hits]

    assert await visible(reader.id) == [item.id]
    await level(item, scope, "private")
    assert await visible(reader.id) == []
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(item.id, agent_id=reader.id, memory_content=True)
    assert await visible(owner.id) == [item.id]
    assert (await service.get_item(item.id, agent_id=owner.id, memory_content=True))[1] == b"<p>Synthesis with retained history.</p>"
    await level(item, scope, "private", grants=[{"kind": "agent", "id": reader.id, "can_write": False}])
    assert await visible(reader.id) == [item.id]
    await documents.delete_document(item.id, actor_agent_id=owner.id)
    await project_document(item.id)
    for actor in (owner.id, reader.id):
        assert await visible(actor) == []
        with pytest.raises(service.MemoryNotFoundError):
            await service.get_item(item.id, agent_id=actor, memory_content=True)
    assert not list(await db.scalars(select(DocumentSummaryRevision).where(DocumentSummaryRevision.document_id == item.id)))
    with pytest.raises(ResourceNotFoundError):
        await get_storage().read(summary_resource)


async def grant(item, scope, kind, identity, can_write):
    current = await documents.document_record(item.id)
    return await document_sharing.update_sharing(item.id, DocumentSharingUpdate(kind=kind, id=identity, can_write=can_write, expected_lock_version=current.lock_version), scope)


async def level(item, scope, value, can_write=False, grants=None):
    from app.document.schemas import DocumentSharingLevelUpdate
    current = await documents.item_record(item.id)
    return await item_sharing.update_level(item.id, DocumentSharingLevelUpdate(
        level=value, can_write=can_write, grants=grants or [],
        expected_lock_version=current.lock_version,
    ), scope)
