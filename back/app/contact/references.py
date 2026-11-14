"""Domain-owned references follow contact merges and forgetting transactionally."""

from collections.abc import Awaitable, Callable
from uuid import UUID

ContactReferenceHandler = Callable[[UUID, UUID | None], Awaitable[dict[str, int]]]
_handlers: dict[str, ContactReferenceHandler] = {}


def register_contact_reference_handler(name: str, handler: ContactReferenceHandler) -> None:
    _handlers[name] = handler


async def update_contact_references(source: UUID, target: UUID | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for handler in tuple(_handlers.values()):
        for key, count in (await handler(source, target)).items():
            if count:
                counts[key] = counts.get(key, 0) + count
    return counts
