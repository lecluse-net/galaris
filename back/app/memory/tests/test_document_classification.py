from datetime import datetime, timedelta, timezone
import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from app.agent import AgentManagementScope
from app.memory import document_icons, document_order, document_tags, service
from app.memory.models import DocumentIcon
from app.memory.schemas import DocumentIconRequest, DocumentIconWrite, DocumentOrderMove, DocumentOrderNode, DocumentOrderSort
from app.memory.schemas import DocumentLibraryRequest, DocumentTagWrite, DocumentTagIconWrite, MemoryGrantUpdate, MemoryItemCreate, MemoryPayload
from core.user import UserModel


async def human(db):
    user = UserModel(email=f"tags-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type", ["html", "dataset"])
async def test_document_icons_are_private_durable_and_preserve_read_only_content_and_classification(db, agents, memory_storage, document_type):
    owner, reader = agents
    user, other = await human(db), await human(db)
    item = await document(owner, "Illustrated document", document_type)
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    peer = AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids)
    folder = await document_tags.write_tag(user.id, DocumentTagWrite(name="Reading"))
    await document_tags.assign_tag(scope, item.id, folder.id)
    before = (item.revision, item.lock_version, item.updated_at, dict(item.metadata_))
    assert await document_icons.resolve(scope, [item.id]) == {item.id: None}
    await document_icons.save(scope, item.id, DocumentIconWrite(icon="emoji:1F680"))
    assert await document_icons.resolve(scope, [item.id, uuid4()]) == {item.id: "emoji:1F680"}
    assert await document_icons.resolve(peer, [item.id]) == {item.id: None}
    # Moving or deleting the folder does not reset the document's icon.
    await document_tags.remove_tag(user.id, folder.id, confirmed=True)
    assert await document_icons.resolve(scope, [item.id]) == {item.id: "emoji:1F680"}
    await document_icons.save(peer, item.id, DocumentIconWrite(icon="emoji:1F600"))
    await document_icons.save(scope, item.id, DocumentIconWrite(icon=None))
    assert await document_icons.resolve(scope, [item.id]) == {item.id: None}
    assert await document_icons.resolve(peer, [item.id]) == {item.id: "emoji:1F600"}
    # A folder icon saved before the restriction falls back at read time.
    await db.execute(update(DocumentIcon).where(DocumentIcon.user_id == other.id).values(icon="folder:green"))
    await db.commit()
    assert await document_icons.resolve(peer, [item.id]) == {item.id: None}
    await db.refresh(item)
    assert (item.revision, item.lock_version, item.updated_at, item.metadata_) == before
    await service.remove_item_grant(item.id, reader.id, actor_agent_id=owner.id)
    assert await document_icons.resolve(peer, [item.id]) == {}
    with pytest.raises((service.MemoryNotFoundError, service.MemoryPermissionError)):
        await document_icons.save(scope, item.id, DocumentIconWrite(icon="emoji:1F680"))


def test_document_icon_contract_rejects_untrusted_icons_and_unbounded_batches():
    for icon in ("javascript:alert(1)", "font:mdi:unknown-icon", "https://example.test/icon.svg", "folder:green", "folder-open:blue"):
        with pytest.raises(ValidationError):
            DocumentIconWrite(icon=icon)
    with pytest.raises(ValidationError):
        DocumentIconRequest(document_ids=[uuid4() for _ in range(501)])


async def document(owner, title, document_type="html"):
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title=title, node_kind="document", memory_type="working",
        document_type=document_type,
        media_type="application/json" if document_type == "dataset" else "text/html",
        payload=MemoryPayload(text='{"label":"Searchable report"}' if document_type == "dataset" else "<p>Searchable report</p>"),
    ))
    return item


