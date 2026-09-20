from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile
import json

import pytest
from sqlalchemy import select, delete

from app.agent import AgentManagementScope, AgentTeamModel
from app.memory import service, document_sharing, item_sharing, document_attachment_service, document_export
from app.memory.access import effective_access, readable_item_clause
from app.memory.models import MemoryItem
from app.memory.schemas import DocumentLibraryRequest, DocumentSharingUpdate, MemoryItemCreate, MemoryItemUpdate, MemoryPayload
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel


async def user(db):
    human = UserModel(email=f"doc-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    return human


async def document(owner):
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title="Shared document", node_kind="document", memory_type="working", media_type="text/html", payload=MemoryPayload(text="<p>Initial</p>")))
    return item


@pytest.mark.asyncio
async def test_human_can_delete_own_document_but_not_a_shared_document(db, agents, memory_storage, monkeypatch):
    from fastapi import HTTPException
    from app.memory import router
    from app.memory.schemas import DocumentSharingLevelUpdate

    owner, _ = agents
    human = await user(db)
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    shared = await document(owner)
    await document_sharing.update_level(shared.id, DocumentSharingLevelUpdate(
        level="private", expected_lock_version=shared.lock_version,
        grants=[{"kind": "user", "id": human.id, "can_write": True}],
    ), AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id})))
    with pytest.raises(HTTPException) as denied:
        await router.forget_memory_item(shared.id, actor_agent_id=None)
    assert denied.value.status_code == 403
    assert (await service.get_item(shared.id, agent_id=HumanActor(human.id)))[0].id == shared.id

    own, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Personal document", node_kind="document",
        memory_type="working", payload=MemoryPayload(text="Personal content"),
    ), owner_user_id=human.id)
    await router.forget_memory_item(own.id, actor_agent_id=None)
    with pytest.raises(service.MemoryNotFoundError):
        await service.get_item(own.id, agent_id=HumanActor(human.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("node_kind", ["document", "memory"])
@pytest.mark.parametrize("after_commit", [False, True])
async def test_mcp_sharing_conflict_preserves_content_and_safe_retry(
    db, agents, memory_storage, monkeypatch, node_kind, after_commit,
):
    from types import SimpleNamespace
    from fastmcp import FastMCP
    from pydantic_ai.mcp import MCPToolset
    from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
    from app.harness.mcp_toolset import ExecutionEvidenceClient
    from app.harness.tests.test_checkpoint import _request
    from app.memory import mcp
    from app.tools.execution_evidence import ExecutionEvidenceMiddleware
    from app.tools.mcp_loader import McpToolContext, _wrap_tool
    from app.tools import mandatory_tools

    owner, peer = agents
    await mandatory_tools.sync_integrated_tool_connections(owner.id)
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Sharing after editing", node_kind=node_kind,
        memory_type="working" if node_kind == "document" else "semantic",
        media_type="text/html", payload=MemoryPayload(text="<p>Original</p>"),
    ))
    ctx = McpToolContext(agent_id=owner.id, runtime="internal", task_id=uuid4())
    previous = json.loads(await mcp.memory_sharing(ctx, str(item.id)))
    item = await service.update_item(item.id, MemoryItemUpdate(
        expected_revision=item.revision, payload=MemoryPayload(text="<p>Updated dossier</p>"),
    ), actor_agent_id=owner.id)
    current_version, current_revision = item.lock_version, item.revision
    assert current_version != previous["lock_version"]

    if after_commit:
        commit = service.commit_item_sharing

        async def lost_response(record):
            await commit(record)
            raise service.MemoryConflictError("Response failed after commit")

        monkeypatch.setattr(service, "commit_item_sharing", lost_response)

    tool_name = f"{node_kind}_share"
    function = getattr(mcp, tool_name)
    server = FastMCP("sharing-recovery")
    server.add_middleware(ExecutionEvidenceMiddleware({tool_name}))
    server.tool(_wrap_tool(function.__galaris_mcp_tool__, ctx))
    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save_checkpoint=save))
    toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], checkpoint)[0]
    args = {
        f"{node_kind}_id": str(item.id), "agent_id": peer.id, "access": "read",
        "expected_lock_version": current_version if after_commit else previous["lock_version"],
    }
    call_ctx = SimpleNamespace(messages=[], tool_call_id="share")
    tool = SimpleNamespace(tool_def=SimpleNamespace(metadata={}))
    failure = await toolset.call_tool(tool_name, args, call_ctx, tool)
    if not after_commit:
        assert "Sharing changed" in failure["error"]
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
    await resumed.prepare_resume()
    if after_commit:
        assert failure["outcome"] == "unknown"
        assert resumed.take_replay(tool_name, args) == (True, failure)
    else:
        assert failure["status"] == "error"
    record, content, *_ = await service.get_item(item.id, agent_id=owner.id)
    assert b"Updated dossier" in content and record.revision == current_revision
    assert (await effective_access(record, peer.id)).can_read is after_commit
    if not after_commit:
        assert record.lock_version == current_version
        refreshed = json.loads(await mcp.memory_sharing(ctx, str(item.id)))
        # No Task resource projection is needed for this independent sharing call.
        retry_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
        await function(retry_ctx, **{**args, "expected_lock_version": refreshed["lock_version"]})
        assert (await effective_access(await service.item_record(item.id), peer.id)).can_read


