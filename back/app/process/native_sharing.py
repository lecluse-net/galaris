"""Process authorization around the shared policy service."""

from typing import Literal

from app.agent import AgentManagementScope
from app.share import Collaborator, SharingState, SharingUpdate, sharing_directory, sharing_state, replace_sharing, set_grant
from core.authorize import privilege_clause
from core.database import get_db
from sqlalchemy import select

from .models import ProcessDefinition
from .native_access import ProcessActor, accessible_clause
from .native_definitions import DefinitionConflictError, get


async def owner_options(scope: AgentManagementScope) -> list[Collaborator]:
    directory = await sharing_directory(owner_agent_id=None, owner_user_id=scope.user_id)
    administrator = bool(await get_db().scalar(select(privilege_clause(scope.user_id, "PROCESS_ADMIN"))))
    return [principal for principal in [*([directory.owner] if directory.owner else []), *directory.options]
        if (principal.kind == "agent" and scope.allows(principal.id)) or
        (principal.kind == "user" and (principal.id == scope.user_id or administrator))]


async def require_owner(scope: AgentManagementScope, kind: Literal["agent", "user"], principal: int) -> None:
    if not any(option.kind == kind and option.id == principal for option in await owner_options(scope)):
        raise PermissionError("Process owner is outside the current management scope")


async def preview(scope: AgentManagementScope, *, owner_agent_id: int | None, owner_user_id: int | None = None) -> SharingState:
    if owner_agent_id is not None:
        scope.require(owner_agent_id)
    user = (owner_user_id or scope.user_id) if owner_agent_id is None else None
    if user is not None and user != scope.user_id:
        await require_owner(scope, "user", user)
    return await sharing_directory(owner_agent_id=owner_agent_id, owner_user_id=user)


async def transfer_owner(code: str, actor: AgentManagementScope, *, kind: Literal["agent", "user"], principal: int,
                         expected_lock_version: int) -> dict[str, object]:
    from .native_definitions import read

    record, _ = await get(code, actor, write=True, lock=True)
    if not await get_db().scalar(select(ProcessDefinition.id).where(
        ProcessDefinition.id == record.id, accessible_clause(actor, manage=True))):
        raise PermissionError("Only the Process owner can transfer ownership")
    if record.lock_version != expected_lock_version:
        raise DefinitionConflictError("Process changed; reload before transferring ownership")
    await require_owner(actor, kind, principal)
    previous_kind: Literal["agent", "user"] = "agent" if record.agent_id is not None else "user"
    previous = record.agent_id if record.agent_id is not None else record.owner_user_id
    if (previous_kind, previous) != (kind, principal):
        if previous is not None:
            await set_grant(record.share_id, previous_kind, previous, True)
        record.agent_id = principal if kind == "agent" else None
        record.owner_user_id = principal if kind == "user" else None
        await set_grant(record.share_id, kind, principal, None)
        record.lock_version += 1
        await get_db().commit()
    return await read(code, actor)


async def state(record: ProcessDefinition, actor: ProcessActor) -> SharingState:
    manage = bool(await get_db().scalar(select(ProcessDefinition.id).where(ProcessDefinition.id == record.id,
        accessible_clause(actor, manage=True))))
    return await sharing_state(record.share_id, owner_agent_id=record.agent_id, owner_user_id=record.owner_user_id,
        can_manage=manage, lock_version=record.lock_version)


async def read(code: str, actor: ProcessActor) -> SharingState:
    record, _ = await get(code, actor)
    return await state(record, actor)


async def update(code: str, actor: ProcessActor, data: SharingUpdate) -> SharingState:
    record, _ = await get(code, actor, write=True, lock=True)
    if record.lock_version != data.expected_lock_version:
        raise DefinitionConflictError("Process sharing changed; reload before updating")
    await replace_sharing(record.share_id, data, await state(record, actor))
    record.lock_version += 1
    await get_db().commit()
    return await state(record, actor)


async def grant_agent(code: str, owner: int, target: int, *, can_write: bool = False, revoke: bool = False) -> dict[str, object]:
    record, _ = await get(code, owner, write=True, lock=True)
    current = await state(record, owner)
    if not current.can_manage:
        raise PermissionError("Only the Process owner can share its definition")
    if not any(p.kind == "agent" and p.id == target for p in current.options):
        raise LookupError("Agent not found")
    await set_grant(record.share_id, "agent", target, None if revoke else can_write)
    record.lock_version += 1
    await get_db().commit()
    return {"process_code": code, "agent_id": target, "can_write": can_write, "revoked": revoke}
