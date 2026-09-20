"""Atomic sharing of memory items and documents, independent of Agent identity."""

from uuid import UUID
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import defer

from app.agent import Agent, AgentManagementScope, AgentTeamModel
from app.tools.contracts import current_tool_execution
from core.authorize import Privileges, check_privilege
from core.database import get_db
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel, get_user_record

from . import service
from .access import human_item_access, managed_item_agent_ids, owner_team_clause
from .models import DocumentTeamGrant, DocumentUserGrant, MemoryItem, MemoryItemGrant
from .schemas import DocumentCollaborator, DocumentSharing, DocumentSharingUpdate, DocumentSharingLevelUpdate


async def item_actor(document_id: UUID, scope: AgentManagementScope, *, write: bool = False) -> int | HumanActor:
    item = await service.item_record(document_id)
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    human = await human_item_access(item, scope.user_id)
    if human.can_write if write else human.can_read:
        return HumanActor(scope.user_id)
    readable, writable = await managed_item_agent_ids(item, scope.agent_ids)
    candidates = writable if write else readable
    if not candidates:
        raise service.MemoryNotFoundError("Document not found")
    return candidates[0]


async def can_manage(item: MemoryItem, scope: AgentManagementScope) -> bool:
    if item.source_managed or item.read_only:
        return False
    return (
        item.owner_user_id == scope.user_id or scope.allows(item.owner_agent_id)
        or await check_privilege(await get_user_record(scope.user_id), Privileges.MEMORY_ADMIN, get_db())
    )


async def sharing(document_id: UUID, scope: AgentManagementScope) -> DocumentSharing:
    await item_actor(document_id, scope)
    item = await service.item_record(document_id)
    assert item is not None
    manage = await can_manage(item, scope)
    return await _sharing_state(item, manage=manage)


async def _sharing_state(item: MemoryItem, *, manage: bool) -> DocumentSharing:
    # Agent.user_id is a human manager, not an Agent service account.
    agents = (await get_db().scalars(select(Agent).options(defer(Agent.avatar)).order_by(Agent.id))).all()
    agent_avatar_ids = set(await get_db().scalars(select(Agent.id).where(Agent.avatar.is_not(None))))
    users = (await get_db().scalars(select(UserModel).where(
        UserModel.is_active.is_(True),
    ).order_by(UserModel.id))).all()
    teams = (await get_db().scalars(select(TeamModel).order_by(TeamModel.order, TeamModel.id))).all()
    agent_groups: dict[int, list[int]] = {}
    for agent_id, team_id in (await get_db().execute(select(AgentTeamModel.agent_id, AgentTeamModel.team_id))).all():
        agent_groups.setdefault(agent_id, []).append(team_id)
    user_groups: dict[int, list[int]] = {}
    for user_id, team_id in (await get_db().execute(select(TeamUserModel.user_id, TeamUserModel.team_id))).all():
        user_groups.setdefault(user_id, []).append(team_id)
    catalog = [
        *[DocumentCollaborator(kind="agent", id=a.id, label=f"{a.first_name} {a.last_name}".strip() or a.code, group_ids=agent_groups.get(a.id, []), has_avatar=a.id in agent_avatar_ids) for a in agents if a.id != item.owner_agent_id],
        *[DocumentCollaborator(kind="user", id=u.id, label=u.display_name or u.email, group_ids=user_groups.get(u.id, []), avatar_url=u.avatar_url, has_avatar=u.avatar_url is not None) for u in users if u.id != item.owner_user_id],
        *[DocumentCollaborator(kind="team", id=t.id, label=t.name) for t in teams],
    ]
    grants: dict[tuple[Literal["agent", "user", "team"], int], bool] = {("agent", g.agent_id): g.can_write for g in item.grants}
    grants.update({("user", g.user_id): g.can_write for g in (await get_db().scalars(select(DocumentUserGrant).where(DocumentUserGrant.item_id == item.id))).all()})
    grants.update({("team", g.team_id): g.can_write for g in (await get_db().scalars(select(DocumentTeamGrant).where(DocumentTeamGrant.item_id == item.id))).all()})
    owner_groups = set(await get_db().scalars(select(TeamModel.id).where(owner_team_clause(
        TeamModel.id, owner_agent_id=item.owner_agent_id, owner_user_id=item.owner_user_id,
    ))))
    # Present legacy owner-relative access as explicit groups. The next save
    # freezes this selection, while membership within each group stays dynamic.
    if item.group_access:
        for team_id in owner_groups:
            grants[("team", team_id)] = grants.get(("team", team_id), False) or item.group_access == 2
    if item.owner_agent_id is not None:
        agent_owner = next((a for a in agents if a.id == item.owner_agent_id), None)
        owner = DocumentCollaborator(kind="agent", id=item.owner_agent_id,
            label=(f"{agent_owner.first_name} {agent_owner.last_name}".strip() or agent_owner.code) if agent_owner else f"#{item.owner_agent_id}")
    elif item.owner_user_id is not None:
        human_owner = next((u for u in users if u.id == item.owner_user_id), None)
        owner = DocumentCollaborator(kind="user", id=item.owner_user_id,
            label=(human_owner.display_name or human_owner.email) if human_owner else f"#{item.owner_user_id}")
    else:
        owner = None
    return DocumentSharing(
        lock_version=item.lock_version, can_manage=manage,
        level="public" if item.global_access or item.visibility == "public" else "groups" if any(kind == "team" for kind, _ in grants) else "private",
        can_write=item.global_access == 2,
        owner=owner,
        owner_groups=[o for o in catalog if o.kind == "team" and o.id in owner_groups],
        grants=[next((o for o in catalog if (o.kind, o.id) == (kind, target_id)), DocumentCollaborator(kind=kind, id=target_id, label=f"#{target_id}")).model_copy(update={"can_write": write}) for (kind, target_id), write in grants.items()],
        # The generic picker uses memberships to hide direct and inherited access.
        # Keep the complete catalog for atomic replacement and level changes.
        options=catalog if manage else [],
    )


