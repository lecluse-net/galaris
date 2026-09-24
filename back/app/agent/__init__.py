"""Generic agent domain and public Galaris facade.

Concrete runtimes are loaded lazily by the registry. Keeping this package importable
without Pydantic AI or Hermes prevents cycles with task contracts.
"""

from .active_run import get_current_task
from .capabilities import driver_capabilities, effective_capabilities, effective_tool_profile, negotiate_capabilities, normalize_capabilities
from .execution_errors import HarnessExecutionError, HarnessCheckpointError, HarnessProtocolError, classify_execution_error
from .contracts import (
    AIMessage,
    AIResult,
    AgentUsage,
    AgentDriver,
    AgentEvent,
    AgentModelConfigurationError,
    AgentDriverSpec,
    HarnessCapability,
    HarnessCapabilityDescriptor,
    HarnessExecutionPolicy,
    AgentContextContribution,
    AgentContextCandidate,
    AgentContextCapsule,
    AgentContextRequest,
    AgentRunCheckpoint,
    AgentRunControl,
    AgentRunEnvelopeV1,
    AgentRunEventKind as AgentRunEventKind,
    AgentRunEventV1,
    AgentRunIdentityV1,
    AgentRunLimitsV1,
    AgentRunContext,
    AgentRunRequest,
    AgentSnapshot,
    AgentTaskDraft,
    AgentTaskBlocker,
    AgentTaskBlockers,
    RealtimeAgentContext,
    OBJECTIVE_IS_STANDALONE_DATA_KEY as OBJECTIVE_IS_STANDALONE_DATA_KEY,
    BriefingChoice,
    BriefingResult,
    ConversationDispatchDecision,
    ConfiguredHarnessSelection,
    DispatchDecision,
    DispatchResult,
    DriverPipelinePolicy,
    DriverStatus,
    ExecutionResult,
    RuntimeName,
    ResolvedModel,
    ResolvedExecutionCapabilities,
    ResolvedExecutionTarget,
    TaskMessage,
    TaskMessageAttachment,
    ToolExposureProfile,
    ToolConcurrencyPolicy as ToolConcurrencyPolicy,
    ToolEffectPolicy as ToolEffectPolicy,
    UsageQuality as UsageQuality,
    WorkingResource,
    WorkingSet,
)
from .context import (
    build_agent_run_context,
    register_context_provider,
    registered_context_providers,
    unregister_context_provider,
)
from .observers import (
    notify_agent_profile,
    register_agent_profile_observer,
    register_terminal_task_observer,
    unregister_agent_profile_observer,
    unregister_terminal_task_observer,
)
from .facade import (
    aggregate_llm_run_usage,
    cancel,
    build_task_context,
    list_driver_specs,
    list_driver_statuses,
    get_plan_progress,
    handle_terminal_task,
    has_resumable_run_checkpoint,
    objective_amendment_blocker,
    memory_context_trace,
    max_parallel_tasks_for_agent,
    resolve_driver,
    resolve_conversation_model,
    resolve_execution_model,
    resolve_execution_target,
    resolve_pipeline_policy,
    resolve_tool_profile,
    reconcile_plan_parent,
    resume_expired_planner_clarifications,
    run_task,
    run,
    run_workflow_step,
    stream_task,
    stream,
    stream_conversation_turn,
    stream_conversation_turn_events,
    stream_workflow,
    submit_background_task,
    validate_agent_driver,
)
from .registry import register_driver_spec
from .models import Agent, AgentGroup, Title
from .dialogue_service import current_dialogue_scope, dialogue_scope_for, require_agent_contact
from .assertions import AgentDialogueAssertion
from .realtime import (
    build_realtime_agent_context,
    list_realtime_tasks,
    realtime_task_status,
    submit_realtime_task,
)
from .dispatcher import (
    dispatch_conversation,
    evaluate_dispatcher_input,
    dispatcher_system_prompt,
    preview_dispatcher_input,
    register_dispatcher_output_contracts,
)
from .briefing_service import register_briefing_output_contracts, validate_briefing_resources
from .conversation_context import (
    conversation_context_block,
    current_message_data,
    linked_work_context,
    message_history_prefix,
    message_history_text,
    message_prompt,
)
from .executor_prompts import ExecutorPromptContext, build_executor_prompt_tree
from .prompt_tree import (
    ExecutorKind,
    PromptTree,
    insert_before_suffix,
    render_prompt_tree,
    section,
)
from .voice import parse_voice_selection
from .schemas import AgentCreate, AgentUpdate, Agent as AgentSchema
from .assertions import AgentManagerAssertion, AgentOwnerAssertion
from .management_scope import (
    AgentManagementScope,
    AgentScopeDeniedError,
    current_management_scope,
    management_scope_for,
)
from .live import AgentLiveEvent, register_live_listener
from .harness_port import register_harness_selection_port


async def agent_skill_revision(agent_id: int) -> str:
    """Desired skill revision shared by every concrete Harness adapter."""
    from app.skill import build_skill_projection

    return (await build_skill_projection(agent_id)).revision


async def projected_skill_agent_ids(agent_ids: list[int] | None = None) -> list[int]:
    from .harness_port import harness_selection_port

    return await harness_selection_port.projected_skill_agent_ids(agent_ids)


async def request_skill_sync(agent_id: int) -> None:
    from .harness_port import harness_selection_port

    await harness_selection_port.request_skill_sync(agent_id)


async def get_agent_record(agent_id: int) -> Agent | None:
    """Return one agent record through the public agent-domain surface."""

    from .agent_service import get

    return await get(agent_id)


