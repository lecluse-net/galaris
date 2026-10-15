"""Domain-owned usage queries, composed without importing consumer internals."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID
from sqlalchemy import select
from app.agent import AgentManagementScope
from core.database import get_db
from .models import DatasetAlias
from . import service

UsageSource = Callable[[tuple[str, ...], AgentManagementScope, int, int], Awaitable[dict[str, Any]]]
_sources: dict[str, dict[str, UsageSource]] = {}


def register_dataset_usage_source(kind: str, name: str, source: UsageSource) -> None:
    _sources.setdefault(kind, {})[name] = source


async def list_usages(identity: UUID, actor: AgentManagementScope, *, kind: str,
    page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await service.record(identity, actor)
    aliases = await get_db().scalars(select(DatasetAlias.legacy_document_id).where(DatasetAlias.dataset_id == identity))
    uris = (f"data://{identity}", *(f"document://{alias}" for alias in aliases))
    offset, remaining, total = (page - 1) * page_size, page_size, 0
    items: list[dict[str, Any]] = []
    for source in _sources.get(kind, {}).values():
        count = int((await source(uris, actor, 0, 0))["total"])
        total += count
        if offset >= count:
            offset -= count
        elif remaining:
            result = await source(uris, actor, offset, remaining)
            items.extend(result["items"])
            remaining -= len(result["items"])
            offset = 0
    return {"items": items, "total": total, "kind": kind}
