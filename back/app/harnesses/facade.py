"""Stable public facade for Harness execution and management."""

from __future__ import annotations

from uuid import UUID

from app.agent import Agent

from .contracts import HarnessCredentials, HarnessTarget
from .service import execution_credentials, resolve_target


async def resolve_agent_harness(agent: Agent) -> HarnessTarget | None:
    """Resolve the one effective Harness; ``None`` means the internal runtime."""

    return await resolve_target(agent)


async def get_private_execution_credentials(harness_id: UUID) -> HarnessCredentials:
    """Private in-process executor surface, intentionally absent from API schemas."""

    return await execution_credentials(harness_id)


__all__ = ["get_private_execution_credentials", "resolve_agent_harness"]


async def list_admin_harness_options() -> list[dict[str, object]]:
    from .service import list_catalogue
    return [{"id": str(h.id), "name": h.name, "provider_code": h.provider_code,
             "driver_code": h.driver_code, "enabled": h.enabled}
            for h in await list_catalogue(enabled_only=True)]


async def get_admin_harness(agent_id: int) -> dict[str, object]:
    from .service import get_for_agent
    selected = await get_for_agent(agent_id)
    return {"agent_id": agent_id, "id": str(selected.id) if selected.id else None,
            "harness_id": str(selected.harness_id) if selected.harness_id else None,
            "internal": selected.internal, "name": selected.name, "provider_code": selected.provider_code,
            "driver_code": selected.driver_code, "model": selected.model,
            "lifecycle_status": selected.lifecycle_status, "revision": selected.revision,
            "capabilities": selected.capabilities}
