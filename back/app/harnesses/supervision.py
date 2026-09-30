"""Shared HTTP/MCP runtime inspection and action validation."""

from app.agent import Agent, get_agent_record
from . import service
from .configuration import configured_provider_capabilities
from .registry import get_provider
from .contracts import HarnessAction, HarnessTarget, HarnessProvider
from .schemas import HarnessRuntimeState, HarnessLogs
from .skill_sync import skill_sync_status


async def selected(agent_id: int) -> tuple[Agent, HarnessTarget, HarnessProvider]:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise LookupError("Agent not found")
    target = await service.resolve_target(agent)
    if target is None:
        raise service.HarnessConflictError("The internal Harness has no external runtime to supervise")
    return agent, target, get_provider(target.provider_code)


async def status(agent_id: int) -> HarnessRuntimeState:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise LookupError("Agent not found")
    target = await service.resolve_target(agent)
    if target is None:
        return HarnessRuntimeState(status="internal", lifecycle_status="internal", managed=False, capabilities=[])
    provider = get_provider(target.provider_code)
    skills_status, skills_error = await skill_sync_status(agent_id)
    capabilities = sorted(await configured_provider_capabilities(target.provider_code))
    observed = await provider.status(agent) if target.status == "ready" and "status" in capabilities else target.status
    return HarnessRuntimeState(status=observed, lifecycle_status=target.status, managed=provider.containerized,
                               capabilities=capabilities, last_error=target.last_error or skills_error, skills_status=skills_status)


async def validate_action(agent_id: int, action: HarnessAction) -> None:
    state = await status(agent_id)
    if action not in state.available_actions:
        raise service.HarnessConflictError("This action is not available for the current runtime state")


async def logs(agent_id: int, lines: int) -> HarnessLogs:
    if not 1 <= lines <= 5000:
        raise ValueError("Log lines must be between 1 and 5000")
    agent, target, provider = await selected(agent_id)
    if "logs" not in await configured_provider_capabilities(target.provider_code):
        raise service.HarnessConflictError("This Harness does not expose logs")
    if target.status != "ready":
        return HarnessLogs(lines=[target.last_error] if target.last_error else [])
    return HarnessLogs(lines=(await provider.logs(agent, lines))[:lines])
