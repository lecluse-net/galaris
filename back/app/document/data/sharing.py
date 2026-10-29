"""Dataset authorization around the shared policy service."""

from uuid import UUID
from app.share import SharingState, SharingUpdate, sharing_state, replace_sharing
from core.database import get_db
from .contracts import DataActor, DatasetConflictError
from .models import Dataset
from . import service
from .access import access
from .projection import changed


async def state(dataset: Dataset, actor: DataActor) -> SharingState:
    permissions = await access(dataset, actor)
    return await sharing_state(dataset.share_id, owner_agent_id=dataset.owner_agent_id,
        owner_user_id=dataset.owner_user_id, lock_version=dataset.lock_version,
        can_manage=permissions.can_manage and permissions.can_write and not dataset.read_only)


async def read(identity: UUID, actor: DataActor) -> SharingState:
    return await state(await service.record(identity, actor), actor)


async def update(identity: UUID, actor: DataActor, data: SharingUpdate) -> SharingState:
    if data.level == "private" and any(grant.kind == "team" for grant in data.grants):
        raise ValueError("Group sharing requires the groups level")
    if data.level == "groups" and not any(grant.kind == "team" for grant in data.grants):
        raise ValueError("Select at least one group")
    from .. import sharing_inheritance
    await sharing_inheritance.lock_sharing()
    dataset = await service.record(identity, actor, write=True, manage=True, lock=True)
    if dataset.lock_version != data.expected_lock_version:
        raise DatasetConflictError("Dataset sharing changed; reload before updating")
    current = await state(dataset, actor)
    data = await sharing_inheritance.replacement_intent(dataset, data, current)
    await sharing_inheritance.prepare_own_sharing(dataset)
    await replace_sharing(dataset.share_id, data, current)
    dataset.visibility = "shared" if data.level == "public" or data.grants else "private"
    dataset.lock_version += 1
    await sharing_inheritance.finish_own_sharing(dataset)
    await get_db().flush()
    await changed(dataset)
    return await state(dataset, actor)