@pytest.mark.asyncio
async def test_classification_notifies_only_its_owner_without_invalidating_document_access(db, agents, memory_storage, monkeypatch):
    from app.memory import events
    from core import websocket

    owner, _ = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner.id}))
    item = await document(owner, "Report")
    notifications = []

    async def capture(subject, action, data, room=None):
        notifications.append((subject, action, data))

    monkeypatch.setattr(websocket, "emit", capture)
    first = await document_tags.write_tag(user.id, DocumentTagWrite(name="Work"))
    second = await document_tags.write_tag(user.id, DocumentTagWrite(name="Reading"))
    assert notifications[-1][2]["tags_changed"] is True
    assert notifications[-1][2]["list_changed"] is False
    await document_tags.move_document(scope, item.id, first.id)
    assert notifications[-1][2]["list_changed"] is True
    await document_tags.move_document(scope, item.id, second.id)
    change = notifications[-1][2]
    assert set(change["tag_ids"]) == {str(first.id), str(second.id)}
    assert change["document_ids"] == [str(item.id)]
    assert change["list_changed"] is False
    assert await events._authorize(user, "classification", change)
    assert not await events._authorize(other, "classification", change)
    await document_order.reorder(scope, DocumentOrderMove(node=DocumentOrderNode(kind="document", id=item.id), list_only=True))
    assert notifications[-1][2]["tag_ids"] == []
    assert notifications[-1][2]["document_ids"] == []
    assert notifications[-1][2]["list_changed"] is True
    await document_tags.remove_tag(user.id, second.id, confirmed=True)
    assert notifications[-1][2]["list_changed"] is True
    assert all(subject == "memory" and action == "classification" for subject, action, _ in notifications)
    # Access revocations keep the existing snapshot invalidation contract.
    await service.invalidate_memory_views()
    assert notifications[-1] == ("memory", "invalidate", {})


@pytest.mark.asyncio
async def test_personal_order_moves_mixed_siblings_and_list_without_writing_documents(db, agents, memory_storage):
    owner, reader = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    first, second, third = [await document(owner, name) for name in ("Alpha", "Beta", "Gamma")]
    for item in (first, second, third):
        await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    before = (first.revision, first.updated_at, first.lock_version)
    root = await document_tags.write_tag(user.id, DocumentTagWrite(name="Work"))
    child = await document_tags.write_tag(user.id, DocumentTagWrite(name="Child", parent_id=root.id))
    last = await document_tags.write_tag(user.id, DocumentTagWrite(name="Last"))
    await document_tags.assign_tag(scope, second.id, root.id)
    await document_tags.assign_tag(scope, first.id, child.id)
    await document_tags.assign_tag(scope, first.id, last.id)
    other_tag = await document_tags.write_tag(other.id, DocumentTagWrite(name="Other user's folder"))
    await document_tags.assign_tag(AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids), first.id, other_tag.id)
    await document_order.reorder(scope, DocumentOrderMove(
        node=DocumentOrderNode(kind="document", id=first.id), parent_id=root.id,
        anchor=DocumentOrderNode(kind="tag", id=child.id),
    ))
    page = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id, include_descendants=False, sort_by="position"), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert [entry.item.id for entry in page.entries] == [first.id, second.id]
    assert [tag.id for tag in page.entries[0].tags] == [root.id]
    child_position = next(tag.position for tag in await document_tags.list_tags(user.id) if tag.id == child.id)
    assert child_position < page.entries[0].position < page.entries[1].position
    await document_order.reorder(scope, DocumentOrderMove(
        node=DocumentOrderNode(kind="tag", id=last.id), anchor=DocumentOrderNode(kind="tag", id=root.id),
    ))
    assert [tag.id for tag in await document_tags.list_tags(user.id) if tag.parent_id is None] == [last.id, root.id]
    # An anchor, rather than a visible-page list, preserves the filtered-out Beta row.
    await document_order.reorder(scope, DocumentOrderMove(
        node=DocumentOrderNode(kind="document", id=third.id), list_only=True,
        anchor=DocumentOrderNode(kind="document", id=first.id),
    ))
    ordered = await service.browse_document_library(DocumentLibraryRequest(sort_by="position", limit=1, offset=1), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert ordered.total == 3
    assert ordered.entries[0].item.id == first.id
    assert [tag.id for tag in ordered.entries[0].tags] == [root.id]
    other_page = await service.browse_document_library(DocumentLibraryRequest(sort_by="position"), managed_agent_ids=scope.agent_ids, user_id=other.id)
    assert [entry.item.id for entry in other_page.entries] == [first.id, second.id, third.id]
    assert [tag.id for tag in other_page.entries[0].tags] == [other_tag.id]
    await document_order.reorder(scope, DocumentOrderMove(
        node=DocumentOrderNode(kind="document", id=first.id),
        anchor=DocumentOrderNode(kind="document", id=second.id), after=True,
    ))
    ordered = await service.browse_document_library(DocumentLibraryRequest(sort_by="position"), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert [entry.item.id for entry in ordered.entries] == [third.id, second.id, first.id]
    assert ordered.entries[-1].tags == []
    await db.refresh(first)
    assert (first.revision, first.updated_at, first.lock_version) == before


@pytest.mark.asyncio
async def test_order_rejects_cycles_foreign_folders_inaccessible_documents_and_stale_anchors(db, agents, memory_storage):
    owner, reader = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner.id}))
    first = await document(owner, "Private")
    root = await document_tags.write_tag(user.id, DocumentTagWrite(name="Root"))
    child = await document_tags.write_tag(user.id, DocumentTagWrite(name="Child", parent_id=root.id))
    foreign = await document_tags.write_tag(other.id, DocumentTagWrite(name="Foreign"))
    with pytest.raises(service.MemoryNotFoundError):
        await document_order.sort_children(user.id, DocumentOrderSort(parent_id=foreign.id))
    await document_tags.assign_tag(scope, first.id, root.id)
    with pytest.raises(ValueError):
        await document_order.reorder(scope, DocumentOrderMove(node=DocumentOrderNode(kind="tag", id=root.id), parent_id=child.id))
    with pytest.raises(service.MemoryNotFoundError):
        await document_order.reorder(scope, DocumentOrderMove(node=DocumentOrderNode(kind="document", id=first.id), parent_id=foreign.id))
    with pytest.raises((service.MemoryNotFoundError, service.MemoryPermissionError)):
        await document_order.reorder(AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id})), DocumentOrderMove(
            node=DocumentOrderNode(kind="document", id=first.id), list_only=True,
        ))
    with pytest.raises(ValueError):
        await document_order.reorder(scope, DocumentOrderMove(node=DocumentOrderNode(kind="document", id=first.id), parent_id=child.id,
            anchor=DocumentOrderNode(kind="tag", id=root.id)))
    page = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id, include_descendants=False), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert [entry.item.id for entry in page.entries] == [first.id]


