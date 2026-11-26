"""Synthetic workflows for own ACLs plus recursive personal placement sharing."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.agent import AgentManagementScope
from app.document import document_nesting, document_sharing, document_tags, folder_sharing
from app.document import resource_service as service
from app.document.access import human_document_access
from app.document import DocumentSharingIntent
from app.document.schemas import DocumentSharingLevelUpdate, DocumentSharingUpdate, DocumentTagWrite, DocumentItemCreate, DocumentPayload
from app.document.sharing_inheritance import reconcile_sharing
from app.share import ShareEffectiveAccess, ShareGrant
from core.user import UserModel


async def human(db):
    user = UserModel(email=f"synthetic-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def document(agent, owner, title, kind="text"):
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=agent.id,
        title=title, document_format=kind, node_kind="document",
        payload=DocumentPayload(text='{"synthetic":true}' if kind == "data" else "<p>Synthetic content</p>")), owner_user_id=owner.id)
    return item


async def rule(tag, scope, grants=(), *, public=False):
    current = await folder_sharing.sharing(tag.id, scope)
    return await folder_sharing.update(tag.id, DocumentSharingLevelUpdate(
        level="public" if public else "groups" if any(g[0] == "team" for g in grants) else "private",
        expected_lock_version=current.lock_version,
        grants=[{"kind": kind, "id": identity, "can_write": write} for kind, identity, write in grants],
    ), scope)


@pytest.mark.asyncio
async def test_reusing_archived_agent_code_projects_only_current_rights(db, agents, memory_storage):
    from app.agent import agent_service
    from app.agent.schemas import AgentCreate

    owner = await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    folder = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Public collection"))
    public = await document(agents[0], owner, "Public text")
    private = await document(agents[0], owner, "Restricted data", kind="data")
    await document_tags.move_document(scope, public.id, folder.id)
    await rule(folder, scope, public=True)
    data = AgentCreate(title_id=agents[0].title_id, user_id=owner.id, code="reused-code", first_name="Synthetic")

    async def rights(agent_id):
        rows = await db.execute(select(ShareEffectiveAccess.share_id, ShareEffectiveAccess.can_write)
            .where(ShareEffectiveAccess.agent_id == agent_id,
                   ShareEffectiveAccess.share_id.in_([private.share_id, public.share_id])))
        return dict(rows.tuples().all())

    first = await agent_service.create(data)
    assert await rights(first.id) == {public.share_id: False}
    await document_sharing.update_sharing(private.id, DocumentSharingUpdate(
        kind="agent", id=first.id, can_write=True, expected_lock_version=private.lock_version), scope)
    assert await rights(first.id) == {public.share_id: False, private.share_id: True}
    assert await agent_service.delete(first.id)
    assert await rights(first.id) == {}
    second = await agent_service.create(data)
    assert second.id != first.id
    assert await rights(second.id) == {public.share_id: False}
    assert await rights(first.id) == {}


@pytest.mark.asyncio
async def test_agent_manager_and_archive_refresh_inherited_rights_of_other_readers(db, agents, memory_storage):
    from app.agent import agent_service
    from app.agent.schemas import AgentUpdate

    agent = agents[0]
    previous, other, reader = agent.user_id, await human(db), await human(db)
    scope = AgentManagementScope(user_id=previous, agent_ids=frozenset({agent.id}))
    folder = await document_tags.write_tag(previous, DocumentTagWrite(name="Former manager folder"))
    item, _ = await service.create_item(DocumentItemCreate(owner_agent_id=agent.id,
        title="Agent property", node_kind="document", payload=DocumentPayload(text="<p>Content</p>")))
    await document_sharing.update_sharing(item.id, DocumentSharingUpdate(
        kind="user", id=reader.id, can_write=False, expected_lock_version=item.lock_version), scope)
    await document_tags.move_document(scope, item.id, folder.id)
    await rule(folder, scope, [("user", reader.id, True)])
    projected = select(ShareEffectiveAccess.can_write).where(
        ShareEffectiveAccess.share_id == item.share_id, ShareEffectiveAccess.user_id == reader.id)

    async def check(write):
        assert await db.scalar(projected) is write
        access = await human_document_access(item, reader.id)
        assert access.can_read and access.can_write is write

    await check(True)
    await agent_service.update(agent.id, AgentUpdate(user_id=other.id))
    await check(False)
    await agent_service.update(agent.id, AgentUpdate(user_id=previous))
    await check(True)
    assert await agent_service.delete(agent.id)
    await check(False)


@pytest.mark.asyncio
async def test_user_activation_projects_current_document_rights(db, agents, memory_storage):
    from core.team import TeamModel
    from core.team.service import set_human_membership
    from core.user import UserCreate, UserUpdate, user_service

    owner = await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Public folder"))
    public = await document(agents[0], owner, "Public read")
    restricted = await document(agents[0], owner, "Group edit")
    await document_tags.move_document(scope, public.id, root.id)
    await rule(root, scope, public=True)
    reader = await user_service.create(UserCreate(email="lifecycle-reader@example.com", password="synthetic-password"))
    projected = select(ShareEffectiveAccess.share_id, ShareEffectiveAccess.can_write).where(
        ShareEffectiveAccess.user_id == reader.id,
        ShareEffectiveAccess.share_id.in_([public.share_id, restricted.share_id]))

    async def check(expected):
        assert dict((await db.execute(projected)).tuples().all()) == expected
        for item in (public, restricted):
            access = await human_document_access(item, reader.id)
            assert access.can_read == (item.share_id in expected)
            assert access.can_write == expected.get(item.share_id, False)

    await check({public.share_id: False})
    personal = await document(agents[0], reader, "Private owned document")
    own_right = select(ShareEffectiveAccess.can_write).where(
        ShareEffectiveAccess.share_id == personal.share_id, ShareEffectiveAccess.user_id == reader.id)
    team = TeamModel(name="Account activation")
    db.add(team)
    await db.flush()
    await set_human_membership(team.id, reader.id, True)
    await document_sharing.update_level(restricted.id, DocumentSharingLevelUpdate(
        level="groups", expected_lock_version=restricted.lock_version,
        grants=[{"kind": "team", "id": team.id, "can_write": True},
                {"kind": "user", "id": reader.id, "can_write": False}]), scope)
    await check({public.share_id: False, restricted.share_id: True})
    await user_service.update(reader.id, UserUpdate(is_active=False))
    await check({})
    assert await db.scalar(own_right) is None
    await set_human_membership(team.id, reader.id, False)
    await rule(root, scope)
    await user_service.update(reader.id, UserUpdate(is_active=True))
    await check({restricted.share_id: False})
    assert await db.scalar(own_right) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("child_kind", ["text", "data"])
async def test_recursive_sharing_preserves_own_rights_and_repairs_drift(db, agents, memory_storage, child_kind):
    owner, julie, max_user = [await human(db) for _ in range(3)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic root", parent_id=None))
    sub = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic child", parent_id=root.id))
    parent = await document(agents[0], owner, "Synthetic parent")
    child = await document(agents[0], owner, "Synthetic nested child", child_kind)
    await document_sharing.update_sharing(parent.id, DocumentSharingUpdate(kind="user", id=julie.id,
        can_write=True, expected_lock_version=parent.lock_version), scope)
    await document_tags.move_document(scope, parent.id, sub.id)
    await document_nesting.move(scope, child.id, parent.id)
    await rule(root, scope, [("user", max_user.id, False)])
    for item in (parent, child):
        projected = dict((await db.execute(select(ShareEffectiveAccess.user_id, ShareEffectiveAccess.can_write)
            .where(ShareEffectiveAccess.share_id == item.share_id, ShareEffectiveAccess.user_id.is_not(None)))).all())
        assert projected[julie.id] and projected[max_user.id] is False
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
    assert await db.scalar(select(ShareEffectiveAccess.id).where(
        ShareEffectiveAccess.share_id == child.share_id, ShareEffectiveAccess.user_id == max_user.id)) is None
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
    from app.document.folder_resources import describe_folder
    from core.user import HumanActor
    from app.agent.dialogue_service import set_agent_membership
    from app.document.access import effective_access, human_document_clause, readable_item_clause
    from app.document import Document
    from core.team import TeamModel
    from core.team.service import set_human_membership
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
    with pytest.raises(FileNotFoundError):
        await describe_folder(root.id, HumanActor(reader.id))
    # Recipient membership is evaluated live, without another reconciliation.
    await set_human_membership(team.id, reader.id, True)
    await set_agent_membership(team.id, agents[1].id, True)
    beneficiaries = select(ShareEffectiveAccess.agent_id, ShareEffectiveAccess.user_id,
                          ShareEffectiveAccess.can_write).where(ShareEffectiveAccess.share_id == child.share_id)
    projected = set((await db.execute(beneficiaries)).tuples())
    assert (None, reader.id, True) in projected and (agents[1].id, None, True) in projected
    assert (await human_document_access(child, reader.id)).can_write
    assert (await describe_folder(root.id, HumanActor(reader.id)))["name"] == root.name
    assert (await describe_folder(root.id, agents[1].id))["name"] == root.name
    child = await service.item_record(child.id)
    assert (await effective_access(child, agents[1].id)).can_write
    assert await db.scalar(select(Document.id).where(Document.id == child.id, readable_item_clause(agents[1].id))) == child.id
    assert await db.scalar(select(Document.id).where(Document.id == child.id, human_document_clause(reader.id))) == child.id
    with pytest.raises(RuntimeError, match="interrupted removal"):
        async with db.begin_nested():
            await set_human_membership(team.id, reader.id, False)
            assert (None, reader.id, True) not in set((await db.execute(beneficiaries)).tuples())
            raise RuntimeError("interrupted removal")
    assert set((await db.execute(beneficiaries)).tuples()) == projected
    await set_human_membership(team.id, reader.id, False)
    assert set((await db.execute(beneficiaries)).tuples()) == projected - {(None, reader.id, True)}
    with pytest.raises(FileNotFoundError):
        await describe_folder(root.id, HumanActor(reader.id))
    assert not (await human_document_access(child, reader.id)).can_read
    await document_tags.write_tag(owner.id, DocumentTagWrite(name=sub.name, parent_id=None), sub.id)
    assert not (await effective_access(await service.item_record(child.id), agents[1].id)).can_read


@pytest.mark.asyncio
@pytest.mark.parametrize("folder_owner", [False, True], ids=["agent-document", "human-folder"])
async def test_legacy_owner_team_projects_surviving_rights_on_move_and_archive(db, agents, memory_storage, folder_owner):
    from app.agent import agent_group_service
    from app.agent.dialogue_service import set_agent_membership
    from app.document.access import effective_access
    from app.document.sharing_inheritance import capture_intent
    from core.team import TeamModel
    from core.team.service import delete_team, set_human_membership

    owner, peer = agents
    human_owner = await db.get(UserModel, owner.user_id)
    reader = await human(db)
    scope = AgentManagementScope(human_owner.id, frozenset({owner.id}))
    team = TeamModel(name="Synthetic legacy team")
    db.add(team)
    await db.flush()
    await set_human_membership(team.id, reader.id, True)
    await set_agent_membership(team.id, peer.id, True)
    child = await document(owner, human_owner, "Synthetic descendant")
    await document_sharing.update_sharing(child.id, DocumentSharingUpdate(
        kind="user", id=reader.id, can_write=False, expected_lock_version=child.lock_version), scope)
    if folder_owner:
        from app.document.models import DocumentTag
        tag = await document_tags.write_tag(human_owner.id, DocumentTagWrite(name="Synthetic historical folder"))
        await document_tags.move_document(scope, child.id, tag.id)
        parent = await db.get(DocumentTag, tag.id)
    else:
        parent, _ = await service.create_item(DocumentItemCreate(owner_agent_id=owner.id, title="Synthetic historical parent",
            node_kind="document", payload=DocumentPayload(text="<p>Synthetic</p>")))
        await document_nesting.move(scope, child.id, parent.id)
    parent.group_access = 2
    await capture_intent(parent.share_id)
    await reconcile_sharing()

    async def check(in_team):
        rows = set((await db.execute(select(ShareEffectiveAccess.agent_id, ShareEffectiveAccess.user_id,
            ShareEffectiveAccess.can_write).where(ShareEffectiveAccess.share_id == child.share_id))).tuples())
        expected = {(None, human_owner.id, True), (None, reader.id, in_team)}
        if in_team:
            expected.add((peer.id, None, True))
            if not folder_owner:
                expected.add((owner.id, None, True))
        assert rows == expected
        human_right = await human_document_access(child, reader.id)
        assert human_right.can_read and human_right.can_write == in_team
        assert (await effective_access(child, peer.id)).can_read == in_team

    await check(False)
    for present in (True, False, True):
        if folder_owner:
            await set_human_membership(team.id, human_owner.id, present)
        else:
            await set_agent_membership(team.id, owner.id, present)
        await check(present)
    from core.user import UserUpdate, user_service
    await user_service.update(reader.id, UserUpdate(is_active=False))
    await user_service.update(reader.id, UserUpdate(is_active=True))
    await check(True)
    if folder_owner:
        await delete_team(team.id)
    else:
        assert await agent_group_service.delete(team.id)
    await check(False)


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_kind", ["text", "data"])
async def test_deleting_parent_or_folder_removes_only_inherited_contributions(db, agents, memory_storage, parent_kind):
    from core.user import HumanActor

    owner, reader = [await human(db) for _ in range(2)]
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic removable root", parent_id=None))
    parent = await document(agents[0], owner, "Synthetic removable parent", parent_kind)
    child = await document(agents[0], owner, "Synthetic surviving child")
    await document_sharing.update_sharing(parent.id, DocumentSharingUpdate(kind="user", id=reader.id,
        can_write=True, expected_lock_version=parent.lock_version), scope)
    await document_nesting.move(scope, child.id, parent.id)
    assert (await human_document_access(child, reader.id)).can_write
    await service.delete_document(parent.id, actor_agent_id=HumanActor(owner.id))
    assert not (await human_document_access(child, reader.id)).can_read
    assert await db.scalar(select(ShareEffectiveAccess.id).where(
        ShareEffectiveAccess.share_id.in_((parent.share_id, child.share_id)),
        ShareEffectiveAccess.user_id == reader.id,
    )) is None
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
