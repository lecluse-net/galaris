"""Public contact-directory facade for other application domains."""

from __future__ import annotations

from uuid import UUID

from .contracts import ReachableHumanContact
from .discovery_contracts import ContactMergeCandidate as ContactMergeCandidate


async def read_contact_resource(contact_item_id: UUID, actor_agent_id: int) -> dict[str, object] | None:
    from .resources import read_contact_resource as read

    return await read(contact_item_id, actor_agent_id=actor_agent_id)


async def list_contact_resources(
    actor_agent_id: int, query: str = "", offset: int = 0, limit: int = 100,
) -> list[dict[str, object]]:
    from .resources import list_contact_resources as list_resources

    return await list_resources(actor_agent_id=actor_agent_id, query=query, offset=offset, limit=limit)


async def write_contact_resource(
    contact_item_id: UUID, actor_agent_id: int, content: bytes, expected_etag: str | None,
) -> dict[str, object]:
    from .resources import write_contact_resource as write

    return await write(contact_item_id, actor_agent_id=actor_agent_id, content=content, expected_etag=expected_etag)


def register_contact_runtime() -> None:
    from .discovery import register_contact_runtime as register
    register()


async def process_contact_discovery() -> int:
    from .discovery import process_contact_discovery as process
    return await process()


async def contact_merge_candidates(excluded: frozenset[str] = frozenset(), *, limit: int = 100) -> list[ContactMergeCandidate]:
    from .reconciliation import contact_merge_candidates as candidates
    return await candidates(excluded, limit=limit)


async def count_contact_merge_candidates(excluded: frozenset[str]) -> int:
    from .reconciliation import count_contact_merge_candidates as count
    return await count(excluded)


async def apply_contact_merge(candidate: ContactMergeCandidate) -> bool:
    from .reconciliation import apply_contact_merge as apply
    return await apply(candidate)


async def contact_merge_evidence(candidate: ContactMergeCandidate) -> list[dict[str, object]]:
    from .reconciliation import contact_merge_evidence as evidence
    return await evidence(candidate)


async def is_known_mail_contact(*, agent_id: int, address: str) -> bool:
    """Match an exact email identity in this agent's existing contact directory."""
    from app.memory import has_mail_contact

    return await has_mail_contact(owner_agent_id=agent_id, address=address)


async def list_reachable_humans(
    *, agent_id: int, query: str = ""
) -> tuple[ReachableHumanContact, ...]:
    """Return human contacts reachable by an agent, already deduplicated."""

    from .service import list_reachable_humans as _list_reachable_humans

    return await _list_reachable_humans(agent_id=agent_id, query=query)


__all__ = ["list_reachable_humans", "is_known_mail_contact", "ContactMergeCandidate",
           "list_contact_resources", "read_contact_resource", "write_contact_resource",
           "register_contact_runtime", "process_contact_discovery", "contact_merge_candidates",
           "apply_contact_merge", "contact_merge_evidence", "count_contact_merge_candidates"]
