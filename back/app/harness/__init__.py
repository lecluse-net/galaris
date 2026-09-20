"""Galaris harness facade and internal Pydantic AI implementation.

Runtime bridges contribute operational supervision through this package's public facade;
the UI and other application domains never call a concrete runtime manager directly.
"""

from loguru import logger

from app.agent import get_agent_record
from app.skill import register_learned_skill_runtime_refresher, skill_service

from .contracts import HarnessAction, HarnessCapability, HarnessSupervisor
from .facade import (
    HarnessSupervisorNotFoundError,
    UnsupportedHarnessCapabilityError,
    capabilities,
    logs,
    refresh,
    register_harness_supervisor,
    run_action,
    status,
    supervisor_for,
)


async def _refresh_learned_skill_projection(agent_id: int) -> None:
    agent = await get_agent_record(agent_id)
    if agent is None or not skill_service.runtime_requires_skill_sync(agent.agent_driver):
        return
    try:
        await refresh(agent)
    except Exception:
        logger.exception(
            "Learned skill runtime refresh failed for agent {}",
            agent_id,
        )


register_learned_skill_runtime_refresher(_refresh_learned_skill_projection)

__all__ = [
    "HarnessAction",
    "HarnessCapability",
    "HarnessSupervisor",
    "HarnessSupervisorNotFoundError",
    "UnsupportedHarnessCapabilityError",
    "capabilities",
    "logs",
    "refresh",
    "register_harness_supervisor",
    "run_action",
    "status",
    "supervisor_for",
]
