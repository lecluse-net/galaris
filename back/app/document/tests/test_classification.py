"""The established classification journey, running on standalone Document persistence."""
from uuid import uuid4
import pytest
from app.agent import AgentManagementScope
from app.document import document_nesting, document_order, document_tags, resource_service as service
from app.document.schemas import DocumentLibraryRequest, DocumentTagWrite, DocumentOrderMove, DocumentOrderNode, DocumentGrantUpdate, DocumentItemCreate, DocumentPayload
from core.user import UserModel
from app.memory.tests.conftest import agents, memory_storage

async def human(db):
    user = UserModel(email=f"tags-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    return user

@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["all", "classified"])
async def test_subdocuments_are_personal_read_only_safe_and_follow_their_parent(db, agents, memory_storage, classification):
    owner, reader = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    parent, child, grandchild = [await document(owner, title) for title in ("Parent", "Child", "Grandchild")]
    for item in (parent, child, grandchild):
        await service.set_item_grant(item.id, reader.id, DocumentGrantUpdate(can_write=False), actor_agent_id=owner.id)
    before = [(item.revision, item.lock_version, item.updated_at) for item in (parent, child, grandchild)]

    async def browse(**filters):
        filters.setdefault("classification", classification)
        return await service.browse_document_library(DocumentLibraryRequest(**filters),
            managed_agent_ids=scope.agent_ids, user_id=user.id)

    for _ in range(2):
        await document_nesting.move(scope, child.id, parent.id)
    await document_nesting.move(scope, grandchild.id, child.id)
    assert [entry.item.id for entry in (await browse(classification="unclassified")).entries] == [parent.id]
    assert {entry.item.id for entry in (await browse(parent_document_id=parent.id)).entries} == {child.id, grandchild.id}
    direct = await browse(parent_document_id=parent.id, include_descendants=False)
    assert [(entry.item.id, entry.parent_document_id, entry.children_count) for entry in direct.entries] == [(child.id, parent.id, 1)]
    peer = await service.browse_document_library(DocumentLibraryRequest(classification="unclassified"),
        managed_agent_ids=scope.agent_ids, user_id=other.id)
    assert len(peer.entries) == 3 and all(entry.parent_document_id is None and entry.children_count == 0 for entry in peer.entries)

    folder = await document_tags.write_tag(user.id, DocumentTagWrite(name="Reports"))
    await document_tags.move_document(scope, parent.id, folder.id)
    assert {entry.item.id for entry in (await browse(tag_id=folder.id)).entries} == {parent.id, child.id, grandchild.id}
    assert [entry.item.id for entry in (await browse(tag_id=folder.id, include_descendants=False)).entries] == [parent.id]
    for ancestor, descendant in ((parent, parent), (parent, grandchild), (child, grandchild)):
        with pytest.raises(ValueError):
            await document_nesting.move(scope, ancestor.id, descendant.id)
    with pytest.raises(ValueError):
        await document_order.reorder(scope, DocumentOrderMove(node=DocumentOrderNode(kind="document", id=child.id),
            parent_document_id=parent.id, anchor=DocumentOrderNode(kind="document", id=grandchild.id)))
    assert [entry.item.id for entry in (await browse(parent_document_id=parent.id, include_descendants=False)).entries] == [child.id]
    await document_tags.move_document(scope, child.id, folder.id)
    assert (await browse(parent_document_id=parent.id)).entries == []
    assert [entry.item.id for entry in (await browse(parent_document_id=child.id)).entries] == [grandchild.id]
    await document_nesting.move(scope, grandchild.id, None)
    assert [entry.item.id for entry in (await browse(classification="unclassified")).entries] == [grandchild.id]
    for item in (parent, child, grandchild):
        await db.refresh(item)
    assert [(item.revision, item.lock_version, item.updated_at) for item in (parent, child, grandchild)] == before

async def document(owner, title, document_type="html"):
    item, _ = await service.create_item(DocumentItemCreate(
        owner_agent_id=owner.id, title=title, node_kind="document",
        document_type=document_type,
        media_type="application/json" if document_type == "dataset" else "text/html",
        payload=DocumentPayload(text='{"label":"Searchable report"}' if document_type == "dataset" else "<p>Searchable report</p>"),
    ))
    return item
