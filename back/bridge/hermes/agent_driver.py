"""Hermes contribution to the generic agent-driver registry."""

from app.agent import (
    AgentDriverSpec,
    DriverPipelinePolicy,
    ToolExposureProfile,
    get_agent_record,
    register_agent_profile_observer,
    register_driver_spec,
)


HERMES_DRIVER = AgentDriverSpec(
    code="hermes",
    label_key="agent.driverHermes",
    factory_path="bridge.hermes.driver:create_driver",
    tool_profile=ToolExposureProfile(voice_calling=True),
    pipeline_policy=DriverPipelinePolicy(
        use_planner=False,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
        use_briefing=False,
    ),
    manages_runtime=True,
    supports_cancellation=True,
    checkpoint_policy_path="bridge.hermes.checkpoint_policy:create_policy",
    execution_capabilities=frozenset(
        {
            "streaming",
            "cancellation",
            "checkpoints",
            "semantic_events",
            "structured_tool_events",
            "normalized_usage",
            "approvals",
        }
    ),
    management_capabilities=frozenset(
        {"status", "start", "stop", "restart", "update", "logs", "refresh"}
    ),
)

register_driver_spec(HERMES_DRIVER)


async def _ensure_configuration(agent_id: int, action: str) -> None:
    """Materialize bridge persistence after an Agent selects this driver."""

    if action == "delete":
        return
    agent = await get_agent_record(agent_id)
    if agent is None or agent.agent_driver != HERMES_DRIVER.code:
        return
    from core.database import get_db
    from .config_service import ensure_config

    await ensure_config(agent)
    await get_db().commit()


register_agent_profile_observer("hermes_configuration", _ensure_configuration)

__all__ = ["HERMES_DRIVER"]
