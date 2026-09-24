"""Galaris harness facade and internal Pydantic AI implementation.

Runtime bridges contribute operational supervision through this package's public facade;
the UI and other application domains never call a concrete runtime manager directly.
"""

from app.skill import register_learned_skill_runtime_refresher

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
    from app.agent import request_skill_sync

    await request_skill_sync(agent_id)


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