async def grant(item, scope, kind, identity, can_write):
    current = await service.document_record(item.id)
    return await document_sharing.update_sharing(item.id, DocumentSharingUpdate(kind=kind, id=identity, can_write=can_write, expected_lock_version=current.lock_version), scope)


@pytest.mark.asyncio
@pytest.mark.parametrize(("node_kind", "document_type"), [("document", "html"), ("document", "dataset"), ("memory", "html")])
async def test_mcp_sharing_uses_live_team_membership_and_preserves_other_grants(db, agents, memory_storage, node_kind, document_type):
    from app.memory import mcp
    from app.tools.mcp_loader import McpToolContext
    from core.team.service import set_human_membership
    from app.agent.dialogue_service import set_agent_membership

    owner, peer = agents
    human = await user(db)
    team = TeamModel(name="Research group")
    db.add(team)
    await db.flush()
    body = '{"evidence":"<h2>Evidence</h2>"}' if document_type == "dataset" else "<h2>Evidence</h2><p>Verified fact.</p>"
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Team knowledge", node_kind=node_kind,
        document_type=document_type,
        memory_type="working" if node_kind == "document" else "semantic",
        media_type="application/json" if document_type == "dataset" else "text/html", payload=MemoryPayload(text=body),
    ))
    original_revision = item.revision
    uri = f"{node_kind}://{item.id}"
    ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    peer_ctx = McpToolContext(agent_id=peer.id, runtime="internal")

    async def share(**kwargs):
        if node_kind == "document":
            result = json.loads(await mcp.document_share(ctx, uri, **kwargs))
            assert "error" not in result, result
            return result
        return json.loads(await mcp.memory_share(ctx, uri, **kwargs))

    initial = json.loads(await mcp.memory_sharing(ctx, uri))
    assert any(option["kind"] == "team" and option["id"] == team.id for option in initial["options"])
    assert any(option["kind"] == "user" and option["id"] == owner.user_id for option in initial["options"])
    team_options = json.loads(await mcp.memory_sharing(ctx, uri, kind="team", search="research", limit=1))
    assert [option["id"] for option in team_options["options"]] == [team.id]
    assert team_options["total"] == 1 and not team_options["has_more"]
    await share(team_id=team.id, access="read", expected_lock_version=initial["lock_version"])
    assert item.revision == original_revision
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(item.id, agent_id=peer.id)
    await set_agent_membership(team.id, peer.id, True)
    await set_human_membership(team.id, human.id, True)
    for actor in (peer.id, HumanActor(human.id)):
        record, content, access, *_ = await service.get_item(item.id, agent_id=actor)
        assert b"<h2>Evidence</h2>" in content
        assert access.can_read and not access.can_write
        with pytest.raises(service.MemoryPermissionError):
            await service.assert_item_access(record, actor, write=True)
    with pytest.raises(service.MemoryPermissionError):
        await mcp.memory_sharing(peer_ctx, uri)

    await share(team_id=team.id, access="edit")
    for actor in (peer.id, HumanActor(human.id)):
        assert (await effective_access(await service.item_record(item.id), actor)).can_write
    with pytest.raises(service.MemoryPermissionError):
        await mcp.memory_share(peer_ctx, uri, user_id=human.id, access="edit")

    # Removing one membership or grant must not accidentally remove independent access.
    await share(agent_id=peer.id, access="read")
    await set_agent_membership(team.id, peer.id, False)
    access = await effective_access(await service.item_record(item.id), peer.id)
    assert access.can_read and not access.can_write
    await share(team_id=team.id, access="none")
    assert not (await effective_access(await service.item_record(item.id), HumanActor(human.id))).can_read
    assert (await effective_access(await service.item_record(item.id), peer.id)).can_read
    await share(user_id=human.id, access="read")
    await share(agent_id=peer.id, access="none")
    assert not (await effective_access(await service.item_record(item.id), peer.id)).can_read
    assert (await effective_access(await service.item_record(item.id), HumanActor(human.id))).can_read
    final = json.loads(await mcp.memory_sharing(ctx, uri))
    assert [(grant["kind"], grant["id"]) for grant in final["grants"]] == [("user", human.id)]
    with pytest.raises(service.MemoryConflictError):
        await mcp.memory_share(ctx, uri, team_id=team.id, expected_lock_version=initial["lock_version"])
    with pytest.raises(ValueError):
        await mcp.memory_share(ctx, uri, team_id=team.id, agent_id=peer.id)
    with pytest.raises(ValueError):
        await mcp.memory_share(ctx, uri)
    with pytest.raises(service.MemoryNotFoundError):
        await mcp.memory_share(ctx, uri, team_id=2147483647)
    current = json.loads(await mcp.memory_sharing(ctx, uri))
    assert current["lock_version"] == final["lock_version"]
    assert current["grants"] == final["grants"]
    assert item.revision == original_revision
    if node_kind == "memory":
        item.read_only = True
        await db.commit()
        with pytest.raises(service.MemoryPermissionError):
            await mcp.memory_share(ctx, uri, team_id=team.id)


