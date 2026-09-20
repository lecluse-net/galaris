"""Public contact-directory facade for other application domains."""

from __future__ import annotations

from .contracts import ReachableHumanContact


async def list_reachable_humans(
    *, agent_id: int, query: str = ""
) -> tuple[ReachableHumanContact, ...]:
    """Return human contacts reachable by an agent, already deduplicated."""

    from .service import list_reachable_humans as _list_reachable_humans

    return await _list_reachable_humans(agent_id=agent_id, query=query)


__all__ = ["list_reachable_humans"]
