"""Native personal-memory storage references; document storage is independently registered."""
from collections.abc import Collection
from sqlalchemy import select, union
from core.database import get_db
from core.storage import register_resource_content
from .inline_content import read_inline_content
from .models import MemoryItem, MemoryRevision


async def resource_referenced(provider: str, pointer: str) -> bool:
    return pointer in await referenced_resources(provider, (pointer,))


async def referenced_resources(provider: str, pointers: Collection[str]) -> set[str]:
    return set(await get_db().scalars(union(
        select(MemoryItem.memory_resource_id).where(MemoryItem.memory_provider_code==provider, MemoryItem.memory_resource_id.in_(pointers)),
        select(MemoryRevision.resource_id).where(MemoryRevision.provider_code==provider, MemoryRevision.resource_id.in_(pointers)),
    ).execution_options(include_historized=True)))


def register_content() -> None:
    register_resource_content("memory",read_inline_content,resource_referenced,referenced_batch=referenced_resources)
