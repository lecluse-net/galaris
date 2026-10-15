"""The Document sharing contract applied atomically to Dataset-owned grants."""

from typing import Literal
from uuid import UUID
from sqlalchemy import delete, select

from app.memory import DocumentCollaborator, DocumentSharing, DocumentSharingLevelUpdate, resource_sharing_directory
from core.database import get_db

from .contracts import DataActor, DatasetConflictError, DatasetNotFoundError, DatasetPermissionError
from .models import Dataset, DatasetGrant
from . import service
from .access import access
from .projection import changed


async def state(dataset: Dataset, actor: DataActor) -> DocumentSharing:
    permissions = await access(dataset, actor)
    directory = await resource_sharing_directory(owner_agent_id=dataset.owner_agent_id, owner_user_id=dataset.owner_user_id)
    catalog = {(entry.kind, entry.id): entry for entry in directory.options}
    grants: dict[tuple[Literal["agent", "user", "team"], int], DocumentCollaborator] = {}
    for grant in await get_db().scalars(select(DatasetGrant).where(DatasetGrant.dataset_id == dataset.id)):
        kind: Literal["agent", "user", "team"]
        principal: int
        if grant.agent_id is not None:
            kind, principal = "agent", grant.agent_id
        elif grant.user_id is not None:
            kind, principal = "user", grant.user_id
        else:
            assert grant.team_id is not None
            kind, principal = "team", grant.team_id
        recipient = catalog.get((kind, principal), DocumentCollaborator(kind=kind, id=principal, label=f"#{principal}"))
        grants[(recipient.kind, recipient.id)] = recipient.model_copy(update={"can_write": grant.can_write})
    if dataset.group_access:
        for team in directory.owner_groups:
            previous = grants.get((team.kind, team.id))
            grants[(team.kind, team.id)] = team.model_copy(update={"can_write": dataset.group_access == 2 or bool(previous and previous.can_write)})
    manage = permissions.can_manage and permissions.can_write and not dataset.read_only
    return directory.model_copy(update={"lock_version": dataset.lock_version, "can_manage": manage,
        "options": directory.options if manage else [], "grants": list(grants.values()),
        "level": "public" if dataset.global_access else "groups" if any(kind == "team" for kind, _ in grants) else "private",
        "can_write": dataset.global_access == 2})


async def read(identity: UUID, actor: DataActor) -> DocumentSharing:
    return await state(await service.record(identity, actor), actor)


async def update(identity: UUID, actor: DataActor, data: DocumentSharingLevelUpdate) -> DocumentSharing:
    dataset = await service.record(identity, actor, write=True, manage=True, lock=True)
    if dataset.lock_version != data.expected_lock_version:
        raise DatasetConflictError("Dataset sharing changed; reload before updating")
    current = await state(dataset, actor)
    if not current.can_manage:
        raise DatasetPermissionError("Only the owner of an editable Dataset can manage sharing")
    recipients = {(grant.kind, grant.id): grant for grant in data.grants}
    if len(recipients) != len(data.grants):
        raise ValueError("Duplicate collaborators")
    has_groups = any(kind == "team" for kind, _ in recipients)
    if data.level == "groups" and not has_groups:
        raise ValueError("Select at least one group")
    if data.level == "private" and has_groups:
        raise ValueError("Group sharing requires the groups level")
    available = {(entry.kind, entry.id) for entry in [*current.options, *current.grants]}
    if set(recipients) - available:
        raise DatasetNotFoundError("Collaborator not found")
    await get_db().execute(delete(DatasetGrant).where(DatasetGrant.dataset_id == identity))
    for grant in recipients.values():
        get_db().add(DatasetGrant(dataset_id=identity, can_write=grant.can_write, **{grant.kind + "_id": grant.id}))
    dataset.global_access = (2 if data.can_write else 1) if data.level == "public" else 0
    dataset.group_access = 0
    dataset.lock_version += 1
    await get_db().flush()
    await changed(dataset)
    return await state(dataset, actor)
