"""Human ownership transfers, with the same live ACLs as Dataset sharing."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.agent import AgentManagementScope
from app.share import Collaborator, set_grant, sharing_directory
from core.database import get_db

from . import service
from .access import access, is_administrator
from .models import Dataset
from .projection import changed


class OwnerOptions(BaseModel):
    owner: Collaborator | None
    options: list[Collaborator]
    current_user_id: int


async def options(identity: UUID, actor: AgentManagementScope) -> OwnerOptions:
    dataset = await service.record(identity, actor)
    directory = await sharing_directory(owner_agent_id=dataset.owner_agent_id, owner_user_id=dataset.owner_user_id)
    permissions = await access(dataset, actor)
    choices: list[Collaborator] = []
    if permissions.can_manage and permissions.can_write:
        administrator = await is_administrator(actor)
        for principal in [*directory.options, *([directory.owner] if directory.owner else [])]:
            if (principal.kind == "agent" and actor.allows(principal.id)) or (
                principal.kind == "user" and (principal.id == actor.user_id or administrator)
            ):
                choices.append(principal)
    return OwnerOptions(owner=directory.owner, options=choices, current_user_id=actor.user_id)


async def transfer(identity: UUID, actor: AgentManagementScope, *, kind: Literal["agent", "user"],
                   principal: int, expected_lock_version: int) -> Dataset:
    dataset = await service.record(identity, actor, write=True, manage=True, lock=True)
    if dataset.lock_version != expected_lock_version:
        raise service.DatasetConflictError("Dataset changed; reload before transferring ownership")
    choices = await options(identity, actor)
    if not any(option.kind == kind and option.id == principal for option in choices.options):
        raise service.DatasetPermissionError("Dataset owner is outside the current management scope")
    previous_kind: Literal["agent", "user"] = "agent" if dataset.owner_agent_id is not None else "user"
    previous = dataset.owner_agent_id if previous_kind == "agent" else dataset.owner_user_id
    if (previous_kind, previous) == (kind, principal):
        return dataset
    # The former owner remains an editor, as with a Document transfer.
    if previous is not None:
        await set_grant(dataset.share_id, previous_kind, previous, True)
    dataset.owner_agent_id = principal if kind == "agent" else None
    dataset.owner_user_id = principal if kind == "user" else None
    await set_grant(dataset.share_id, kind, principal, None)
    dataset.lock_version += 1
    await get_db().flush()
    await changed(dataset)
    return dataset
