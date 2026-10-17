"""Process authorization around the shared policy service."""

from app.agent import AgentManagementScope
from app.share import SharingState, SharingUpdate, sharing_directory, sharing_state, replace_sharing, set_grant
from core.database import get_db
from sqlalchemy import select

from .models import ProcessDefinition
from .native_access import ProcessActor, accessible_clause
from .native_definitions import DefinitionConflictError, get


async def preview(scope: AgentManagementScope, *, owner_agent_id: int | None) -> SharingState:
    if owner_agent_id is not None:
        scope.require(owner_agent_id)
    return await sharing_directory(owner_agent_id=owner_agent_id, owner_user_id=scope.user_id if owner_agent_id is None else None)


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