async def update_level(document_id: UUID, data: DocumentSharingLevelUpdate, scope: AgentManagementScope) -> DocumentSharing:
    item = await _editable_sharing(document_id, data.expected_lock_version, scope)
    recipients = {(grant.kind, grant.id): grant for grant in data.grants}
    if len(recipients) != len(data.grants):
        raise ValueError("Duplicate document collaborators")
    has_teams = any(kind == "team" for kind, _ in recipients)
    if data.level == "groups" and not has_teams:
        raise ValueError("Select at least one group")
    if data.level == "private" and has_teams:
        raise ValueError("Group sharing requires the groups level")
    # Validate the complete selection before replacing anything. One lock,
    # transaction and version cover the entire sharing form.
    current = await sharing(document_id, scope)
    available = {(option.kind, option.id) for option in current.options}
    existing = {(grant.kind, grant.id) for grant in current.grants}
    if any(key not in available and key not in existing for key in recipients):
        raise service.MemoryNotFoundError("Collaborator not found")
    for model in (MemoryItemGrant, DocumentUserGrant, DocumentTeamGrant):
        await get_db().execute(delete(model).where(model.item_id == item.id))
    for grant in recipients.values():
        if grant.kind == "agent":
            get_db().add(MemoryItemGrant(item_id=item.id, agent_id=grant.id, can_write=grant.can_write))
        elif grant.kind == "user":
            get_db().add(DocumentUserGrant(item_id=item.id, user_id=grant.id, can_write=grant.can_write))
        else:
            get_db().add(DocumentTeamGrant(item_id=item.id, team_id=grant.id, can_write=grant.can_write))
    value = 2 if data.can_write else 1
    item.global_access = value if data.level == "public" else 0
    item.group_access = 0
    item.visibility = "shared" if item.global_access or recipients else "private"
    item.lock_version += 1
    await service.commit_item_sharing(item)
    return await sharing(document_id, scope)


