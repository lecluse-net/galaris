"""Adapter registering Harness persistence behind the ``app.agent`` port."""

from __future__ import annotations

from typing import Any
from collections.abc import Collection

from app.agent import AgentRunRequest, ConfiguredHarnessSelection, HarnessExecutionPolicy, register_harness_selection_port

from .service import resolve_target
from .registry import get_provider


class HarnessSelectionAdapter:
    async def projected_skill_agent_ids(self, agent_ids: Collection[int] | None = None) -> list[int]:
        from .skill_sync import projected_skill_agent_ids

        return await projected_skill_agent_ids(agent_ids)

    async def request_skill_sync(self, agent_id: int) -> None:
        from .skill_sync import request_skill_sync

        await request_skill_sync(agent_id)

    async def prepare_execution(self, request: AgentRunRequest) -> None:
        from .skill_sync import prepare_skill_execution

        await prepare_skill_execution(request)

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
