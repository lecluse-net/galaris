"""Synthetic workflows for own ACLs plus recursive personal placement sharing."""

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.agent import AgentManagementScope
from app.document import document_nesting, document_sharing, document_tags, folder_sharing
from app.document import resource_service as service
from app.document.access import human_document_access
from app.document import DocumentSharingIntent
from app.document.schemas import DocumentSharingLevelUpdate, DocumentSharingUpdate, DocumentTagWrite, DocumentItemCreate, DocumentPayload
from app.document.sharing_inheritance import reconcile_sharing
from app.share import ShareGrant
from core.user import UserModel


async def human(db):
    user = UserModel(email=f"synthetic-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def document(agent, owner, title):
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=agent.id,
        title=title, node_kind="document", payload=DocumentPayload(text="<p>Synthetic content</p>")), owner_user_id=owner.id)
    return item


async def rule(tag, scope, grants=(), *, public=False):
    current = await folder_sharing.sharing(tag.id, scope)
    return await folder_sharing.update(tag.id, DocumentSharingLevelUpdate(
        level="public" if public else "groups" if any(g[0] == "team" for g in grants) else "private",
        expected_lock_version=current.lock_version,
        grants=[{"kind": kind, "id": identity, "can_write": write} for kind, identity, write in grants],
    ), scope)