async def _editable_sharing(document_id: UUID, expected: int, scope: AgentManagementScope) -> MemoryItem:
    # Serialize edits to the same document, including concurrent first-time grants.
    await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == document_id).with_for_update())
    item = await service.item_record(document_id)
    if item is None or not await can_manage(item, scope):
        raise service.MemoryPermissionError("Only the owner can manage sharing")
    await item_actor(document_id, scope, write=True)
    if item.lock_version != expected:
        raise service.MemoryConflictError("Document sharing changed; reload and retry")
    return item


async def update_sharing(document_id: UUID, data: DocumentSharingUpdate, scope: AgentManagementScope) -> DocumentSharing:
    item = await _editable_sharing(document_id, data.expected_lock_version, scope)
    await _update_grant(item, data)
    return await sharing(document_id, scope)


async def _update_grant(item: MemoryItem, data: DocumentSharingUpdate) -> None:
    if data.kind == "agent":
        target = await get_db().scalar(select(Agent.id).where(Agent.id == data.id))
        if data.id == item.owner_agent_id:
            raise ValueError("The owner already has access")
        model, field = MemoryItemGrant, MemoryItemGrant.agent_id
    elif data.kind == "user":
        target = await get_db().scalar(select(UserModel.id).where(UserModel.id == data.id, UserModel.is_active.is_(True)))
        if data.id == item.owner_user_id:
            raise ValueError("The owner already has access")
        model, field = DocumentUserGrant, DocumentUserGrant.user_id
    else:
        target = await get_db().scalar(select(TeamModel.id).where(TeamModel.id == data.id))
        model, field = DocumentTeamGrant, DocumentTeamGrant.team_id
    if target is None and data.can_write is not None:
        raise service.MemoryNotFoundError("Collaborator not found")
    grant = await get_db().scalar(select(model).where(model.item_id == item.id, field == data.id))
    if data.can_write is None:
        if grant is not None:
            await get_db().delete(grant)
    elif grant is not None:
        grant.can_write = data.can_write
    else:
        grant = model(item_id=item.id, can_write=data.can_write)
        setattr(grant, field.key, data.id)
        get_db().add(grant)
    await get_db().flush()
    if item.visibility != "public":
        item.visibility = "shared" if item.global_access or item.group_access or await service.has_document_grants(item.id) else "private"
    item.lock_version += 1
    await service.commit_item_sharing(item)


async def agent_sharing(item_id: UUID, *, agent_id: int) -> DocumentSharing:
    """Let an agent inspect its own recipients without impersonating its human manager."""
    item = await service.item_record(item_id)
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    if item.owner_agent_id != agent_id:
        raise service.MemoryPermissionError("Only the owner can manage sharing")
    return await _sharing_state(item, manage=not item.read_only and not item.source_managed)


async def update_agent_sharing(
    item_id: UUID, *, agent_id: int, kind: Literal["agent", "user", "team"],
    target_id: int, access: Literal["read", "edit", "none"],
    expected_lock_version: int | None = None, document_only: bool = False,
) -> DocumentSharing:
    """Update one explicit grant atomically; edits do not grant the right to reshare."""
    await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id == item_id).with_for_update())
    item = await service.item_record(item_id)
    if item is None:
        raise service.MemoryNotFoundError("Memory not found")
    if document_only and item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")
    if item.owner_agent_id != agent_id or item.read_only or item.source_managed:
        raise service.MemoryPermissionError("Only the owner of an editable item can manage sharing")
    if expected_lock_version is not None and item.lock_version != expected_lock_version:
        # This check precedes every grant mutation. A stale version (including one
        # invalidated by a content edit) is safe for the model to reload and retry.
        # Do not infer this evidence from a later exception: commit or notification
        # failures can occur after the sharing has already taken effect.
        execution = current_tool_execution()
        if execution is not None:
            execution.outcome = "rejected"
        raise service.MemoryConflictError(
            "Sharing changed; call memory_sharing again for the current lock_version, then retry"
        )
    data = DocumentSharingUpdate(
        kind=kind, id=target_id,
        can_write=None if access == "none" else access == "edit",
        expected_lock_version=item.lock_version,
    )
    await _update_grant(item, data)
    return await agent_sharing(item_id, agent_id=agent_id)
