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
    dataset = await service.record(identity, actor, write=True, manage=True, lock=True)
    if dataset.lock_version != data.expected_lock_version:
        raise DatasetConflictError("Dataset sharing changed; reload before updating")
    await replace_sharing(dataset.share_id, data, await state(dataset, actor))
    dataset.lock_version += 1
    await get_db().flush()
    await changed(dataset)
    return await state(dataset, actor)