@pytest.mark.asyncio
async def test_recursive_sharing_preserves_own_rights_and_repairs_drift(db, agents, memory_storage):
    owner, julie, max_user = [await human(db) for _ in range(3)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic root", parent_id=None))
    sub = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic child", parent_id=root.id))
    parent = await document(agents[0], owner, "Synthetic parent")
    child = await document(agents[0], owner, "Synthetic nested child")
    await document_sharing.update_sharing(parent.id, DocumentSharingUpdate(kind="user", id=julie.id,
        can_write=True, expected_lock_version=parent.lock_version), scope)
    await document_tags.move_document(scope, parent.id, sub.id)
    await document_nesting.move(scope, child.id, parent.id)
    await rule(root, scope, [("user", max_user.id, False)])
    for item in (parent, child):
        assert (await human_document_access(item, julie.id)).can_write
        assert (await human_document_access(item, max_user.id)).can_read
        assert not (await human_document_access(item, max_user.id)).can_write
    # Removing an inherited recipient is accepted and immediately repaired.
    await document_sharing.update_sharing(child.id, DocumentSharingUpdate(kind="user", id=max_user.id,
        can_write=None, expected_lock_version=child.lock_version), scope)
    assert (await human_document_access(child, max_user.id)).can_read
    # Corrupt only the projection, then exercise the actual update reconciler.
    await db.execute(delete(ShareGrant).where(ShareGrant.share_id == child.share_id, ShareGrant.user_id == max_user.id))
    assert not (await human_document_access(child, max_user.id)).can_read
    from app.document.dbadmin import reconcile_sharing as _reconcile_sharing
    await _reconcile_sharing(db)
    assert (await human_document_access(child, max_user.id)).can_read
    intruder = await human(db)
    db.add(ShareGrant(share_id=child.share_id, user_id=intruder.id, can_write=True))
    child.visibility = "private"
    await db.flush()
    assert (await human_document_access(child, intruder.id)).can_read
    await _reconcile_sharing(db)
    assert not (await human_document_access(child, intruder.id)).can_read
    assert child.visibility == "shared"
    versions = (parent.lock_version, child.lock_version)
    assert await reconcile_sharing() == 0
    assert (parent.lock_version, child.lock_version) == versions
    # Saving the displayed effective ACL must not turn inherited rights into own rights.
    displayed = await document_sharing.sharing(child.id, scope)
    await document_sharing.update_level(child.id, DocumentSharingLevelUpdate(
        level=displayed.level, can_write=displayed.can_write, grants=[g.model_dump() for g in displayed.grants],
        expected_lock_version=displayed.lock_version), scope)
    await rule(root, scope)
    assert not (await human_document_access(child, max_user.id)).can_read
    assert (await human_document_access(child, julie.id)).can_write
    await document_tags.move_document(scope, parent.id, None)
    assert (await human_document_access(parent, julie.id)).can_write
    assert (await human_document_access(child, julie.id)).can_write
    assert await db.get(DocumentSharingIntent, parent.share_id) is not None


@pytest.mark.asyncio
async def test_multiple_folders_maximum_right_and_foreign_classification(db, agents, memory_storage):
    owner, other, reader = [await human(db) for _ in range(3)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    foreign_scope = AgentManagementScope(user_id=other.id, agent_ids=frozenset())
    first = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic first", parent_id=None))
    second = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic second", parent_id=None))
    foreign = await document_tags.write_tag(other.id, DocumentTagWrite(name="Synthetic private tree", parent_id=None))
    item = await document(agents[0], owner, "Synthetic shared document")
    await document_sharing.update_sharing(item.id, DocumentSharingUpdate(kind="user", id=other.id,
        can_write=True, expected_lock_version=item.lock_version), scope)
    await document_tags.assign_tag(scope, item.id, first.id)
    await document_tags.assign_tag(scope, item.id, second.id)
    await document_tags.assign_tag(foreign_scope, item.id, foreign.id)
    await rule(foreign, foreign_scope, [("user", reader.id, True)])
    assert not (await human_document_access(item, reader.id)).can_read
    await rule(first, scope, [("user", reader.id, False)])
    await rule(second, scope, [("user", reader.id, True)])
    assert (await human_document_access(item, reader.id)).can_write
    await rule(second, scope)
    assert (await human_document_access(item, reader.id)).can_read
    assert not (await human_document_access(item, reader.id)).can_write
    await document_tags.assign_tag(scope, item.id, first.id, remove=True)
    assert not (await human_document_access(item, reader.id)).can_read
    # Personal trees cannot be read or edited by another user, even a document editor.
    with pytest.raises(service.DocumentNotFoundError):
        await folder_sharing.sharing(first.id, foreign_scope)
    from fastapi import HTTPException
    from unittest.mock import AsyncMock
    from app.document import router
    from unittest.mock import patch
    with patch.object(router, "current_management_scope", AsyncMock(return_value=foreign_scope)):
        with pytest.raises(HTTPException) as denied:
            await router.read_folder_sharing(first.id)
        assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_public_folder_applies_to_late_documents_and_is_revoked_on_move(db, agents, memory_storage):
    owner, reader = [await human(db) for _ in range(2)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic public", parent_id=None))
    await rule(root, scope, public=True)
    item = await document(agents[0], owner, "Synthetic late document")
    await document_tags.move_document(scope, item.id, root.id)
    assert (await human_document_access(item, reader.id)).can_read
    await document_tags.move_document(scope, item.id, None)
    assert not (await human_document_access(item, reader.id)).can_read


@pytest.mark.asyncio
async def test_team_membership_agent_owner_and_subtree_move(db, agents, memory_storage):
    from app.agent import AgentTeamModel
    from app.document.access import effective_access, human_document_clause, readable_item_clause
    from app.document import Document
    from core.team import TeamModel, TeamUserModel
    from sqlalchemy import select

    owner = await db.get(UserModel, agents[0].user_id)
    reader = await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset({agents[0].id}))
    team = TeamModel(name="Synthetic inherited team")
    db.add(team)
    await db.flush()
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic shared root", parent_id=None))
    sub = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic moving branch", parent_id=root.id))
    parent, _ = await service.create_item(DocumentItemCreate(owner_agent_id=agents[0].id,
        title="Synthetic agent document", node_kind="document", payload=DocumentPayload(text="<p>Synthetic</p>")))
    child = await document(agents[0], owner, "Synthetic child")
    await document_tags.move_document(scope, parent.id, sub.id)
    await document_nesting.move(scope, child.id, parent.id)
    await rule(root, scope, [("team", team.id, True)])
    assert not (await human_document_access(child, reader.id)).can_read
    # Recipient membership is evaluated live, without another reconciliation.
    membership = TeamUserModel(user_id=reader.id, team_id=team.id)
    db.add_all([membership, AgentTeamModel(agent_id=agents[1].id, team_id=team.id)])
    await db.flush()
    assert (await human_document_access(child, reader.id)).can_write
    child = await service.item_record(child.id)
    assert (await effective_access(child, agents[1].id)).can_write
    assert await db.scalar(select(Document.id).where(Document.id == child.id, readable_item_clause(agents[1].id))) == child.id
    assert await db.scalar(select(Document.id).where(Document.id == child.id, human_document_clause(reader.id))) == child.id
    await db.delete(membership)
    await db.flush()
    assert not (await human_document_access(child, reader.id)).can_read
    await document_tags.write_tag(owner.id, DocumentTagWrite(name=sub.name, parent_id=None), sub.id)
    assert not (await effective_access(await service.item_record(child.id), agents[1].id)).can_read


@pytest.mark.asyncio
async def test_deleting_parent_or_folder_removes_only_inherited_contributions(db, agents, memory_storage):
    from core.user import HumanActor

    owner, reader = [await human(db) for _ in range(2)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic removable root", parent_id=None))
    parent = await document(agents[0], owner, "Synthetic removable parent")
    child = await document(agents[0], owner, "Synthetic surviving child")
    await document_sharing.update_sharing(parent.id, DocumentSharingUpdate(kind="user", id=reader.id,
        can_write=True, expected_lock_version=parent.lock_version), scope)
    await document_nesting.move(scope, child.id, parent.id)
    assert (await human_document_access(child, reader.id)).can_write
    await service.delete_document(parent.id, actor_agent_id=HumanActor(owner.id))
    assert not (await human_document_access(child, reader.id)).can_read
    await document_tags.move_document(scope, child.id, root.id)
    await rule(root, scope, [("user", reader.id, True)])
    await document_sharing.update_sharing(child.id, DocumentSharingUpdate(kind="user", id=reader.id,
        can_write=False, expected_lock_version=child.lock_version), scope)
    displayed = await document_sharing.sharing(child.id, scope)
    await document_sharing.update_level(child.id, DocumentSharingLevelUpdate(
        level=displayed.level, can_write=displayed.can_write,
        grants=[g.model_dump() for g in displayed.grants], expected_lock_version=displayed.lock_version), scope)
    await document_tags.remove_tag(owner.id, root.id, confirmed=True)
    assert (await human_document_access(child, reader.id)).can_read
    assert not (await human_document_access(child, reader.id)).can_write


@pytest.mark.asyncio
async def test_folder_sharing_rejects_stale_versions_and_rolls_back_with_placement(db, agents, memory_storage):
    from app.document import DocumentTagAssignment
    from app.document.sharing_inheritance import lock_sharing

    owner, reader = [await human(db) for _ in range(2)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    folder = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic atomic folder", parent_id=None))
    item = await document(agents[0], owner, "Synthetic atomic child")
    state = await folder_sharing.sharing(folder.id, scope)
    await rule(folder, scope, [("user", reader.id, True)])
    with pytest.raises(service.DocumentConflictError):
        await folder_sharing.update(folder.id, DocumentSharingLevelUpdate(
            level="private", grants=[], expected_lock_version=state.lock_version), scope)
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        async with db.begin_nested():
            await lock_sharing()
            db.add(DocumentTagAssignment(tag_id=folder.id, document_id=item.id, position=1))
            await reconcile_sharing()
            assert (await human_document_access(item, reader.id)).can_write
            raise RuntimeError("synthetic rollback")
    await db.refresh(item)
    assert not (await human_document_access(item, reader.id)).can_read


@pytest.mark.asyncio
async def test_received_parent_is_skipped_without_hiding_owned_descendants_from_folder_rules(db, agents, memory_storage):
    owner, other, reader = [await human(db) for _ in range(3)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    other_scope = AgentManagementScope(user_id=other.id, agent_ids=frozenset())
    folder = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic mixed branch", parent_id=None))
    received = await document(agents[0], other, "Synthetic received parent")
    child = await document(agents[0], owner, "Synthetic owned descendant")
    await document_sharing.update_sharing(received.id, DocumentSharingUpdate(kind="user", id=owner.id,
        can_write=False, expected_lock_version=received.lock_version), other_scope)
    await document_tags.move_document(scope, received.id, folder.id)
    await document_nesting.move(scope, child.id, received.id)
    await rule(folder, scope, [("user", reader.id, True)])
    assert not (await human_document_access(received, reader.id)).can_read
    assert (await human_document_access(child, reader.id)).can_write
    await rule(folder, scope)
    assert not (await human_document_access(child, reader.id)).can_read