@pytest.mark.asyncio
async def test_alphabetical_folder_sort_is_durable_private_and_preserves_read_only_documents(db, agents, memory_storage):
    owner, reader = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    root = await document_tags.write_tag(user.id, DocumentTagWrite(name="Root"))
    for name in ("Zèbre", "école", "Abeille"):
        await document_tags.write_tag(user.id, DocumentTagWrite(name=name, parent_id=root.id))
    items = [await document(owner, name) for name in ("Zulu", "Éléphant", "Alpha")]
    for item in items:
        await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
        await document_tags.assign_tag(scope, item.id, root.id)
    before = [(item.revision, item.lock_version, item.updated_at) for item in items]
    for descending in (False, True):
        request = DocumentOrderSort(parent_id=root.id, descending=descending)
        for _ in range(2):
            await document_order.sort_children(user.id, request)
            folders = [tag for tag in await document_tags.list_tags(user.id) if tag.parent_id == root.id]
            page = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id, include_descendants=False, sort_by="position"), managed_agent_ids=scope.agent_ids, user_id=user.id)
            assert [tag.name for tag in folders] == (["Zèbre", "école", "Abeille"] if descending else ["Abeille", "école", "Zèbre"])
            assert [entry.item.title for entry in page.entries] == (["Zulu", "Éléphant", "Alpha"] if descending else ["Alpha", "Éléphant", "Zulu"])
            assert max(tag.position for tag in folders) < min(entry.position for entry in page.entries)
        assert await document_tags.list_tags(other.id) == []
    for item in items:
        await db.refresh(item)
    assert [(item.revision, item.lock_version, item.updated_at) for item in items] == before


