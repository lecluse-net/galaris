"""Canonical URL associations; caller owns transactions and access checks."""

from uuid import UUID
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from core.database import get_db

from .models import MemoryItem, MemoryURL

_url_reference_mergers: dict[str, Callable[[UUID, UUID], Awaitable[None]]] = {}


def register_url_reference_merger(key: str, merger: Callable[[UUID, UUID], Awaitable[None]]) -> None:
    """Let source owners preserve their references when equal URLs coalesce."""
    _url_reference_mergers[key] = merger


async def associate_memory_url(node_id: UUID, url: str) -> MemoryURL:
    if not url.strip():
        raise ValueError("A Memory URL cannot be empty")
    db = get_db()
    # Serialize association creation for this node, including repeated encounters.
    node = await db.scalar(select(MemoryItem).where(MemoryItem.id == node_id).with_for_update())
    if node is None:
        raise ValueError("Memory node does not exist")
    location = await db.scalar(select(MemoryURL).where(
        MemoryURL.memory_node_id == node_id, MemoryURL.url == url,
    ).order_by(MemoryURL.id).limit(1))
    if location is None:
        location = MemoryURL(memory_node_id=node_id, url=url)
        node.url_relations.append(location)
        await db.flush()
    if node.primary_url is None:
        node.primary_url = url
    return location


async def memory_urls(node_id: UUID) -> list[str]:
    return list(await get_db().scalars(select(MemoryURL.url).where(
        MemoryURL.memory_node_id == node_id,
    ).distinct().order_by(MemoryURL.url)))


async def transfer_memory_urls(duplicate: MemoryItem, canonical: MemoryItem) -> None:
    db = get_db()
    locations = {location.url: location for location in canonical.url_relations}
    for location in list(duplicate.url_relations):
        existing = locations.get(location.url)
        if existing is not None:
            for merger in _url_reference_mergers.values():
                await merger(location.id, existing.id)
            await db.delete(location)
        else:
            duplicate.url_relations.remove(location)
            canonical.url_relations.append(location)
            location.memory_node_id = canonical.id
            locations[location.url] = location
    if canonical.primary_url is None:
        canonical.primary_url = duplicate.primary_url
    duplicate.primary_url = None
    await db.flush()