async def list_agent_records(
    *,
    driver_code: str | None = None,
    limit: int = 500,
    agent_ids: frozenset[int] | None = None,
) -> tuple[Agent, ...]:
    """List agent records through the public domain surface for runtime bridges."""

    from .agent_service import get_all

    records = await get_all(
        limit=limit,
        agent_driver=driver_code,
        agent_ids=agent_ids,
    )
    return tuple(records)


async def agent_has_open_tasks(agent_id: int) -> bool:
    """Return whether an agent owns any non-terminal root Task.

    Harness replacement consumes this public query so it never imports ``app.task``.
    """

    from .task_port import task_port

    return bool(await task_port.list_for_agent(agent_id, limit=1))


async def get_agent_task_blockers(agent_id: int) -> AgentTaskBlockers:
    """Return the open root Tasks relevant to a Harness selection change."""

    from .task_port import task_port

    return await task_port.harness_blockers(agent_id)


async def terminate_paused_agent_tasks(agent_id: int) -> AgentTaskBlockers:
    """Force-terminate paused root Tasks, then return any remaining blockers."""

    from .task_port import task_port

    return await task_port.force_terminate_paused_for_agent(agent_id)


__all__ = [
    "HarnessExecutionError", "HarnessCheckpointError", "HarnessProtocolError", "classify_execution_error",
    "HarnessCapability", "HarnessCapabilityDescriptor", "HarnessExecutionPolicy",
    "driver_capabilities", "negotiate_capabilities", "normalize_capabilities",
    "effective_capabilities", "effective_tool_profile",
    "read_agent_resource", "list_agent_resources",
    "Agent",
    "AgentTeamModel",
    "AgentGroup",
    "current_dialogue_scope",
    "dialogue_scope_for",
    "require_agent_contact",
    "AgentDialogueAssertion",
    "Title",
    "AgentCreate",
    "AgentUpdate",
    "AgentSchema",
    "AgentOwnerAssertion",
    "AgentManagerAssertion",
    "AgentManagementScope",
    "AgentScopeDeniedError",
    "current_management_scope",
    "management_scope_for",
    "AgentLiveEvent",
    "AIMessage",
    "AIResult",
    "AgentUsage",
    "AgentTaskDraft",
    "AgentTaskBlocker",
    "AgentTaskBlockers",
    "ExecutionResult",
    "DispatchDecision",
    "DispatchResult",
    "BriefingChoice",
    "BriefingResult",
    "ConversationDispatchDecision",
    "ConfiguredHarnessSelection",
    "AgentDriver",
    "AgentEvent",
    "AgentModelConfigurationError",
    "AgentDriverSpec",
    "AgentContextContribution",
    "AgentContextCandidate",
    "AgentContextCapsule",
    "AgentContextRequest",
    "AgentRunCheckpoint",
    "AgentRunControl",
    "AgentRunEnvelopeV1",
    "AgentRunEventV1",
    "AgentRunIdentityV1",
    "AgentRunLimitsV1",
    "AgentRunContext",
    "AgentRunRequest",
    "AgentSnapshot",
    "RealtimeAgentContext",
    "DriverPipelinePolicy",
    "DriverStatus",
    "RuntimeName",
    "ResolvedModel",
    "ResolvedExecutionCapabilities",
    "ResolvedExecutionTarget",
    "TaskMessage",
    "TaskMessageAttachment",
    "ToolExposureProfile",
    "WorkingResource",
    "WorkingSet",
    "aggregate_llm_run_usage",
    "build_agent_run_context",
    "conversation_context_block",
    "current_message_data",
    "linked_work_context",
    "build_task_context",
    "build_realtime_agent_context",
    "cancel",
    "list_driver_specs",
    "list_driver_statuses",
    "get_plan_progress",
    "get_agent_record",
    "list_agent_records",
    "agent_has_open_tasks",
    "get_agent_task_blockers",
    "terminate_paused_agent_tasks",
    "handle_terminal_task",
    "has_resumable_run_checkpoint",
    "objective_amendment_blocker",
    "memory_context_trace",
    "max_parallel_tasks_for_agent",
    "message_history_prefix",
    "message_history_text",
    "message_prompt",
    "parse_voice_selection",
    "resolve_driver",
    "resolve_conversation_model",
    "register_context_provider",
    "register_driver_spec",
    "register_agent_profile_observer",
    "register_live_listener",
    "register_harness_selection_port",
    "agent_skill_revision",
    "projected_skill_agent_ids",
    "request_skill_sync",
    "registered_context_providers",
    "register_terminal_task_observer",
    "resolve_execution_model",
    "resolve_execution_target",
    "resolve_pipeline_policy",
    "resolve_tool_profile",
    "reconcile_plan_parent",
    "resume_expired_planner_clarifications",
    "run_task",
    "run",
    "run_workflow_step",
    "stream_task",
    "stream",
    "stream_conversation_turn",
    "stream_conversation_turn_events",
    "stream_workflow",
    "submit_background_task",
    "submit_realtime_task",
    "list_realtime_tasks",
    "realtime_task_status",
    "validate_agent_driver",
    "evaluate_dispatcher_input",
    "dispatcher_system_prompt",
    "preview_dispatcher_input",
    "register_dispatcher_output_contracts",
    "register_briefing_output_contracts",
    "validate_briefing_resources",
    "dispatch_conversation",
    "ExecutorKind",
    "ExecutorPromptContext",
    "PromptTree",
    "build_executor_prompt_tree",
    "render_prompt_tree",
    "insert_before_suffix",
    "section",
    "unregister_context_provider",
    "unregister_agent_profile_observer",
    "unregister_terminal_task_observer",
    "notify_agent_profile",
    "get_current_task",
]

from .resource_facade import read_agent_resource, list_agent_resources

from .models import AgentTeam as AgentTeamModel
