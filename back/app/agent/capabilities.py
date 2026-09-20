"""One capability vocabulary and restrictive negotiation for every driver/provider."""

from collections.abc import Iterable
from typing import cast, get_args

from .contracts import (
    AgentDriverSpec, HarnessCapability, HarnessCapabilityDescriptor, HarnessExecutionPolicy,
    CONFIGURABLE_HARNESS_CAPABILITIES, ToolExposureProfile,
)

CAPABILITIES = frozenset(get_args(HarnessCapability))
MANAGEMENT_CAPABILITIES = frozenset({"status", "start", "stop", "restart", "update", "logs", "refresh"})


def normalize_capabilities(values: Iterable[str]) -> frozenset[HarnessCapability]:
    # Read historical persisted records; only the canonical spelling is ever emitted.
    normalized = {"streaming" if value == "stream" else value for value in values}
    unknown = normalized - CAPABILITIES
    if unknown:
        raise ValueError(f"Unknown Harness capabilities: {sorted(unknown)}")
    return frozenset(cast(HarnessCapability, value) for value in normalized)


def driver_capabilities(spec: AgentDriverSpec) -> frozenset[HarnessCapability]:
    values = set(spec.execution_capabilities | spec.management_capabilities) | {"execute", "local_interrupt"}
    for name in ("voice_calling", "file_tools", "console_execution"):
        if getattr(spec.tool_profile, name):
            values.add(name)
    if spec.checkpoint_policy_path:
        values.add("resume")
    return normalize_capabilities(values)


def negotiate_capabilities(
    implemented: Iterable[str], *, verified: Iterable[str] | None = None,
    policy: HarnessExecutionPolicy | None = None, revision: int = 0,
) -> HarnessCapabilityDescriptor:
    supported = normalize_capabilities(implemented)
    checked = supported if verified is None else normalize_capabilities(verified) & supported
    settings = policy or HarnessExecutionPolicy()
    configured = supported - settings.disabled_capabilities
    effective = configured & checked
    unavailable = {
        capability: "disabled_by_configuration" if capability in settings.disabled_capabilities else "not_verified"
        for capability in supported - effective
    }
    return HarnessCapabilityDescriptor(
        implemented=supported, configured=configured, verified=checked, effective=effective,
        configurable=supported & CONFIGURABLE_HARNESS_CAPABILITIES,
        unavailable=unavailable, policy=settings, revision=revision,
    )


async def effective_capabilities(agent_id: int, runtime: str) -> frozenset[HarnessCapability]:
    """Recheck operator restrictions, including remote MCP calls after reconfiguration."""
    from . import agent_service
    from .harness_port import harness_selection_port
    from .registry import get_driver_spec

    spec = get_driver_spec(runtime)
    agent = await agent_service.get(agent_id)
    selection = await harness_selection_port.resolve(agent)
    if selection is not None and selection.driver_code != spec.code:
        # Conversation turns have an independent runtime selection from durable Tasks.
        selection = None
    policy, _ = await harness_selection_port.configuration(
        selection.provider_code if selection is not None else spec.code,
    )
    return negotiate_capabilities(driver_capabilities(spec), policy=policy).effective


async def effective_tool_profile(agent_id: int, runtime: str) -> ToolExposureProfile:
    effective = await effective_capabilities(agent_id, runtime)
    if "execute" not in effective:
        return ToolExposureProfile()
    return ToolExposureProfile(
        voice_calling="voice_calling" in effective,
        file_tools="file_tools" in effective,
        console_execution="console_execution" in effective,
    )