@pytest.mark.asyncio
async def test_human_without_agents_reads_edits_exports_and_loses_access(db, agents, memory_storage, monkeypatch):
    from app.memory import events
    owner, outsider = agents
    human = await user(db)
    item = await document(owner)
    manager = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    human_scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    monkeypatch.setattr(events, "management_scope_for", AsyncMock(return_value=human_scope))
    event = {"id": str(item.id)}
    assert not await events._authorize(human, "update", event)
    actor = HumanActor(human.id)
    attachment = await document_attachment_service.add_document_attachment_bytes(item.id, actor_agent_id=owner.id, name="notes.txt", media_type="text/plain", content=b"Attached")
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(item.id, agent_id=actor)
    await grant(item, manager, "user", human.id, False)
    assert await events._authorize(human, "update", event)
    page = await service.browse_document_library(DocumentLibraryRequest(), managed_agent_ids=frozenset(), user_id=human.id)
    assert [entry.item.id for entry in page.entries] == [item.id]
    assert page.entries[0].agent_ids == []
    assert page.entries[0].user_access.can_read
    assert await document_sharing.document_actor(item.id, human_scope) == actor
    assert (await document_attachment_service.read_document_attachment(item.id, attachment.id, actor_agent_id=actor))[1] == b"Attached"
    archive = await document_export.export_document_bundle(item.id, "<p>Snapshot</p>", actor_agent_id=actor)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert len(zip_file.namelist()) == 2
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(item.id, MemoryItemUpdate(payload=MemoryPayload(text="<p>Denied</p>")), actor_agent_id=actor)
    await grant(item, manager, "user", human.id, True)
    updated = await service.update_item(item.id, MemoryItemUpdate(expected_revision=item.revision, payload=MemoryPayload(text="<p>Human edit</p>")), actor_agent_id=actor)
    assert updated.revision == 2
    await service.restore_document_content_revision(item.id, 1, expected_revision=2, actor_agent_id=actor)
    # Human rights never become rights of an Agent that the human happens to use.
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(item.id, agent_id=outsider.id)
    monkeypatch.setattr(item_sharing, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(service.MemoryPermissionError):
        await grant(item, human_scope, "agent", outsider.id, True)
    with pytest.raises(service.MemoryPermissionError):
        await level(item, human_scope, "public", True)
    await grant(item, manager, "user", human.id, None)
    assert not await events._authorize(human, "update", event)
    with pytest.raises(service.MemoryPermissionError):
        await document_attachment_service.read_document_attachment(item.id, attachment.id, actor_agent_id=actor)
    assert (await service.browse_document_library(DocumentLibraryRequest(), managed_agent_ids=frozenset(), user_id=human.id)).entries == []


@pytest.mark.asyncio
async def test_live_team_membership_applies_to_agents_and_humans_without_collisions(db, agents, memory_storage):
    owner, member = agents
    human = await user(db)
    team = TeamModel(name="Document team")
    db.add(team)
    await db.flush()
    db.add(AgentTeamModel(agent_id=member.id, team_id=team.id))
    db.add(TeamUserModel(team_id=team.id, user_id=human.id))
    await db.commit()
    item = await document(owner)
    manager = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    await grant(item, manager, "team", team.id, True)
    assert (await effective_access(item, member.id)).can_write
    assert (await effective_access(item, HumanActor(human.id))).can_write
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, readable_item_clause(member.id))) == item.id
    # Direct read survives team removal, but team-derived editing disappears.
    await grant(item, manager, "agent", member.id, False)
    await db.execute(delete(AgentTeamModel).where(AgentTeamModel.agent_id == member.id))
    await db.execute(delete(TeamUserModel).where(TeamUserModel.team_id == team.id))
    await db.commit()
    current = await service.document_record(item.id)
    assert (await effective_access(current, member.id)).can_read
    assert not (await effective_access(current, member.id)).can_write
    assert not (await effective_access(current, HumanActor(human.id))).can_read
    await grant(item, manager, "agent", member.id, None)
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, readable_item_clause(member.id))) is None
    # Soft deletion of a team also revokes its live grants.
    db.add(AgentTeamModel(agent_id=member.id, team_id=team.id))
    await db.commit()
    assert (await effective_access(current, member.id)).can_write
    team.soft_delete()
    await db.commit()
    assert not (await effective_access(current, member.id)).can_read


