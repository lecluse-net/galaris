"""Legacy Dataset adapter port. Dataset remains the sole data authority."""

from app.share import ShareGrant

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol
from uuid import UUID
from pathlib import Path

from core.user import HumanActor
from app.agent import AgentManagementScope
from .contracts import DatasetDocumentProjection


class DatasetCompatibility(Protocol):
    async def contains(self, identity: UUID) -> bool: ...
    async def adopt(self, identity: UUID) -> None: ...
    async def read(self, identity: UUID, actor: int | HumanActor, revision: int | None = None) -> dict[str, Any]: ...
    async def update(self, identity: UUID, actor: int | HumanActor, values: dict[str, Any]) -> None: ...
    async def grant(self, identity: UUID, actor: int | HumanActor, kind: str, principal: int, write: bool | None) -> None: ...
    async def history(self, identity: UUID, actor: int | HumanActor, limit: int, offset: int) -> dict[str, Any]: ...
    async def restore(self, identity: UUID, actor: int | HumanActor, number: int, expected_revision: int) -> None: ...
    async def budget(self, identity: UUID, user_id: int, size: int) -> None: ...
    async def sharing(self, identity: UUID, state: dict[str, Any]) -> None: ...
    async def remove(self, identity: UUID, actor: int | HumanActor) -> None: ...
    async def application(self, operation: str, actor: AgentManagementScope, context: dict[str, Any]) -> dict[str, Any]: ...
    async def attachments(self, identity: UUID, actor: int | HumanActor) -> list[dict[str, Any]]: ...
    async def read_attachment(self, identity: UUID, attachment_id: UUID, actor: int | HumanActor) -> tuple[dict[str, Any], bytes] | None: ...
    async def attachment_path(self, identity: UUID, attachment_id: UUID, actor: int | HumanActor) -> tuple[dict[str, Any], Path] | None: ...


_adapter: DatasetCompatibility | None = None
budget_reserved: ContextVar[bool] = ContextVar("dataset_budget_reserved", default=False)


@contextmanager
def reserved_budget():
    token = budget_reserved.set(True)
    try:
        yield
    finally:
        budget_reserved.reset(token)


def register_dataset_compatibility(adapter: DatasetCompatibility) -> None:
    global _adapter
    _adapter = adapter


def dataset_compatibility() -> DatasetCompatibility | None:
    return _adapter


async def legacy_dataset_access(identity: UUID, actor: int | HumanActor) -> bool:
    """Authorize adoption through Memory's current ACL before a Dataset exists."""
    from . import service
    from .access import effective_access

    item = await service.document_record(identity, revisions=False)
    return item is not None and (await effective_access(item, actor)).can_read


async def refresh_dataset_projection(identity: UUID, state: DatasetDocumentProjection | None) -> None:
    """Refresh legacy metadata/ACL projections; never write Dataset content here."""
    from sqlalchemy import delete, select
    from core.database import get_db
    from .models import MemoryItem

    item = await get_db().scalar(select(MemoryItem).where(MemoryItem.id == identity).with_for_update())
    if item is None or item.document_type != "dataset":
        return
    if state is None:
        item.soft_delete()
        await get_db().flush()
        return
    item.title, item.revision = state.title, state.revision
    item.lock_version = state.lock_version
    item.content_hash, item.size_bytes = state.content_hash, state.size_bytes
    item.owner_agent_id, item.owner_user_id = state.owner_agent_id, state.owner_user_id
    item.global_access, item.group_access = state.global_access, state.group_access
    item.visibility = "shared" if item.global_access or item.group_access else "private"
    item.read_only, item.keywords = state.read_only, list(state.keywords)
    item.metadata_ = {**state.metadata, "dataset_migrated": True, "dataset_uri": f"data://{identity}"}
    for model in (ShareGrant,):
        await get_db().execute(delete(model).where(ShareGrant.share_id == item.share_id))
    for grant in state.grants:
        if grant.agent_id is not None:
            get_db().add(ShareGrant(share_id=MemoryItem.share_for(identity), agent_id=grant.agent_id, can_write=grant.can_write))
        elif grant.user_id is not None:
            get_db().add(ShareGrant(share_id=MemoryItem.share_for(identity), user_id=grant.user_id, can_write=grant.can_write))
        else:
            get_db().add(ShareGrant(share_id=MemoryItem.share_for(identity), team_id=grant.team_id, can_write=grant.can_write))
    await get_db().flush()
    await get_db().refresh(item, attribute_names=["grants"])
