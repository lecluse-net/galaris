"""Messaging identity directory.

AI identities derive from the remote-account parameter declared by each bridge. Application
services are imported lazily to prevent import cycles.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.messenger._observations import ObservedMessengerMessage, ObservedMessengerUser


async def _identity_param_for(tool_id: int) -> str | None:
    from app.tools import tool_service

    from . import facade

    tool = await tool_service.get_tool_by_id(tool_id)
    if tool is None:
        return None
    kind = facade.kind_for_tool(tool)
    spec = facade.get_spec(kind) if kind is not None else None
    canonical_name = spec.identity_param if spec is not None else "user_id"
    if not canonical_name:
        return None
    messenger = tool.messenger
    if messenger is not None:
        return messenger.param_map.get(canonical_name) or canonical_name
    return canonical_name


async def _agent_for(
    tool_id: int,
    platform_user_id: str,
    *,
    identity_param: str | None = None,
) -> Optional[int]:
    from app.connection import connection_service

    param_name = identity_param or await _identity_param_for(tool_id)
    if not param_name:
        return None
    agent_ids = await connection_service.find_agents_by_param(
        tool_id=tool_id,
        param_name=param_name,
        param_value=platform_user_id,
    )
    unique_agent_ids = list(dict.fromkeys(agent_ids))
    return unique_agent_ids[0] if len(unique_agent_ids) == 1 else None


async def resolve_agent_ids(
    tool_id: int,
    platform_user_ids: Iterable[str],
) -> dict[str, int]:
    """Resolve distinct remote account IDs to configured agents for one Tool."""

    identity_param = await _identity_param_for(tool_id)
    if not identity_param:
        return {}
    resolved: dict[str, int] = {}
    for platform_user_id in dict.fromkeys(platform_user_ids):
        if not platform_user_id:
            continue
        agent_id = await _agent_for(
            tool_id,
            platform_user_id,
            identity_param=identity_param,
        )
        if agent_id is not None:
            resolved[platform_user_id] = agent_id
    return resolved


async def resolve_user(tool_id: int, platform_user_id: str) -> ObservedMessengerUser:
    """Build a canonical user enriched with an AI agent identity when available."""
    agent_id = await _agent_for(tool_id, platform_user_id)
    return ObservedMessengerUser(id=platform_user_id, agent_id=agent_id, tool_id=tool_id)


async def enrich_ai_identity(tool_id: int, messages: Iterable[ObservedMessengerMessage]) -> None:
    """Resolve and assign ``sender.agent_id`` on each message in place.

    Bridges only know native sender identifiers. This function maps them to configured agent
    connections and caches repeated identifiers for the current batch.
    """
    identity_param = await _identity_param_for(tool_id)
    cache: dict[str, Optional[int]] = {}
    for msg in messages:
        sender = msg.sender
        if sender is None or not sender.id or sender.agent_id is not None:
            continue
        if sender.id not in cache:
            cache[sender.id] = await _agent_for(
                tool_id,
                sender.id,
                identity_param=identity_param,
            )
        sender.agent_id = cache[sender.id]
        sender.is_ai = sender.agent_id is not None