@pytest.mark.asyncio
async def test_stale_sharing_cannot_overwrite_new_grants(db, agents, memory_storage):
    owner, peer = agents
    human = await user(db)
    item = await document(owner)
    manager = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    version = item.lock_version
    await grant(item, manager, "user", human.id, True)
    with pytest.raises(service.MemoryConflictError):
        await document_sharing.update_sharing(item.id, DocumentSharingUpdate(kind="agent", id=peer.id, can_write=True, expected_lock_version=version), manager)


@pytest.mark.asyncio
async def test_default_private_public_rights_and_authenticated_identity(db, agents, memory_storage, monkeypatch):
    from app.memory import router
    from app.memory.schemas import DocumentGlobalAccessUpdate
    from fastapi import HTTPException

    owner, outsider = agents
    human = await user(db)
    item = await document(owner)
    assert item.global_access == 0
    assert (await document_sharing.sharing(item.id, AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id})))).grants == []
    assert not (await effective_access(item, HumanActor(human.id))).can_read
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scope))
    assert await router._document_request_actor(item.id, None) == HumanActor(human.id)
    monkeypatch.setattr(router, "_require_agent_scope", AsyncMock(side_effect=HTTPException(status_code=403)))
    with pytest.raises(HTTPException):
        await router._document_request_actor(item.id, outsider.id)
    for value in [1, 2, 0]:
        item = await service.set_document_global_access(item.id, DocumentGlobalAccessUpdate(global_access=value, expected_revision=item.revision, expected_lock_version=item.lock_version))
        for actor in [HumanActor(human.id), outsider.id]:
            access = await effective_access(item, actor)
            assert access.can_read == (value > 0)
            assert access.can_write == (value == 2)
        page = await service.browse_document_library(DocumentLibraryRequest(), managed_agent_ids=frozenset(), user_id=human.id)
        assert bool(page.entries) == (value > 0)


