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
