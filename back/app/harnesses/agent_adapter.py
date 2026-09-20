"""Adapter registering Harness persistence behind the ``app.agent`` port."""

from __future__ import annotations

from typing import Any

from app.agent import ConfiguredHarnessSelection, HarnessExecutionPolicy, register_harness_selection_port

from .service import resolve_target
from .registry import get_provider


class HarnessSelectionAdapter:
    async def configuration(self, provider_code: str) -> tuple[HarnessExecutionPolicy, int]:
        from .configuration import read_policy

        return await read_policy(provider_code)

    async def resolve(self, agent: Any) -> ConfiguredHarnessSelection | None:
        target = await resolve_target(agent)
        if target is None:
            return None
        return ConfiguredHarnessSelection(
            id=target.id,
            name=target.name,
            provider_code=target.provider_code,
            driver_code=target.driver_code,
            revision=target.revision,
            status=target.status,
            max_parallel_tasks=target.max_parallel_tasks,
            model=target.model,
            capabilities=frozenset(target.capabilities),
            pipeline_policy=get_provider(target.provider_code).pipeline_policy,
            metadata=dict(target.metadata),
        )


adapter = HarnessSelectionAdapter()
register_harness_selection_port(adapter)

__all__ = ["HarnessSelectionAdapter", "adapter"]