async def level(item, scope, value, can_write=False, grants=None):
    from app.memory.schemas import DocumentSharingLevelUpdate
    current = await service.item_record(item.id)
    return await item_sharing.update_level(item.id, DocumentSharingLevelUpdate(
        level=value, can_write=can_write, grants=grants or [],
        expected_lock_version=current.lock_version,
    ), scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("node_kind", ["document", "memory"])
@pytest.mark.parametrize("kind", ["agent", "user", "team"])
async def test_atomic_sharing_preserves_content_and_enforces_each_recipient_right(db, agents, memory_storage, node_kind, kind):
    owner, peer = agents
    manager, human = await user(db), await user(db)
    team = TeamModel(name="Recipients")
    db.add(team)
    await db.flush()
    db.add_all([AgentTeamModel(agent_id=peer.id, team_id=team.id), TeamUserModel(user_id=human.id, team_id=team.id)])
    await db.commit()
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind=node_kind,
        memory_type="working" if node_kind == "document" else "semantic",
        title="Sharing contract", media_type="text/html", payload=MemoryPayload(text="<p>Preserved</p>"),
    ))
    scope = AgentManagementScope(user_id=manager.id, agent_ids=frozenset({owner.id}))
    actors = [peer.id] if kind == "agent" else [HumanActor(human.id)] if kind == "user" else [peer.id, HumanActor(human.id)]
    target_id = peer.id if kind == "agent" else human.id if kind == "user" else team.id
    revision, content_hash = item.revision, item.content_hash
    assert not (await effective_access(item, actors[0])).can_read
    for write in [False, True]:
        state = await level(item, scope, "groups" if kind == "team" else "private",
                            grants=[{"kind": kind, "id": target_id, "can_write": write}])
        assert [(g.kind, g.id, g.can_write) for g in state.grants] == [(kind, target_id, write)]
        for actor in actors:
            loaded, content, access, *_ = await service.get_item(item.id, agent_id=actor)
            assert content == b"<p>Preserved</p>"
            assert access.can_read and access.can_write == write
            if not write:
                with pytest.raises(service.MemoryPermissionError):
                    await service.update_item(item.id, MemoryItemUpdate(title="Denied"), actor_agent_id=actor)
        assert loaded.revision == revision and loaded.content_hash == content_hash
        if kind != "user":
            assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id, readable_item_clause(peer.id))) == item.id
    # Public read keeps selected writers and grants read to outsiders.
    state = await level(item, scope, "public", grants=[{"kind": kind, "id": target_id, "can_write": True}])
    assert not state.can_write and state.grants[0].can_write
    assert (await effective_access(item, HumanActor(manager.id))).can_read
    assert not (await effective_access(item, HumanActor(manager.id))).can_write
    for actor in actors:
        assert (await effective_access(item, actor)).can_write
    await level(item, scope, "public", True)
    assert (await effective_access(item, HumanActor(manager.id))).can_write
    await level(item, scope, "private")
    for actor in actors:
        with pytest.raises(service.MemoryPermissionError):
            await service.get_item(item.id, agent_id=actor)
    assert (await service.item_record(item.id)).revision == revision


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_kind", ["agent", "user"])
async def test_selected_owner_groups_are_explicit_and_memberships_remain_live(db, agents, memory_storage, owner_kind):
    owner, peer = agents
    human, reader = await user(db), await user(db)
    team = TeamModel(name="Selected group")
    db.add(team)
    await db.flush()
    membership_model = AgentTeamModel if owner_kind == "agent" else TeamUserModel
    owner_field = "agent_id" if owner_kind == "agent" else "user_id"
    owner_id = owner.id if owner_kind == "agent" else human.id
    db.add_all([membership_model(**{owner_field: owner_id, "team_id": team.id}),
                AgentTeamModel(agent_id=peer.id, team_id=team.id),
                TeamUserModel(user_id=reader.id, team_id=team.id)])
    await db.commit()
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Selected groups", node_kind="document",
        memory_type="working", payload=MemoryPayload(text="Content"),
    ), owner_user_id=human.id if owner_kind == "user" else None)
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}) if owner_kind == "agent" else frozenset())
    state = await document_sharing.sharing(item.id, scope)
    assert state.owner.kind == owner_kind and [g.id for g in state.owner_groups] == [team.id]
    assert state.level == "private" and not state.grants
    for write in [False, True]:
        state = await level(item, scope, "groups", grants=[{"kind": "team", "id": team.id, "can_write": write}])
        for actor in [peer.id, HumanActor(reader.id)]:
            assert (await effective_access(item, actor)).can_write == write
            assert (await effective_access(item, actor)).can_read
    # Removing the owner from a selected group does not silently replace the selection.
    await db.execute(delete(membership_model).where(getattr(membership_model, owner_field) == owner_id))
    await db.commit()
    assert (await effective_access(item, peer.id)).can_write
    assert (await document_sharing.sharing(item.id, scope)).owner_groups == []
    # Removing a recipient from the group revokes its inherited access.
    await db.execute(delete(AgentTeamModel).where(AgentTeamModel.agent_id == peer.id))
    await db.commit()
    assert not (await effective_access(item, peer.id)).can_read
    assert (await effective_access(item, HumanActor(reader.id))).can_write