@pytest.mark.asyncio
async def test_read_only_classification_is_private_idempotent_and_preserves_document(db, agents, memory_storage):
    owner, reader = agents
    user, other = await human(db), await human(db)
    item = await document(owner, "Public report")
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    before = (item.revision, item.lock_version, item.updated_at, dict(item.metadata_))
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    tag = await document_tags.write_tag(user.id, DocumentTagWrite(name="Reading"))
    for _ in range(2):
        await document_tags.assign_tag(scope, item.id, tag.id)
    page = await service.browse_document_library(DocumentLibraryRequest(classification="classified"), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert [(entry.item.id, [t.id for t in entry.tags]) for entry in page.entries] == [(item.id, [tag.id])]
    assert page.entries[0].item.access.can_write is False
    assert await document_tags.list_tags(other.id) == []
    other_page = await service.browse_document_library(DocumentLibraryRequest(classification="unclassified"), managed_agent_ids=scope.agent_ids, user_id=other.id)
    assert [entry.item.id for entry in other_page.entries] == [item.id]
    with pytest.raises(service.MemoryNotFoundError):
        await document_tags.write_tag(other.id, DocumentTagWrite(name="Stolen"), tag.id)
    with pytest.raises(service.MemoryNotFoundError):
        await service.browse_document_library(DocumentLibraryRequest(tag_id=tag.id), managed_agent_ids=scope.agent_ids, user_id=other.id)
    await document_tags.assign_tag(scope, item.id, tag.id, remove=True)
    await db.refresh(item)
    assert (item.revision, item.lock_version, item.updated_at, item.metadata_) == before


@pytest.mark.asyncio
async def test_tag_tree_rejects_cycles_and_deletes_confirmed_branches_without_deleting_documents(db, agents, memory_storage):
    owner, _ = agents
    user, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({owner.id}))
    item = await document(owner, "Report")
    root = await document_tags.write_tag(user.id, DocumentTagWrite(name="Work"))
    child = await document_tags.write_tag(user.id, DocumentTagWrite(name="Project", parent_id=root.id))
    grandchild = await document_tags.write_tag(user.id, DocumentTagWrite(name="Notes", parent_id=child.id))
    outside = await document_tags.write_tag(user.id, DocumentTagWrite(name="Other"))
    other_tag = await document_tags.write_tag(other.id, DocumentTagWrite(name="Private"))
    await document_tags.assign_tag(scope, item.id, root.id)
    await document_tags.assign_tag(scope, item.id, child.id)
    page = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert page.total == 1
    assert len(page.entries) == 1
    await document_tags.assign_tag(scope, item.id, root.id, remove=True)
    direct = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id, include_descendants=False), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert direct.total == 0
    branch = await service.browse_document_library(DocumentLibraryRequest(tag_id=root.id), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert branch.total == 1
    with pytest.raises(ValueError):
        await document_tags.write_tag(user.id, DocumentTagWrite(name="Cycle", parent_id=child.id), root.id)
    await document_tags.assign_tag(scope, item.id, grandchild.id)
    await document_tags.assign_tag(scope, item.id, outside.id)
    await document_tags.assign_tag(AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids), item.id, other_tag.id)
    before = (item.revision, item.lock_version, item.updated_at, dict(item.metadata_))
    with pytest.raises(service.MemoryNotFoundError):
        await document_tags.remove_tag(other.id, root.id, confirmed=True)
    preview = await document_tags.remove_tag(user.id, root.id)
    assert (preview.deleted, preview.tag_count, preview.document_count) == (False, 3, 1)
    assert {tag.id for tag in await document_tags.list_tags(user.id)} == {root.id, child.id, grandchild.id, outside.id}
    result = await document_tags.remove_tag(user.id, root.id, confirmed=True)
    assert result.deleted
    assert [t.id for t in await document_tags.list_tags(user.id)] == [outside.id]
    assert await service.document_record(item.id) is not None
    page = await service.browse_document_library(DocumentLibraryRequest(classification="unclassified"), managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert [(entry.item.id, entry.tags) for entry in page.entries] == [(item.id, [])]
    other_page = await service.browse_document_library(DocumentLibraryRequest(tag_id=other_tag.id), managed_agent_ids=scope.agent_ids, user_id=other.id)
    assert [entry.item.id for entry in other_page.entries] == [item.id]
    await db.refresh(item)
    assert (item.revision, item.lock_version, item.updated_at, item.metadata_) == before
    assert (await document_tags.remove_tag(user.id, outside.id)).deleted


@pytest.mark.asyncio
async def test_nonempty_branch_requires_confirmation_even_when_it_changed_after_display(db, agents, memory_storage):
    user = await human(db)
    root = await document_tags.write_tag(user.id, DocumentTagWrite(name="Previously empty"))
    child = await document_tags.write_tag(user.id, DocumentTagWrite(name="New child", parent_id=root.id))
    assert not (await document_tags.remove_tag(user.id, root.id)).deleted
    assert (await document_tags.remove_tag(user.id, child.id)).deleted
    item = await document(agents[0], "New document")
    await document_tags.assign_tag(AgentManagementScope(user_id=user.id, agent_ids=frozenset({agents[0].id})), item.id, root.id)
    assert not (await document_tags.remove_tag(user.id, root.id)).deleted
    assert (await document_tags.remove_tag(user.id, root.id, confirmed=True)).deleted


@pytest.mark.asyncio
async def test_filters_apply_before_pagination_and_live_access_hides_classified_documents(db, agents, memory_storage):
    owner, reader = agents
    user = await human(db)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    tag = await document_tags.write_tag(user.id, DocumentTagWrite(name="Reports"))
    items = [await document(owner, f"Report {n}") for n in range(3)]
    for item in items:
        await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
        await document_tags.assign_tag(scope, item.id, tag.id)
    now = datetime.now(timezone.utc)
    request = DocumentLibraryRequest(tag_id=tag.id, query="report", owner_kind="agent", owner=owner.id,
        created_from=now-timedelta(days=1), created_until=now+timedelta(days=1),
        updated_from=now-timedelta(days=1), updated_until=now+timedelta(days=1), limit=1, offset=1)
    page = await service.browse_document_library(request, managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert page.total == 3 and page.has_more
    assert [entry.item.id for entry in page.entries] == [items[1].id]
    assert page.entries[0].owner_label
    for excluded in (
        request.model_copy(update={"owner_kind": "user", "owner": user.id}),
        request.model_copy(update={"classification": "unclassified"}),
        request.model_copy(update={"created_from": None, "created_until": now-timedelta(days=1)}),
        request.model_copy(update={"updated_from": None, "updated_until": now-timedelta(days=1)}),
    ):
        empty = await service.browse_document_library(excluded, managed_agent_ids=scope.agent_ids, user_id=user.id)
        assert empty.total == 0 and empty.entries == []
    await service.remove_item_grant(items[1].id, reader.id, actor_agent_id=owner.id)
    page = await service.browse_document_library(request, managed_agent_ids=scope.agent_ids, user_id=user.id)
    assert page.total == 2 and not page.has_more
    assert [entry.item.id for entry in page.entries] == [items[2].id]
    with pytest.raises(service.MemoryNotFoundError):
        await document_tags.assign_tag(scope, items[1].id, tag.id)


def test_date_filters_require_ordered_timezone_aware_bounds():
    with pytest.raises(ValidationError):
        DocumentLibraryRequest(created_from="2026-01-01T00:00:00")
    with pytest.raises(ValidationError):
        DocumentLibraryRequest(updated_from="2026-02-01T00:00:00Z", updated_until="2026-01-01T00:00:00Z")


@pytest.mark.asyncio
async def test_move_replaces_all_own_tags_preserves_other_users_and_read_only_document(db, agents, memory_storage):
    owner, reader = agents
    user, other = await human(db), await human(db)
    item = await document(owner, "Shared reading")
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    scope = AgentManagementScope(user_id=user.id, agent_ids=frozenset({reader.id}))
    other_scope = AgentManagementScope(user_id=other.id, agent_ids=scope.agent_ids)
    before = (item.revision, item.lock_version, item.updated_at, dict(item.metadata_))
    tags = [await document_tags.write_tag(user.id, DocumentTagWrite(name=name)) for name in ("Old", "Also old", "New")]
    other_tag = await document_tags.write_tag(other.id, DocumentTagWrite(name="Private"))
    for tag in tags[:2]:
        await document_tags.assign_tag(scope, item.id, tag.id)
    await document_tags.assign_tag(other_scope, item.id, other_tag.id)

    async def assigned(current_scope):
        page = await service.browse_document_library(DocumentLibraryRequest(), managed_agent_ids=current_scope.agent_ids, user_id=current_scope.user_id)
        return {tag.id for tag in page.entries[0].tags}

    with pytest.raises(service.MemoryNotFoundError):
        await document_tags.move_document(scope, item.id, other_tag.id)
    assert await assigned(scope) == {tag.id for tag in tags[:2]}
    for _ in range(2):
        await document_tags.move_document(scope, item.id, tags[2].id)
        assert await assigned(scope) == {tags[2].id}
    assert await assigned(other_scope) == {other_tag.id}
    await document_tags.move_document(scope, item.id, None)
    assert await assigned(scope) == set()
    await document_tags.move_document(scope, item.id, tags[0].id)
    assert await assigned(scope) == {tags[0].id}
    await db.refresh(item)
    assert (item.revision, item.lock_version, item.updated_at, item.metadata_) == before
    await service.remove_item_grant(item.id, reader.id, actor_agent_id=owner.id)
    with pytest.raises(service.MemoryNotFoundError):
        await document_tags.move_document(scope, item.id, tags[2].id)
    await service.set_item_grant(item.id, reader.id, MemoryGrantUpdate(can_write=False), actor_agent_id=owner.id)
    assert await assigned(scope) == {tags[0].id}


def svg_data(source):
    return "data:image/svg+xml;base64," + base64.b64encode(source.encode()).decode()


@pytest.mark.asyncio
async def test_icons_survive_rename_moves_and_tag_deletion_and_are_private(db):
    user, other = await human(db), await human(db)
    data = DocumentTagIconWrite(name="Triangle", data=svg_data('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 10L5 0L10 10Z"/></svg>'))
    icon = await document_tags.upload_icon(user.id, data)
    assert (await document_tags.upload_icon(user.id, data)).id == icon.id
    assert await document_tags.list_icons(other.id) == []
    tag = await document_tags.write_tag(user.id, DocumentTagWrite(name="Custom", icon=icon.data))
    renamed = await document_tags.write_tag(user.id, DocumentTagWrite(name="Renamed"), tag.id)
    assert renamed.icon == icon.data
    parent = await document_tags.write_tag(user.id, DocumentTagWrite(name="Parent", icon="/tag-icons/openmoji/1F680.svg"))
    moved = await document_tags.write_tag(user.id, DocumentTagWrite(name="Renamed", parent_id=parent.id), tag.id)
    assert moved.icon == icon.data
    cleared = await document_tags.write_tag(user.id, DocumentTagWrite(name="Renamed", parent_id=parent.id, icon=None), tag.id)
    assert cleared.icon is None
    await document_tags.remove_tag(user.id, tag.id)
    assert [entry.id for entry in await document_tags.list_icons(user.id)] == [icon.id]


@pytest.mark.parametrize("source", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/a"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path fill="url(https://example.test/a)"/></svg>',
    '<!DOCTYPE svg [<!ENTITY x "test">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://example.test";</style></svg>',
    '<?xml-stylesheet href="https://example.test/style.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    '<html/>', 'broken', '<svg xmlns="http://www.w3.org/2000/svg">' + ' ' * 65536 + '</svg>',
])
def test_uploaded_icons_reject_active_external_invalid_and_oversized_svg(source):
    with pytest.raises(ValidationError):
        DocumentTagIconWrite(name="Invalid", data=svg_data(source))
    with pytest.raises(ValidationError):
        DocumentTagWrite(name="Invalid", icon=svg_data(source))


@pytest.mark.parametrize("icon", ["emoji:1F680", "emoji:1F9A6", "folder:blue", "folder-open:iris", "font:mdi:database", "font:fas:database"])
def test_personal_icons_accept_unicode_folders_and_available_font_glyphs(icon):
    assert DocumentTagWrite(name="Tag", icon=icon).icon == icon


@pytest.mark.parametrize("icon", ["emoji:41", "emoji:110000", "folder:unknown", "font:mdi:unknown-glyph", "font:fas:<script>"])
def test_personal_icons_reject_unknown_builtin_glyphs(icon):
    with pytest.raises(ValidationError):
        DocumentTagWrite(name="Tag", icon=icon)


@pytest.mark.parametrize("library", ["openmoji", "fluent"])
def test_previous_svg_emoji_references_become_unicode_without_a_data_migration(library):
    assert DocumentTagWrite(name="Existing", icon=f"/tag-icons/{library}/1F680.svg").icon == "emoji:1F680"
