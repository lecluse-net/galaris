"""Common network Harness contribution to the agent-driver registry."""

from app.agent import (
    AgentDriverSpec,
    DriverPipelinePolicy,
    ToolExposureProfile,
    register_driver_spec,
)


OPENAI_MESSAGES_DRIVER = AgentDriverSpec(
    code="openai_messages",
    label_key="agent.driverOpenAIMessages",
    factory_path="app.harnesses.driver:create_driver",
    tool_profile=ToolExposureProfile(),
    pipeline_policy=DriverPipelinePolicy(use_planner=False, use_briefing=False),
    supports_streaming=True,
    # Chat Completions cannot address and cancel a remote run by its run_id.
    supports_cancellation=False,
    execution_capabilities=frozenset(
        {"streaming", "semantic_events", "normalized_usage"}
    ),
)

register_driver_spec(OPENAI_MESSAGES_DRIVER)

__all__ = ["OPENAI_MESSAGES_DRIVER"]