@pytest.mark.asyncio
async def test_legacy_groups_become_explicit_and_survive_owner_transfer(db, agents, memory_storage):
    from app.memory.schemas import DocumentOwnerUpdate
    owner, peer = agents
    human = await user(db)
    old_team, new_team = TeamModel(name="Old owner"), TeamModel(name="New owner")
    db.add_all([old_team, new_team])
    await db.flush()
    db.add_all([AgentTeamModel(agent_id=owner.id, team_id=old_team.id),
                AgentTeamModel(agent_id=peer.id, team_id=old_team.id),
                TeamUserModel(user_id=human.id, team_id=new_team.id)])
    item = await document(owner)
    item.group_access = 2
    item.visibility = "shared"
    await db.commit()
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    state = await document_sharing.sharing(item.id, scope)
    assert state.level == "groups" and not state.can_write
    assert [(g.id, g.can_write) for g in state.grants] == [(old_team.id, True)]
    await level(item, scope, "groups", grants=[{"kind": "team", "id": old_team.id, "can_write": True}])
    assert item.group_access == 0
    item = await service.transfer_document_owner(item.id, DocumentOwnerUpdate(
        kind="user", id=human.id, expected_revision=item.revision,
        expected_lock_version=item.lock_version,
    ), actor_agent_id=owner.id)
    assert (await effective_access(item, peer.id)).can_write
    state = await document_sharing.sharing(item.id, AgentManagementScope(user_id=human.id, agent_ids=frozenset()))
    assert [g.id for g in state.grants if g.kind == "team"] == [old_team.id]
    assert [g.id for g in state.owner_groups] == [new_team.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("node_kind", ["document", "memory"])
async def test_sharing_rejects_stale_invalid_and_non_owner_updates_atomically(db, agents, memory_storage, monkeypatch, node_kind):
    from app.memory.schemas import DocumentSharingLevelUpdate
    owner, peer = agents
    human = await user(db)
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, node_kind=node_kind, title="Atomic permissions",
        memory_type="working" if node_kind == "document" else "semantic",
        payload=MemoryPayload(text="Unchanged"),
    ))
    manager = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    writer = AgentManagementScope(user_id=human.id, agent_ids=frozenset({peer.id}))
    stale_version = item.lock_version
    selected = [{"kind": "agent", "id": peer.id, "can_write": True}]
    state = await level(item, manager, "private", grants=selected)
    monkeypatch.setattr(item_sharing, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(service.MemoryPermissionError):
        await level(item, writer, "public", True)
    with pytest.raises(service.MemoryPermissionError):
        await service.update_item(item.id, MemoryItemUpdate(visibility="public"), actor_agent_id=peer.id)
    for grants, expected, error in [
        ([], stale_version, service.MemoryConflictError),
        (selected * 2, state.lock_version, ValueError),
        ([{"kind": "user", "id": 2147483647, "can_write": True}], state.lock_version, service.MemoryNotFoundError),
        ([{"kind": "agent", "id": owner.id}], state.lock_version, service.MemoryNotFoundError),
    ]:
        with pytest.raises(error):
            await item_sharing.update_level(item.id, DocumentSharingLevelUpdate(
                level="private", grants=grants, expected_lock_version=expected,
            ), manager)
        current = await item_sharing.sharing(item.id, manager)
        assert current.lock_version == state.lock_version
        assert [(g.kind, g.id, g.can_write) for g in current.grants] == [("agent", peer.id, True)]
    await level(item, manager, "private")
    for field in (["source_managed", "read_only"] if node_kind == "memory" else []):
        setattr(item, field, True)
        if field == "source_managed":
            item.managed_source_kind = "test"
            item.managed_source_ref = "test:sharing"
            item.read_only = True
        await db.commit()
        assert not (await item_sharing.sharing(item.id, manager)).can_manage
        with pytest.raises(service.MemoryPermissionError):
            await level(item, manager, "public", True)
        setattr(item, field, False)
        item.managed_source_kind = None
        item.managed_source_ref = None
        item.read_only = False
        await db.commit()


@pytest.mark.asyncio
async def test_memory_routes_support_human_access_without_granting_it_to_their_agents(db, agents, memory_storage, monkeypatch):
    from fastapi import HTTPException
    from app.memory import router
    from app.memory.schemas import DocumentSharingLevelUpdate
    owner, peer = agents
    human = await user(db)
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Human memory", payload=MemoryPayload(text="Original"),
    ))
    manager = AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id}))
    reader = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=reader))
    monkeypatch.setattr(item_sharing, "check_privilege", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as denied:
        await router.read_item_sharing(item.id)
    assert denied.value.status_code == 404
    for write in [False, True]:
        monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=manager))
        state = await router.update_item_sharing(item.id, DocumentSharingLevelUpdate(
            level="private", expected_lock_version=item.lock_version,
            grants=[{"kind": "user", "id": human.id, "can_write": write}],
        ))
        monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=reader))
        detail = await router.get_memory_item(item.id, agent_id=None, revision=None)
        assert detail.access.can_read and detail.access.can_write == write
        readonly = await router.read_item_sharing(item.id)
        assert not readonly.can_manage and readonly.options == []
        with pytest.raises(HTTPException) as denied:
            await router.update_item_sharing(item.id, DocumentSharingLevelUpdate(
                level="public", can_write=True, grants=[], expected_lock_version=state.lock_version,
            ))
        assert denied.value.status_code == 403
        if write:
            updated = await router.update_memory_item(item.id, MemoryItemUpdate(title="Human edited"), actor_agent_id=None)
            assert updated.title == "Human edited"
        else:
            with pytest.raises(HTTPException) as denied:
                await router.update_memory_item(item.id, MemoryItemUpdate(title="Denied"), actor_agent_id=None)
            assert denied.value.status_code == 403
        with pytest.raises(service.MemoryPermissionError):
            await service.get_item(item.id, agent_id=peer.id)


@pytest.mark.asyncio
async def test_ownerless_generated_memory_exposes_readonly_public_sharing(db, agents, memory_storage):
    human = await user(db)
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=agents[0].id, title="Generated memory", payload=MemoryPayload(text="Generated"),
    ))
    item.owner_agent_id = None
    item.source_managed = True
    item.read_only = True
    item.visibility = "public"
    item.managed_source_kind = "test"
    item.managed_source_ref = "test:generated"
    await db.commit()
    scope = AgentManagementScope(user_id=human.id, agent_ids=frozenset())
    state = await item_sharing.sharing(item.id, scope)
    assert state.owner is None and state.level == "public" and not state.can_write
    assert not state.can_manage and state.options == []
    with pytest.raises(service.MemoryPermissionError):
        await level(item, scope, "private")
