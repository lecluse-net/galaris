"""Public contact-directory facade for other application domains."""

from __future__ import annotations

from .contracts import ReachableHumanContact


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


__all__ = ["list_reachable_humans", "is_known_mail_contact"]
