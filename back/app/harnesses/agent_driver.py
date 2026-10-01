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
    pipeline_policy=DriverPipelinePolicy(use_planner=False),
    supports_streaming=True,
    # Only a persisted managed actor can acknowledge a remote cancellation.
    supports_cancellation=True,
    execution_capabilities=frozenset(
        {"streaming", "semantic_events", "normalized_usage", "checkpoints", "cancellation"}
    ),
    checkpoint_policy_path="app.harnesses.checkpoint_policy:create_policy",
)

register_driver_spec(OPENAI_MESSAGES_DRIVER)

__all__ = ["OPENAI_MESSAGES_DRIVER"]
