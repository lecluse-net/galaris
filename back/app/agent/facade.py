"""Single public facade for the agent subsystem."""

from __future__ import annotations

from .management_scope import team_agent_ids as team_agent_ids

import asyncio
import hashlib
import traceback
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import replace
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from loguru import logger
from .scope_contracts import EffectDescriptorV1, ScopePreflightV1

from .contracts import (
    AgentTaskState,
    AIMessage,
    AgentUsage,
    AgentContextRequest,
    AgentRunCheckpoint,
    CheckpointIndex,
    AgentRunControl,
    AgentRunEventKind,
    AgentRunEventV1,
    AgentRunIdentityV1,
    AgentRunLimitsV1,
    AgentRunRequest,
    AgentRunContext,
    AgentTask,
    AgentTaskDraft,
    AgentSnapshot,
    AgentDriverSpec,
    AgentDriverError,
    AgentDriver,
    HarnessCancellationReceipt,
    DriverTargetProvider,
    DriverPipelinePolicy,
    DriverStatus,
    DriverConfigurationProvider,
    DeepSteeringControl,
    AgentEvent,
    ExecutionResult,
    ReasoningEffort,
    ToolExposureProfile,
    ResolvedModel,
    ScopedInferenceAdmission,
    ResolvedExecutionCapabilities,
    ResolvedExecutionTarget,
    OBJECTIVE_IS_STANDALONE_DATA_KEY,
    StaleAgentRunError,
    UnknownAgentDriverError,
)
from pydantic import BaseModel
from .conversation_context import (
    LeadingMessageMetadataFilter as _LeadingMessageMetadataFilter,
    strip_leading_message_metadata,
)
from .registry import (
    all_driver_specs,
    all_driver_statuses,
    create_driver,
    get_driver_spec,
    pipeline_policy_for,
    require_available_driver,
    tool_profile_for_runtime,
)
from .reasoning_guard import ReasoningDegenerationError, ReasoningPatternGuard
from .driver_stream import validated_driver_stream
from .run_control import has_prepared_runtime_run as has_prepared_runtime_run, mark_run_prepared
from .checkpoints import assess_checkpoint, checkpoint_tool_history, rebase_checkpoint, prepare_retry_checkpoint
from .capabilities import MANAGEMENT_CAPABILITIES, driver_capabilities, negotiate_capabilities
from .execution_errors import HarnessCheckpointError, classify_execution_error


RUN_CHECKPOINT_DATA_KEY = "_agent_run_checkpoint"
RUN_RETRY_CHECKPOINT_DATA_KEY = "_agent_run_retry_checkpoint"
RUN_IDENTITY_DATA_KEY = "_agent_run_identity"
_CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY = "objective_fingerprint"


async def aggregate_llm_run_usage(
    run_id: UUID,
    *,
    agent_id: int,
    correlation_ref: str | None = None,
) -> tuple[AgentUsage, float] | None:
    """Return persisted gateway accounting through the agent-domain facade."""

    from app.llm import aggregate_agent_run_usage

    payload = await aggregate_agent_run_usage(run_id, agent_id=agent_id, correlation_ref=correlation_ref)
    if payload["requests"] <= 0:
        return None
    return (
        AgentUsage(
            input_tokens=payload["input_tokens"],
            output_tokens=payload["output_tokens"],
            cache_read_tokens=payload["cache_read_tokens"],
            cache_write_tokens=payload["cache_write_tokens"],
            reasoning_tokens=payload["reasoning_tokens"],
            requests=payload["requests"],
            tool_calls=payload["tool_calls"],
            cost=payload["cost"],
            token_quality=payload["token_quality"],
            cost_quality=payload["cost_quality"],
        ),
        payload["inference_cost"],
    )


async def inspect_task_states(task_ids: Sequence[UUID]) -> dict[UUID, AgentTaskState]:
    """Inspect at most 500 linked Tasks after the caller authorizes their owning resource."""
    from .task_port import task_port

    if len(task_ids) > 500:
        raise ValueError("Inspect at most 500 Tasks at once")
    return await task_port.inspect_states(task_ids)


async def submit_background_task(draft: AgentTaskDraft) -> UUID:
    """Persist and schedule a runtime-neutral Task requested by another domain."""

    from .task_port import task_port

    task = await task_port.create(draft)
    task_port.schedule(task.id)
    return task.id


async def find_background_tasks(agent_id: int, idempotency_keys: Sequence[str]) -> dict[str, UUID]:
    """Reconcile at most 500 authorized resource receipts without admitting work."""
    from .task_port import task_port
    if len(idempotency_keys) > 500:
        raise ValueError("Reconcile at most 500 background task submissions")
    return await task_port.find_submissions(agent_id, idempotency_keys)


def _objective_fingerprint(objective: str) -> str:
    return hashlib.sha256(objective.strip().encode("utf-8")).hexdigest()


def _checkpoint_for_objective(
    checkpoint: AgentRunCheckpoint | None,
    *,
    objective_fingerprint: str,
    amended: bool,
) -> AgentRunCheckpoint | None:
    """Negotiate objective changes without interpreting the runtime's opaque payload."""

    if checkpoint is None:
        return None
    checkpoint_data = dict(checkpoint.data)
    stored_fingerprint = str(
        checkpoint_data.get(_CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY) or ""
    ).strip()
    if stored_fingerprint == objective_fingerprint:
        return checkpoint
    if not stored_fingerprint and not amended:
        # Legacy checkpoint for an objective that has never been amended.
        return checkpoint
    rebased = rebase_checkpoint(checkpoint)
    return replace(rebased, data={
        **rebased.data, _CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY: objective_fingerprint,
    })


async def _ensure_request_objective_is_current(
    task: AgentTask,
    *,
    expected_fingerprint: str,
) -> None:
    """Reject late progress, checkpoints, or results from a superseded request."""

    from .task_port import task_port

    await task_port.refresh(task)
    current_fingerprint = _objective_fingerprint(
        str(getattr(task, "objective", "") or "")
    )
    if current_fingerprint != expected_fingerprint:
        raise StaleAgentRunError(
            "The Task objective changed while this agent run was active; "
            "discarding the stale run so the amended objective can execute."
        )


def _string_keyed_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _read_run_checkpoint(data: Mapping[str, Any]) -> AgentRunCheckpoint | None:
    raw = data.get(RUN_CHECKPOINT_DATA_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise HarnessCheckpointError("Invalid agent checkpoint envelope.")
    normalized = _string_keyed_dict(cast(object, raw))
    version = normalized.get("schema_version", 1)
    if type(version) is not int or version != 1:
        # Starting afresh could repeat an effect recorded by a newer runtime.
        raise HarnessCheckpointError(f"Unsupported agent checkpoint schema version: {version!r}")
    driver_code = str(normalized.get("driver_code") or "").strip()
    runtime_run_id = str(normalized.get("runtime_run_id") or "").strip()
    status = str(normalized.get("status") or "").strip()
    if not driver_code or not runtime_run_id or not status:
        raise HarnessCheckpointError("The agent checkpoint identity is incomplete.")
    raw_result: object = normalized.get("result")
    result = (
        ExecutionResult.model_validate(_string_keyed_dict(cast(object, raw_result)))
        if isinstance(raw_result, Mapping)
        else None
    )
    raw_checkpoint_data: object = normalized.get("data")
    checkpoint_data = (
        _string_keyed_dict(cast(object, raw_checkpoint_data))
        if isinstance(raw_checkpoint_data, Mapping)
        else {}
    )
    return AgentRunCheckpoint(
        driver_code=driver_code,
        runtime_run_id=runtime_run_id,
        status=status,
        result=result,
        data=checkpoint_data,
    )


def _persisted_request_run_id(
    data: Mapping[str, Any], *, driver_code: str
) -> UUID | None:
    """Recover the logical run identity across scheduler attempts."""

    for raw in (data.get(RUN_CHECKPOINT_DATA_KEY), data.get(RUN_IDENTITY_DATA_KEY)):
        if not isinstance(raw, Mapping):
            continue
        normalized = _string_keyed_dict(cast(object, raw))
        if str(normalized.get("driver_code") or "") != driver_code:
            continue
        candidate = normalized.get("request_run_id") or normalized.get("run_id")
        try:
            return UUID(str(candidate))
        except (TypeError, ValueError):
            continue
    return None


def _persisted_run_limit(
    data: Mapping[str, Any], *, driver_code: str, run_id: UUID,
    limit_key: Literal["request_limit", "tool_call_limit"],
) -> int | None:
    """Read the original allowance even after result application clears the active identity."""
    for key in (RUN_IDENTITY_DATA_KEY, RUN_CHECKPOINT_DATA_KEY):
        record = data.get(key)
        if not isinstance(record, Mapping):
            continue
        admission = cast(Mapping[str, object], record)
        if admission.get("request_run_id") != str(run_id) or admission.get("driver_code") != driver_code:
            continue
        limit = admission.get(limit_key)
        if type(limit) is int and limit > 0:
            return limit
    return None


def memory_context_trace(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Keep safe recall telemetry without persisting the injected memory text."""

    error = metadata.get("long_term_memory_error")
    if "memory_context_enabled" not in metadata and error is None:
        return None
    raw_ids: object = metadata.get("memory_context_ids")
    memory_ids = (
        [str(value) for value in cast(Sequence[object], raw_ids)]
        if isinstance(raw_ids, (list, tuple))
        else []
    )
    raw_count = metadata.get("memory_context_count")
    count = (
        max(0, raw_count)
        if isinstance(raw_count, int) and not isinstance(raw_count, bool)
        else len(memory_ids)
    )
    raw_retrieved_count = metadata.get("memory_context_retrieved_count")
    retrieved_count = (
        max(count, raw_retrieved_count)
        if isinstance(raw_retrieved_count, int)
        and not isinstance(raw_retrieved_count, bool)
        else count
    )
    return {
        "enabled": bool(metadata.get("memory_context_enabled")),
        "query": str(metadata.get("memory_context_query") or ""),
        "count": count,
        "retrieved_count": retrieved_count,
        "truncated": bool(metadata.get("memory_context_truncated")),
        "memory_ids": memory_ids,
        "error": str(error) if error is not None else None,
    }


def _memory_context_trace(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Compatibility alias for existing internal callers and tests."""

    return memory_context_trace(metadata)


def has_resumable_run_checkpoint(task: Any) -> bool:
    """Return whether a driver can resume the task without replaying its objective."""

    try:
        checkpoint = _read_run_checkpoint(dict(getattr(task, "data", None) or {}))
    except HarnessCheckpointError:
        return False
    if checkpoint is None:
        return False
    return assess_checkpoint(checkpoint).resumable


def recorded_checkpoint_tools(raw_checkpoint: object, *, limit: int) -> list[AIMessage]:
    """Read the bounded tool projection without exposing the driver's checkpoint format."""
    try:
        checkpoint = _read_run_checkpoint({RUN_CHECKPOINT_DATA_KEY: raw_checkpoint})
        return checkpoint_tool_history(checkpoint, limit=limit) if checkpoint is not None else []
    except (HarnessCheckpointError, TypeError, ValueError):
        return []


def prepare_run_retry(data: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare explicit retry and preserve evidence of a superseded operation."""
    prepared = dict(data)
    checkpoint = _read_run_checkpoint(data)
    if checkpoint is None:
        return prepared
    candidate = prepare_retry_checkpoint(checkpoint)
    if candidate is None:
        prepared[RUN_RETRY_CHECKPOINT_DATA_KEY] = prepared.pop(RUN_CHECKPOINT_DATA_KEY)
        prepared.pop(RUN_IDENTITY_DATA_KEY, None)
        prepared.pop("authorization_requests", None)
        return prepared
    if candidate != checkpoint:
        prepared[RUN_CHECKPOINT_DATA_KEY] = {
            **_string_keyed_dict(data[RUN_CHECKPOINT_DATA_KEY]),
            "driver_code": candidate.driver_code,
            "runtime_run_id": candidate.runtime_run_id,
            "status": candidate.status,
            "result": candidate.result.model_dump(mode="json") if candidate.result is not None else None,
            "data": dict(candidate.data),
        }
    return prepared


def objective_amendment_blocker(
    data: Mapping[str, Any], *, execution_active: bool,
) -> str | None:
    """Check amendment safety without changing a run or interpreting driver payloads.

    Task admission calls this again under its row lock, before cancellation. A lease
    without a checkpoint may already be starting effects; absence is not permission
    to restart. Rebase negotiates on a deep copy and never persists the candidate.
    """
    try:
        checkpoint = _read_run_checkpoint(data)
        if checkpoint is None:
            if execution_active or data.get(RUN_IDENTITY_DATA_KEY) is not None:
                return "Execution has no checkpoint that can safely accept an objective amendment."
            return None
        identity = data.get(RUN_IDENTITY_DATA_KEY)
        if isinstance(identity, Mapping):
            identity_data = _string_keyed_dict(cast(object, identity))
            if identity_data.get("driver_code") != checkpoint.driver_code:
                return "The execution identity and checkpoint belong to different drivers."
        rebase_checkpoint(checkpoint)
    except (HarnessCheckpointError, AgentDriverError, ValueError, TypeError):
        return "The driver cannot safely amend the current execution checkpoint."
    return None


def checkpoint_blocks_new_effects(task: Any) -> bool:
    """A resumed runtime may reconcile; a new effect requires a fully safe checkpoint."""
    try:
        checkpoint = _read_run_checkpoint(dict(getattr(task, "data", None) or {}))
    except HarnessCheckpointError:
        return True
    return checkpoint is not None and assess_checkpoint(checkpoint).state != "safe"


def list_driver_specs() -> tuple[AgentDriverSpec, ...]:
    return all_driver_specs()


def list_driver_statuses() -> tuple[DriverStatus, ...]:
    return all_driver_statuses()


def resolve_driver(code: str | None) -> AgentDriverSpec:
    return require_available_driver(code)


def retains_authorization_run(code: str) -> bool:
    """Check a saved driver even when current configuration disables new runs."""
    try:
        return get_driver_spec(code).retains_authorization_run
    except UnknownAgentDriverError:
        return False


def resolve_pipeline_policy(code: str | None) -> DriverPipelinePolicy:
    return pipeline_policy_for(code)


def resolve_tool_profile(code: str | None) -> ToolExposureProfile:
    return tool_profile_for_runtime(get_driver_spec(code).code)


def validate_agent_driver(code: str | None, *, require_available: bool = True) -> str:
    spec = require_available_driver(code) if require_available else get_driver_spec(code)
    return spec.code


async def max_parallel_tasks_for_agent(agent_id: int) -> int | None:
    """Return the provider limit, or the driver default when no provider is selected."""

    from .agent_service import get
    from .harness_port import harness_selection_port

    agent = await get(agent_id)
    if agent is None:
        raise LookupError(f"Agent {agent_id} not found.")
    selection = await harness_selection_port.resolve(agent)
    if selection is not None:
        limit = selection.max_parallel_tasks
        if limit is None and selection.metadata.get("run_scoped_llm") is not True:
            raise RuntimeError("Removing the task limit requires run-scoped LLM attribution.")
        if limit is not None and limit < 1:
            raise RuntimeError("A configured external Harness must have a positive task parallelism limit.")
        configuration_code = selection.provider_code
    else:
        configuration_code = validate_agent_driver(
            getattr(agent, "agent_driver", None),
            require_available=False,
        )
        limit = get_driver_spec(configuration_code).max_parallel_tasks
    policy, _ = await harness_selection_port.configuration(configuration_code)
    if policy.max_parallel_tasks is None:
        return limit
    return policy.max_parallel_tasks if limit is None else min(limit, policy.max_parallel_tasks)


async def _execution_driver_configuration(agent: Any, driver_code: str) -> dict[str, Any]:
    spec = resolve_driver(driver_code)
    driver = create_driver(spec)
    if not isinstance(driver, DriverConfigurationProvider):
        return {}
    return await driver.execution_configuration(agent)


def resolve_execution_target(
    spec: AgentDriverSpec,
    *,
    agent_id: int,
    driver_config: Mapping[str, Any],
) -> ResolvedExecutionTarget:
    """Freeze one safe target and its effective execution/management capabilities."""

    driver = create_driver(spec)
    if isinstance(driver, DriverTargetProvider):
        return driver.execution_target(agent_id, driver_config)
    return ResolvedExecutionTarget(
        provider_code=spec.code,
        target_ref=f"agent:{agent_id}:driver:{spec.code}",
        transport=spec.transport,
        capabilities=ResolvedExecutionCapabilities(
            execution=spec.execution_capabilities,
            management=(
                spec.management_capabilities if spec.manages_runtime else frozenset()
            ),
        ),
    )


async def resolve_execution_model(
    agent: Any,
    effort: str,
    language: str = "en",
    reasoning_effort_override: ReasoningEffort | None = None,
) -> ResolvedModel:
    """Public standard/high model resolution facade."""
    from .model_resolver import resolve_model

    normalized = "high" if effort == "high" else "standard"
    return await resolve_model(
        agent,
        normalized,
        language,
        reasoning_effort_override,
    )


async def resolve_conversation_model(agent: Any, language: str = "en") -> ResolvedModel:
    """Resolve the dedicated model shared by text and voice conversations."""

    from .model_resolver import resolve_conversation_model as resolve

    return await resolve(agent, language)


async def conversation_driver_for_agent(agent_id: int) -> str:
    """Resolve a new round against the persisted Harness assignment."""
    from core.params import runtime_settings
    from .agent_service import get
    from .harness_port import harness_selection_port
    from .registry import CLAUDE_EMBEDDED_HARNESS, conversation_driver_code, driver_status

    agent = await get(agent_id)
    if agent is None:
        raise LookupError(f"Agent {agent_id} not found.")
    embedded = conversation_driver_code(agent.agent_driver, None)
    if (
        embedded == CLAUDE_EMBEDDED_HARNESS.code
        or not runtime_settings.HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED
        or not driver_status(CLAUDE_EMBEDDED_HARNESS).enabled
    ):
        return embedded
    selection = await harness_selection_port.resolve(agent)
    return conversation_driver_code(agent.agent_driver, selection.provider_code if selection else None)


def _serialize_message(message: object) -> dict[str, Any]:
    if isinstance(message, BaseModel):
        return message.model_dump(mode="json")
    if isinstance(message, Mapping):
        mapping = cast(Mapping[object, object], message)
        return {str(key): value for key, value in mapping.items()}
    raise TypeError(f"Conversation message is not serializable: {type(message).__name__}.")


async def _build_task_run_context(
    task: AgentTask,
    request: AgentContextRequest,
) -> AgentRunContext:
    """Compose and freeze the first contact-scoped capsule on the Task root."""

    from .context import build_agent_run_context
    from .task_port import task_port

    if request.contact_memory_item_id is None:
        return await build_agent_run_context(request)

    frozen = await task_port.get_context_capsule(task)
    effective = replace(
        request,
        frozen_capsule=(
            frozen.model_dump(mode="json") if frozen is not None else None
        ),
    )
    built = await build_agent_run_context(effective)
    provider_failed = any(
        key.endswith("_error") for key in built.metadata
    )
    if (
        frozen is None
        and built.context_capsule is not None
        and not provider_failed
    ):
        canonical = await task_port.freeze_context_capsule(
            task, built.context_capsule
        )
        if canonical != built.context_capsule:
            built = await build_agent_run_context(
                replace(
                    effective,
                    frozen_capsule=canonical.model_dump(mode="json"),
                )
            )
    # Context providers and the first-capsule guard may lock or mutate the Task row.
    # End that transaction before an internal LLM request records its LLMCall through
    # another session, and before the scheduler heartbeat renews the same Task lease.
    await task_port.save(task)
    return built


async def build_task_context(
    task: AgentTask,
    *,
    stage: Literal["planning", "execution"],
) -> AgentRunContext:
    """Compose one frozen provider snapshot for a named agentic stage."""

    agent = getattr(task, "agent", None)
    agent_id = getattr(task, "agent_id", None)
    if agent is None or agent_id is None:
        return AgentRunContext()
    from app.llm import llm_service

    resolved_llm = await llm_service.get_llm_for_agent(agent)
    title = getattr(agent, "title", None)
    snapshot = AgentSnapshot(
        id=int(agent_id),
        code=str(getattr(agent, "code", "") or ""),
        first_name=str(getattr(agent, "first_name", "") or ""),
        last_name=str(getattr(agent, "last_name", "") or ""),
        driver_code=str(getattr(agent, "agent_driver", "internal") or "internal"),
        gender="F" if getattr(title, "gender", None) == "F" else "M",
        llm_id=int(resolved_llm.id) if resolved_llm is not None else None,
        personality=getattr(agent, "personality", None),
        job_description=getattr(agent, "job_description", None),
        job_title=getattr(agent, "job_title", None),
    )
    task_data = dict(getattr(task, "data", None) or {})
    fallback_history = tuple(
        _serialize_message(message)
        for message in (getattr(task, "messages", None) or ())
    )
    return await _build_task_run_context(
        task,
        AgentContextRequest(
            task_id=getattr(task, "id", None),
            agent=snapshot,
            objective=str(getattr(task, "objective", "") or ""),
            stage=stage,
            label=str(getattr(task, "label", "") or ""),
            messenger_connection_id=getattr(task, "messenger_connection_id", None),
            message_platform=getattr(task, "message_platform", None),
            message_group_id=getattr(task, "message_group_id", None),
            topic_id=getattr(task, "topic_id", None),
            contact_memory_item_id=getattr(task, "contact_memory_item_id", None),
            task_data=task_data,
            include_historical_context=not bool(
                task_data.get(OBJECTIVE_IS_STANDALONE_DATA_KEY)
            ),
            fallback_history=fallback_history,
        ),
    )


async def build_run_request(task: AgentTask) -> AgentRunRequest:
    """Freeze a persisted task into a DTO before crossing the driver boundary."""
    agent = getattr(task, "agent", None)
    if agent is None:
        raise RuntimeError(f"Task {getattr(task, 'id', '?')} has no associated agent.")
    driver_code = validate_agent_driver(getattr(agent, "agent_driver", None))
    driver_spec = resolve_driver(driver_code)
    effort = "high" if getattr(task, "effort", None) == "high" else "standard"
    data = dict(task.data or {})
    objective = str(getattr(task, "objective", "") or "")
    objective_fingerprint = _objective_fingerprint(objective)
    resume_checkpoint = _checkpoint_for_objective(
        _read_run_checkpoint(data),
        objective_fingerprint=objective_fingerprint,
        amended=bool(data.get("amendment_count")),
    )
    execution_strategy = driver_spec.execution_strategy_for(effort)
    if resume_checkpoint is not None:
        if resume_checkpoint.driver_code != driver_code:
            raise HarnessCheckpointError("A checkpoint cannot be transferred to another driver.")
        assessment = assess_checkpoint(resume_checkpoint)
        if not assessment.resumable:
            raise HarnessCheckpointError(f"The driver cannot resume this checkpoint: {assessment.reason}")
        execution_strategy = assessment.execution_strategy
    language = str(data.get("language") or "en").strip().lower()
    model = await resolve_execution_model(
        agent,
        effort,
        language,
        getattr(task, "reasoning_effort_override", None),
    )
    title = getattr(agent, "title", None)
    gender = "F" if getattr(title, "gender", None) == "F" else "M"
    driver_config = await _execution_driver_configuration(agent, driver_code)
    target = resolve_execution_target(
        driver_spec,
        agent_id=int(agent.id),
        driver_config=driver_config,
    )
    # The persisted Harness selection is authoritative. Drivers still contribute
    # execution mechanics, but they cannot silently target another runtime.
    from .harness_port import harness_selection_port

    selected_harness = await harness_selection_port.resolve(agent)
    if selected_harness is None:
        # Existing Hermes rows predate Harness persistence. They keep their legacy
        # target until the DbAdmin backfill or the first explicit Harness switch.
        pass
    else:
        if selected_harness.driver_code != driver_code:
            raise RuntimeError(
                "The selected Harness and compatibility agent driver disagree."
            )
        target = ResolvedExecutionTarget(
            provider_code=selected_harness.provider_code,
            target_ref=f"harness:{selected_harness.id}",
            revision=str(selected_harness.revision),
            transport=target.transport,
            ready=selected_harness.status == "ready",
            capabilities=ResolvedExecutionCapabilities(
                execution=driver_spec.execution_capabilities,
                management=driver_spec.management_capabilities,
                unavailable=(
                    {}
                    if selected_harness.status == "ready"
                    else {"execute": f"Harness status is {selected_harness.status}."}
                ),
            ),
            metadata={
                **target.metadata,
                **dict(selected_harness.metadata),
                "harness_name": selected_harness.name,
                "model": selected_harness.model,
            },
        )
    policy, policy_revision = await harness_selection_port.configuration(target.provider_code)
    implemented = driver_capabilities(driver_spec)
    verified = implemented
    if selected_harness is not None:
        implemented = implemented | selected_harness.capabilities
        verified = (verified - {"execute", "streaming"}) | selected_harness.capabilities
    descriptor = negotiate_capabilities(
        implemented, verified=verified, policy=policy, revision=policy_revision,
    )
    target = target.model_copy(update={
        "descriptor": descriptor,
        "capabilities": ResolvedExecutionCapabilities(
            execution=descriptor.effective - MANAGEMENT_CAPABILITIES,
            management=descriptor.effective & MANAGEMENT_CAPABILITIES,
            unavailable=descriptor.unavailable,
        ),
    })
    snapshot = AgentSnapshot(
        id=int(agent.id),
        code=str(agent.code),
        first_name=str(agent.first_name),
        last_name=str(agent.last_name),
        driver_code=driver_code,
        gender=gender,
        llm_id=int(model.id),
        personality=getattr(agent, "personality", None),
        job_description=getattr(agent, "job_description", None),
        job_title=getattr(agent, "job_title", None),
        driver_config=driver_config,
    )
    from app.agent import planner_service
    from .task_port import task_port

    shared_context = "\n\n".join(
        part
        for part in (planner_service.task_plan_context(task), task_port.collab_context(task))
        if part
    )
    fallback_history = tuple(
        _serialize_message(message)
        for message in (getattr(task, "messages", None) or ())
    )
    contributed_context = await _build_task_run_context(
        task,
        AgentContextRequest(
            task_id=getattr(task, "id", None),
            agent=snapshot,
            objective=objective,
            stage="execution",
            label=str(getattr(task, "label", "") or ""),
            messenger_connection_id=getattr(task, "messenger_connection_id", None),
            message_platform=getattr(task, "message_platform", None),
            message_group_id=getattr(task, "message_group_id", None),
            topic_id=getattr(task, "topic_id", None),
            contact_memory_item_id=getattr(task, "contact_memory_item_id", None),
            task_data=data,
            include_historical_context=not bool(
                data.get(OBJECTIVE_IS_STANDALONE_DATA_KEY)
            ),
            fallback_history=fallback_history,
        ),
    )
    shared_context = "\n\n".join(
        part
        for part in (shared_context, contributed_context.shared_context)
        if part
    )
    if (
        selected_harness is not None
        and "skills" not in selected_harness.capabilities
    ):
        # A configured network Harness has no provider-owned filesystem projector.
        # Inject only bounded SKILL.md instructions; provisioned providers such as
        # Hermes receive the complete immutable tree through their own projector.
        from app.skill import build_skill_prompt

        skill_prompt = await build_skill_prompt(int(agent.id))
        shared_context = "\n\n".join(
            part for part in (shared_context, skill_prompt) if part
        )
    approval_raw = await task_port.approval_action(task)
    approval: Literal["auto", "deny_agent", "ask"] = (
        cast(Literal["auto", "deny_agent", "ask"], approval_raw)
        if approval_raw in {"auto", "deny_agent", "ask"}
        else "ask"
    )
    request_run_id = (
        _persisted_request_run_id(data, driver_code=driver_code) or uuid4()
    )
    from core.params import runtime_settings

    request_limit = runtime_settings.TASK_AGENT_MAX_REQUESTS
    tool_call_limit = runtime_settings.TASK_AGENT_MAX_TOOL_CALLS
    budget_trace: dict[str, int] = {}
    if driver_code == "claude_embedded":
        request_limit = _persisted_run_limit(
            data, driver_code=driver_code, run_id=request_run_id, limit_key="request_limit",
        ) or request_limit
        budget_trace["request_limit"] = request_limit
    if driver_code in {"internal", "claude_embedded"}:
        tool_call_limit = _persisted_run_limit(
            data, driver_code=driver_code, run_id=request_run_id, limit_key="tool_call_limit",
        ) or tool_call_limit
        budget_trace["tool_call_limit"] = tool_call_limit
    limits = AgentRunLimitsV1(
        request_limit=request_limit,
        tool_call_limit=tool_call_limit,
        tool_parallelism=4,
    )
    attempt_id = await task_port.activate_agent_run(
        task,
        {
            "schema_version": "galaris.agent-run-identity/v1",
            "task_id": str(getattr(task, "id", "") or ""),
            "request_run_id": str(request_run_id),
            "driver_code": driver_code,
            "provider_code": target.provider_code,
            "target_ref": target.target_ref,
            "target_revision": target.revision,
            "transport": target.transport,
            "local_interrupt": bool(target.descriptor and "local_interrupt" in target.descriptor.effective),
            "call_recovery": bool(
                driver_spec.supports_call_recovery and target.descriptor
                and {"local_interrupt", "cancellation"} <= target.descriptor.effective
            ),
            "model_id": model.id,
            "model_code": model.code,
            "executor_profile_effort": model.executor_profile_effort,
            "reasoning_effort": model.reasoning_effort,
            "effort": effort,
            "execution_strategy": execution_strategy,
            "objective_fingerprint": objective_fingerprint,
            **budget_trace,
        },
    )

    async def save_progress(result: ExecutionResult) -> None:
        """Publish an observable partial result without declaring it resumable."""

        await task_port.persist_agent_run_state(
            task.id,
            expected_objective=objective,
            expected_attempt_id=attempt_id,
            execution_result=result,
        )

    async def record_activity() -> None:
        if attempt_id is not None:
            await task_port.record_agent_run_activity(task.id, attempt_id, request_run_id)

    previous_checkpoint: CheckpointIndex | None = None
    checkpoint_revision: int | None = None

    async def save_checkpoint(checkpoint: AgentRunCheckpoint) -> None:
        """Persist resumable driver state without exposing the task implementation."""

        nonlocal previous_checkpoint, checkpoint_revision
        index = await asyncio.to_thread(checkpoint.checkpoint_index)
        base = None
        if previous_checkpoint is not None and checkpoint_revision is not None:
            prefixes = index.unchanged_prefixes(previous_checkpoint)
            if prefixes:
                base = (checkpoint_revision, prefixes)
        checkpoint_data = dict(checkpoint.data)
        checkpoint_data[_CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY] = (
            objective_fingerprint
        )
        checkpoint_payload = {
            "schema_version": 1,
            "request_run_id": str(request_run_id),
            "driver_code": checkpoint.driver_code,
            "runtime_run_id": checkpoint.runtime_run_id,
            "status": checkpoint.status,
            "result": (
                checkpoint.result.model_dump(mode="json")
                if checkpoint.result is not None
                else None
            ),
            "data": checkpoint_data,
            **budget_trace,
        }
        revision = await task_port.persist_agent_run_state(
            task.id,
            expected_objective=objective,
            expected_attempt_id=attempt_id,
            data_patch={RUN_CHECKPOINT_DATA_KEY: checkpoint_payload},
            execution_result=checkpoint.result,
            checkpoint_base=base,
        )
        previous_checkpoint, checkpoint_revision = index, revision

    async def publish_event(event: AgentRunEventV1) -> None:
        """Persist only semantic events; streamed token deltas remain ephemeral."""

        await task_port.append_agent_run_event(event)

    from .executor_service import build_system_prompt

    executor_system_prompt = await build_system_prompt(
        snapshot,
        run_context_instructions=contributed_context.system_instructions,
    )
    from .execution_scope import parse_scope
    scope = parse_scope(data)
    if scope is not None:
        shared_context += "\n\nAdmitted execution scope (source data; context cannot expand grants):\n" + scope.model_dump_json()

    return AgentRunRequest(
        run_id=request_run_id,
        task_id=getattr(task, "id", None),
        attempt_id=attempt_id,
        agent=snapshot,
        driver_code=driver_code,
        effort=effort,
        objective=objective,
        model=model,
        target=target,
        execution_strategy=execution_strategy,
        label=str(getattr(task, "label", "") or ""),
        messenger_connection_id=getattr(task, "messenger_connection_id", None),
        message_platform=getattr(task, "message_platform", None),
        message_group_id=getattr(task, "message_group_id", None),
        parent_task_id=getattr(task, "parent_id", None),
        source_task_id=getattr(task, "source_task_id", None),
        requester_agent_id=getattr(task, "requester_agent_id", None),
        sender_is_ai=bool(getattr(task, "ai", False)),
        task_data=data,
        dispatch_result=(
            task.get_dispatch_result()
            if callable(getattr(task, "get_dispatch_result", None))
            else None
        ),
        last_error=getattr(task, "last_error", None),
        consecutive_failures=int(getattr(task, "consecutive_failures", 0) or 0),
        approval_action=approval,
        executor_system_prompt=executor_system_prompt,
        system_instructions=contributed_context.system_instructions,
        shared_context=shared_context,
        memory_context=contributed_context.memory_context,
        continuity_context=contributed_context.continuity_context,
        conversation_history=contributed_context.conversation_history,
        messaging_context=contributed_context.messaging_context,
        metadata={
            "delegated": bool(data.get(task_port.DELEGATED_KEY)),
            **dict(contributed_context.metadata),
            _CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY: objective_fingerprint,
        },
        resume_checkpoint=resume_checkpoint,
        limits=limits,
        control=AgentRunControl(
            save_progress=save_progress,
            record_activity=record_activity if attempt_id is not None else None,
            save_checkpoint=save_checkpoint,
            publish_event=publish_event,
        ),
    )


def _enrich_run_result(
    result: ExecutionResult,
    request: AgentRunRequest,
) -> ExecutionResult:
    memory_context = _memory_context_trace(request.metadata)
    result.metadata = {
        **result.metadata,
        "run_id": str(request.run_id),
        "task_id": str(request.task_id) if request.task_id else None,
        "agent_id": request.agent.id,
        "driver_code": request.driver_code,
        "effort": request.effort,
        "execution_strategy": request.execution_strategy,
        "attempt_id": str(request.attempt_id) if request.attempt_id else None,
        "execution_target": (
            request.target.model_dump(mode="json") if request.target is not None else None
        ),
        "model_id": request.model.id,
        "model_code": request.model.code,
        "model_name": request.model.model_name,
        "reasoning_effort": request.model.reasoning_effort,
        "model_fallback_used": request.model.fallback_used,
        "usage": result.usage.model_dump(mode="json"),
        "planner_used": request.parent_task_id is not None,
        _CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY: request.metadata.get(
            _CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY
        ),
        **(
            {"memory_context": memory_context}
            if memory_context is not None
            else {}
        ),
    }
    return result


def _apply_run_result(
    task: AgentTask,
    result: ExecutionResult,
    request: AgentRunRequest,
) -> None:
    result = _enrich_run_result(result, request)
    task.set_execution_result(result)
    data = dict(getattr(task, "data", None) or {})
    # A failed terminal result may still be followed by the scheduler's automatic
    # retry policy. Keep the effect-safe checkpoint so that retry can resume the
    # provider history and replay durable tool results instead of repeating effects.
    # Explicit human retries also preserve this checkpoint and its effect journal.
    if result.success or result.disposition == "waiting_for_children":
        data.pop(RUN_CHECKPOINT_DATA_KEY, None)
    data.pop(RUN_IDENTITY_DATA_KEY, None)
    task.data = data


async def run_task(task: AgentTask) -> ExecutionResult:
    """Execute a task through the driver resolved by the strict facade."""
    request = await build_run_request(task)
    result = await run(request)
    await _ensure_request_objective_is_current(
        task,
        expected_fingerprint=_objective_fingerprint(request.objective),
    )
    _apply_run_result(task, result, request)
    return result


def _validate_run_request(request: AgentRunRequest, spec: AgentDriverSpec) -> None:
    """Validate the common boundary before constructing a concrete runtime."""
    if request.agent.driver_code != spec.code:
        raise ValueError("The request agent and selected driver disagree.")
    descriptor = request.target.descriptor if request.target is not None else None
    effective = descriptor.effective if descriptor is not None else driver_capabilities(spec)
    if "execute" not in effective:
        raise ValueError("Execution is disabled for this Harness.")
    if request.task_id is None and request.deep_session_id is None and "taskless_runs" not in effective:
        raise ValueError(f"Driver {spec.code!r} requires a durable Task.")
    if request.target is not None and not request.target.ready:
        raise ValueError("The frozen Harness target is not ready.")
    if request.resume_checkpoint is not None:
        if request.resume_checkpoint.driver_code != spec.code:
            raise HarnessCheckpointError("A checkpoint cannot be transferred to another driver.")
        if "resume" not in effective:
            raise HarnessCheckpointError("Checkpoint resume is disabled for this Harness.")
        if not assess_checkpoint(request.resume_checkpoint).resumable:
            raise HarnessCheckpointError("The checkpoint does not permit safe recovery.")
    request.to_envelope().model_dump_json()


async def run(request: AgentRunRequest) -> ExecutionResult:
    """Consume the same validated lifecycle as every streaming consumer."""
    terminal: ExecutionResult | None = None
    async for event in stream(request):
        if event.result is not None:
            terminal = event.result
    assert terminal is not None
    return terminal


def _event_identity(
    request: AgentRunRequest,
    *,
    runtime_run_id: str | None = None,
) -> AgentRunIdentityV1:
    checkpoint = request.resume_checkpoint
    return AgentRunIdentityV1(
        task_id=request.task_id,
        attempt_id=request.attempt_id,
        run_id=request.run_id,
        runtime_run_id=(
            runtime_run_id
            or (
                checkpoint.runtime_run_id
                if checkpoint is not None
                and checkpoint.driver_code == request.driver_code
                else None
            )
        ),
    )


async def _publish_run_event(
    request: AgentRunRequest,
    *,
    sequence: int,
    kind: AgentRunEventKind,
    message: AIMessage | None = None,
    result: ExecutionResult | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    publisher = request.publish_event
    if publisher is None:
        return
    runtime_run_id = None
    if result is not None:
        runtime_run_id = str(result.metadata.get("runtime_run_id") or "") or None
    try:
        await publisher(
            AgentRunEventV1(
                identity=_event_identity(
                    request,
                    runtime_run_id=runtime_run_id,
                ),
                sequence=sequence,
                kind=kind,
                message=message,
                result=result,
                usage=result.usage if result is not None else None,
                payload=dict(payload or {}),
            )
        )
    except Exception:
        # The Task result remains authoritative. A timeline projection must never turn a
        # successful external effect into a replayable driver failure.
        logger.exception(
            "Could not persist semantic agent event kind={} run={}",
            kind,
            request.run_id,
        )


def _failure_result(request: AgentRunRequest, exc: BaseException) -> ExecutionResult:
    return ExecutionResult(
        prompt=request.objective,
        result=f"{type(exc).__name__}: {exc}",
        success=False,
        failure=classify_execution_error(exc),
        metadata={"runtime_status": "cancelled" if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else "failed"},
    )


async def _record_run_outcome(
    request: AgentRunRequest,
    result: ExecutionResult,
    *,
    exc: BaseException | None = None,
) -> None:
    """Record terminal model/runtime failures and close recovered tool incidents."""

    if result.disposition in {"waiting_for_authorization", "waiting_for_children"}:
        return

    from core.failure_journal import (
        FailureEvent,
        mark_failure_run_recovered,
        record_failure_event,
    )

    if result.success:
        await mark_failure_run_recovered(request.run_id)
        return
    error_message = str(
        result.metadata.get("error")
        or result.result
        or (str(exc) if exc is not None else "Agent run failed")
    )
    error_type = type(exc).__name__ if exc is not None else str(
        result.metadata.get("error_type") or "AgentRunError"
    )
    await record_failure_event(
        FailureEvent(
            idempotency_key=(
                f"agent-run:{request.run_id}:attempt:{request.attempt_id}:terminal"
                if request.attempt_id is not None
                else f"agent-run:{request.run_id}:terminal"
            ),
            kind="llm",
            phase="agent_run",
            error_type=error_type,
            error_message=error_message,
            retryable=None,
            will_retry=(
                False if result.failure is not None and result.failure.retry == "never" else None
            ),
            task_id=request.task_id,
            task_attempt_id=request.attempt_id if request.task_id is not None else None,
            agent_id=request.agent.id,
            run_uuid=request.run_id,
            driver_code=request.driver_code,
            provider_code=request.target.provider_code if request.target else None,
            model_code=request.model.code,
            trace={
                "source": "agent_run",
                "request": request.to_envelope().model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "exception": (
                    {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": "".join(
                            traceback.format_exception(type(exc), exc, exc.__traceback__)
                        ),
                    }
                    if exc is not None
                    else None
                ),
            },
        )
    )


async def _record_tool_failure(
    request: AgentRunRequest,
    message: AIMessage,
    *,
    sequence: int,
) -> None:
    """Driver-neutral fallback when a concrete runtime lacks a richer hook."""

    from core.failure_journal import FailureEvent, record_failure_event
    from app.services import native_failure_key

    external_id = message.tool_call_external_id
    key = external_id or f"sequence-{sequence}"
    await record_failure_event(
        FailureEvent(
            idempotency_key=(
                native_failure_key(message.content or "") or f"tool-call:{request.run_id}:{key}"
            ),
            kind="tool",
            phase="tool_execution",
            error_type="ToolCallError",
            error_message=message.content or "Tool call failed",
            retryable=True,
            attempt_number=message.tool_retry_number,
            retry_limit=message.tool_retry_limit,
            will_retry=True if message.tool_retry_limit is not None else None,
            task_id=request.task_id,
            task_attempt_id=request.attempt_id if request.task_id is not None else None,
            agent_id=request.agent.id,
            run_uuid=request.run_id,
            driver_code=request.driver_code,
            provider_code=request.target.provider_code if request.target else None,
            model_code=request.model.code,
            tool_name=message.tool_name,
            tool_call_external_id=external_id,
            trace={
                "source": "agent_driver.tool_event",
                "message": message.model_dump(mode="json"),
                "identity": _event_identity(request).model_dump(mode="json"),
            },
        )
    )


async def stream(request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """One lifecycle for native streams and non-streaming adapters."""
    spec = resolve_driver(request.driver_code)
    if request.target is None or request.target.descriptor is None:
        from .harness_port import harness_selection_port

        target = request.target or resolve_execution_target(
            spec, agent_id=request.agent.id, driver_config=request.agent.driver_config,
        )
        policy, revision = await harness_selection_port.configuration(target.provider_code)
        descriptor = negotiate_capabilities(driver_capabilities(spec), policy=policy, revision=revision)
        request = replace(request, target=target.model_copy(update={"descriptor": descriptor}))
    _validate_run_request(request, spec)
    driver = create_driver(spec)
    from .run_control import own_run

    with own_run(driver, request):
        async with aclosing(_stream_driver(request, spec=spec, driver=driver)) as events:
            async for event in events:
                yield event


def deep_execution_target(target: ResolvedExecutionTarget) -> ResolvedExecutionTarget:
    """Keep skill synchronization receipts out of the identity of a Deep session."""
    return target.model_copy(update={"metadata": {
        key: value for key, value in target.metadata.items() if not key.startswith("skill_")
    }})


async def deep_harness_target(agent_id: int) -> tuple[str, ResolvedExecutionTarget]:
    """Resolve the agent's assigned harness without dispatching any work."""
    from .agent_service import get
    from .harness_port import harness_selection_port

    agent = await get(agent_id)
    if agent is None:
        raise PermissionError("The conversation agent is unavailable.")
    spec = resolve_driver(agent.agent_driver)
    if spec.deep_model_source is None:
        raise PermissionError("The selected harness does not expose direct Deep sessions.")
    selected = await harness_selection_port.resolve(agent)
    if selected is not None and spec.transport != "embedded":
        if selected.status != "ready" or selected.driver_code != spec.code:
            raise PermissionError("The configured harness is unavailable.")
        return spec.code, deep_execution_target(ResolvedExecutionTarget(
            provider_code=selected.provider_code, target_ref=f"harness:{selected.id}",
            transport=spec.transport, revision=str(selected.revision),
            metadata={**selected.metadata, "model": selected.model,
                      **({"galaris_extensions": True} if spec.deep_model_source == "managed_gateway" else {})},
        ))
    if spec.deep_model_source == "managed_gateway":
        raise PermissionError("Deep requires a managed harness assignment.")
    configuration = await _execution_driver_configuration(agent, spec.code)
    return spec.code, resolve_execution_target(spec, agent_id=agent_id, driver_config=configuration)


async def stream_deep_submission(
    *, session_id: UUID, submission_id: UUID, agent_id: int, driver_code: str,
    target: ResolvedExecutionTarget, objective: str, native_session: str | None, credential: str | None,
    requester_user_id: int,
    room_id: UUID, connection_id: int, language: str, message_data: dict[str, Any],
    history: tuple[Mapping[str, Any], ...], attachments: tuple[Mapping[str, Any], ...],
    native_history: str | None = None, save_native_history: Callable[[str], None] | None = None,
    control_credential: str | None = None,
    admit_inference: Callable[[ResolvedModel], Awaitable[ScopedInferenceAdmission]] | None = None,
    resume_checkpoint: AgentRunCheckpoint | None = None,
    save_checkpoint: Callable[[AgentRunCheckpoint], Awaitable[None]] | None = None,
    tool_lock: asyncio.Lock | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Send an input directly to the session's harness with its normal tools and skills."""
    from .agent_service import get
    from app.llm import deep_inference_scope, llm_execution_scope

    agent = await get(agent_id)
    if agent is None:
        raise PermissionError("The conversation agent is unavailable.")
    if (driver_code, target) != await deep_harness_target(agent_id):
        raise PermissionError("The Deep session's harness assignment has changed.")
    spec = resolve_driver(driver_code)
    external_model = target.metadata.get("model")
    model = (ResolvedModel(0, external_model, external_model, external_model, "standard")
             if credential is None and spec.deep_model_source == "harness" and isinstance(external_model, str) and external_model
             else await resolve_execution_model(agent, "standard", language))
    admission = None
    if spec.scoped_inference:
        if admit_inference is None:
            raise PermissionError("This Deep session requires an admitted submission.")
        admission = await admit_inference(model)
    snapshot = AgentSnapshot(
        id=agent.id, code=agent.code, first_name=agent.first_name, last_name=agent.last_name,
        driver_code=driver_code, llm_id=model.id, gender="F" if getattr(agent.title, "gender", None) == "F" else "M",
        personality=agent.personality, job_description=agent.job_description, job_title=agent.job_title,
        driver_config=await _execution_driver_configuration(agent, driver_code) if spec.manages_runtime else {},
    )
    if message_data.get("console_cwd"):
        objective += (
            f"\n\nLinked checkout: {message_data['displayed_repository_uri']} "
            f"(Galaris Console cwd={message_data['console_cwd']!r})."
        )
    request = AgentRunRequest(
        run_id=submission_id, task_id=None, attempt_id=admission.attempt_id if admission else None,
        limits=AgentRunLimitsV1(request_limit=admission.request_limit if admission else None,
                               tool_call_limit=admission.tool_call_limit if admission else None),
        deep_session_id=session_id, deep_native_session=native_session,
        deep_credential=credential,
        deep_control_credential=control_credential,
        deep_native_history=native_history, resume_checkpoint=resume_checkpoint,
        control=AgentRunControl(save_native_history=save_native_history, save_checkpoint=save_checkpoint,
                                conversation_tool_lock=tool_lock,
                                reserve_conversation_tool=admission.reserve_tool if admission else None),
        agent=snapshot, model=model, effort="standard", objective=objective, driver_code=driver_code,
        target=target, message_group_id=str(room_id), message_platform="internal",
        messenger_connection_id=connection_id, conversation_history=history, attachments=attachments,
        task_data={**message_data, "language": language, "conversation_id": str(room_id), "connection_id": connection_id},
        system_instructions="\n\n".join(filter(None, (snapshot.personality, snapshot.job_description))),
    )
    with deep_inference_scope(session_id), llm_execution_scope(requester_user_id=requester_user_id):
        async with aclosing(cast(AsyncGenerator[AgentEvent, None], stream(request))) as events:
            async for event in events:
                yield event


async def steer_deep_input(driver_code: str, target: ResolvedExecutionTarget, session_id: UUID,
                          control: str, text: str) -> bool:
    driver = create_driver(resolve_driver(driver_code))
    if isinstance(driver, DeepSteeringControl):
        return await driver.steer_deep(target, session_id, control, text)
    return False


async def _stream_driver(
    request: AgentRunRequest,
    *,
    spec: AgentDriverSpec,
    driver: AgentDriver,
) -> AsyncGenerator[AgentEvent, None]:
    """Validate one concrete stream and project its sparse semantic timeline."""

    terminal_seen = False
    sequence = 1
    live_sequence = 0
    reasoning_guard = ReasoningPatternGuard()
    from .live import AgentLiveEvent, publish_live_event

    if request.task_id is not None:
        await publish_live_event(
            AgentLiveEvent(
                task_id=request.task_id,
                run_id=request.run_id,
                sequence=live_sequence,
                attempt_id=request.attempt_id,
                kind="started",
            )
        )
    await _publish_run_event(request, sequence=sequence, kind="run.started")
    driver_stream = validated_driver_stream(driver, request, spec=spec)
    try:
        from .harness_port import harness_selection_port

        await harness_selection_port.prepare_execution(request)
        mark_run_prepared(request.run_id)
        async for raw_event in driver_stream:
            event = AgentEvent.model_validate(raw_event)
            if request.deep_session_id is not None and event.message is not None and event.message.native_session_ref is not None:
                yield event
                continue
            if event.message is not None:
                try:
                    reasoning_guard.observe(event.message)
                except ReasoningDegenerationError:
                    close = getattr(driver_stream, "aclose", None)
                    if callable(close):
                        try:
                            await cast(Callable[[], Awaitable[None]], close)()
                        except Exception:
                            logger.exception(
                                "Could not close degenerate agent stream driver={} run={}",
                                spec.code,
                                request.run_id,
                            )
                    raise
            live_sequence += 1
            if request.task_id is not None:
                await publish_live_event(
                    AgentLiveEvent(
                        task_id=request.task_id,
                        run_id=request.run_id,
                        sequence=live_sequence,
                        attempt_id=request.attempt_id,
                        kind="result" if event.kind == "result" else "message",
                        message=event.message,
                        result=event.result,
                    )
                )
            if event.kind == "result":
                terminal_seen = True
                assert event.result is not None
                sequence += 1
                await _publish_run_event(
                    request,
                    sequence=sequence,
                    kind="run.waiting_for_authorization" if event.result.disposition == "waiting_for_authorization"
                         else "run.waiting_for_children" if event.result.disposition == "waiting_for_children"
                         else "run.completed" if event.result.success else "run.failed",
                    result=event.result,
                    payload={"execution_stopped": event.result.metadata.get("execution_stopped", True) is True},
                )
                await _record_run_outcome(request, event.result)
            elif (
                event.message is not None
                and event.message.type == "tool"
                and (
                    event.message.stream_id is None
                    or event.message.stream_mode == "snapshot"
                )
            ):
                sequence += 1
                await _publish_run_event(
                    request,
                    sequence=sequence,
                    kind="tool.completed" if event.message.success else "tool.failed",
                    message=event.message,
                    payload={"tool_name": event.message.tool_name or ""},
                )
                if not event.message.success:
                    await _record_tool_failure(
                        request,
                        event.message,
                        sequence=sequence,
                    )
            yield event
    except (asyncio.CancelledError, GeneratorExit) as exc:
        if request.task_id is not None and not terminal_seen:
            live_sequence += 1
            await publish_live_event(
                AgentLiveEvent(
                    task_id=request.task_id,
                    run_id=request.run_id,
                    sequence=live_sequence,
                    attempt_id=request.attempt_id,
                    kind="cancelled",
                    result=_failure_result(request, exc),
                )
            )
        if not terminal_seen:
            sequence += 1
            await _publish_run_event(
                request,
                sequence=sequence,
                kind="run.cancelled",
                result=_failure_result(request, exc),
            )
        raise
    except StaleAgentRunError as exc:
        if request.task_id is not None and not terminal_seen:
            live_sequence += 1
            await publish_live_event(
                AgentLiveEvent(
                    task_id=request.task_id,
                    run_id=request.run_id,
                    sequence=live_sequence,
                    attempt_id=request.attempt_id,
                    kind="cancelled",
                    result=_failure_result(request, exc),
                )
            )
        if not terminal_seen:
            sequence += 1
            await _publish_run_event(
                request,
                sequence=sequence,
                kind="run.cancelled",
                result=_failure_result(request, exc),
            )
        raise
    except Exception as exc:
        if request.task_id is not None and not terminal_seen:
            live_sequence += 1
            await publish_live_event(
                AgentLiveEvent(
                    task_id=request.task_id,
                    run_id=request.run_id,
                    sequence=live_sequence,
                    attempt_id=request.attempt_id,
                    kind="failed",
                    result=_failure_result(request, exc),
                )
            )
        if not terminal_seen:
            sequence += 1
            failure = _failure_result(request, exc)
            await _publish_run_event(
                request,
                sequence=sequence,
                kind="run.failed",
                result=failure,
            )
            await _record_run_outcome(request, failure, exc=exc)
        raise
    finally:
        await driver_stream.aclose()


async def stream_conversation_turn_events(
    *,
    agent_id: int,
    objective: str,
    conversation_id: str,
    room_locator: str | None = None,
    messenger_connection_id: int | None = None,
    conversation_history: Sequence[object] = (),
    current_message_id: UUID | None = None,
    excluded_message_ids: Sequence[UUID] = (),
    linked_work: Sequence[Mapping[str, object]] = (),
    language: str = "en",
    transport_kind: str = "call",
    run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
    voice_session_id: UUID | None = None,
    resume_checkpoint: AgentRunCheckpoint | None = None,
    control: AgentRunControl | None = None,
    round_driver_code: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Execute one voice turn through the internal conversation runtime.

    A conversational turn is not a durable Task. It bypasses the Task scheduler and
    dispatcher while retaining personality, context providers, trace, and conversation
    binding. Voice uses the conversation model and the engine frozen when the
    round was admitted by the audio transport.
    """
    from . import agent_service

    agent = await agent_service.get(agent_id)
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found")

    text = objective.strip()
    if not text:
        raise ValueError("conversation objective must not be empty")
    if len(conversation_id) > 512:
        raise ValueError("conversation_id must not exceed 512 characters")
    normalized_room_locator = (room_locator or "").strip()
    if len(normalized_room_locator) > 512:
        raise ValueError("room_locator must not exceed 512 characters")

    driver_spec = resolve_driver(round_driver_code)
    driver_code = driver_spec.code
    effort: Literal["standard"] = "standard"
    model = await resolve_conversation_model(agent, language)
    control = control or AgentRunControl()
    admission = None
    if driver_spec.scoped_inference:
        admit = control.admit_conversation_inference
        if (conversation_round_id is None or voice_session_id is None or admit is None
                or run_id != conversation_round_id):
            raise PermissionError("This voice runtime requires an admitted round in the live call.")
        admission = await admit(model)
    title = getattr(agent, "title", None)
    snapshot = AgentSnapshot(
        id=int(agent.id),
        code=str(agent.code),
        first_name=str(agent.first_name),
        last_name=str(agent.last_name),
        driver_code=driver_code,
        gender="F" if getattr(title, "gender", None) == "F" else "M",
        llm_id=int(model.id),
        personality=getattr(agent, "personality", None),
        job_description=getattr(agent, "job_description", None),
        job_title=getattr(agent, "job_title", None),
        driver_config={},
    )
    message_platform = f"voice:{transport_kind}"[:100]
    task_data: dict[str, Any] = {
        "conversation_id": conversation_id,
        "language": language,
        "voice_call": True,
        "conversation_only": True,
        "conversation_origin": "voice",
        "voice_session_id": str(voice_session_id) if voice_session_id else None,
        "transport_kind": transport_kind,
        "linked_work": tuple(dict(item) for item in linked_work),
        "message_id": str(current_message_id) if current_message_id else "",
        "excluded_message_ids": tuple(str(item) for item in excluded_message_ids),
        **(
            {"room_locator": normalized_room_locator}
            if normalized_room_locator
            else {}
        ),
        **(
            {
                "connection_id": messenger_connection_id,
                "messenger_connection_id": messenger_connection_id,
            }
            if messenger_connection_id is not None
            else {}
        ),
        **(
            {"conversation_round_id": str(conversation_round_id)}
            if conversation_round_id is not None
            else {}
        ),
    }
    fallback_history = tuple(
        _serialize_message(item) for item in conversation_history
    )
    from .context import build_agent_run_context

    contributed_context = await build_agent_run_context(
        AgentContextRequest(
            task_id=None,
            agent=snapshot,
            objective=text,
            label=f"Voice conversation — {agent.code}",
            messenger_connection_id=messenger_connection_id,
            message_platform=message_platform,
            message_group_id=conversation_id,
            topic_id=topic_id,
            contact_memory_item_id=contact_memory_item_id,
            task_data=task_data,
            fallback_history=fallback_history,
            conversation_round_id=conversation_round_id,
        )
    )
    messaging_context = dict(contributed_context.messaging_context)
    if normalized_room_locator:
        messaging_context["room_locator"] = normalized_room_locator
    request = AgentRunRequest(
        run_id=run_id or uuid4(),
        task_id=None,
        attempt_id=admission.attempt_id if admission else None,
        limits=AgentRunLimitsV1(request_limit=admission.request_limit if admission else None,
                               tool_call_limit=admission.tool_call_limit if admission else None),
        agent=snapshot,
        driver_code=driver_code,
        effort=effort,
        objective=text,
        model=model,
        execution_strategy=driver_spec.execution_strategy_for(effort),
        label=f"Voice conversation — {agent.code}",
        messenger_connection_id=messenger_connection_id,
        message_platform=message_platform,
        message_group_id=conversation_id,
        task_data=task_data,
        approval_action="ask",
        resume_checkpoint=resume_checkpoint,
        control=replace(control, reserve_conversation_tool=admission.reserve_tool) if admission else control,
        system_instructions=contributed_context.system_instructions,
        shared_context=contributed_context.shared_context,
        memory_context=contributed_context.memory_context,
        continuity_context=contributed_context.continuity_context,
        conversation_history=contributed_context.conversation_history,
        messaging_context=messaging_context,
        metadata={
            **dict(contributed_context.metadata),
        },
    )

    emitted_text = ""
    metadata_filter = _LeadingMessageMetadataFilter()
    async with aclosing(
        cast(AsyncGenerator[AgentEvent, None], stream(request)),
    ) as events:
        async for event in events:
            if event.kind == "result" and event.result is not None:
                pending = metadata_filter.finish()
                if pending:
                    emitted_text += pending
                    yield AgentEvent.from_message(AIMessage(type="text", content=pending))
                terminal = ExecutionResult.model_validate(event.result)
                terminal.result = strip_leading_message_metadata(terminal.result)
                yield AgentEvent.from_result(_enrich_run_result(terminal, request))
                continue
            if event.message is None:
                continue
            normalized = AIMessage.model_validate(event.message)
            if normalized.type == "text" and normalized.success:
                content = strip_leading_message_metadata(
                    metadata_filter.feed(normalized.content)
                )
                # Some runtimes emit the whole answer after streaming it. Preserve
                # low latency without repeating speech synthesis for those words.
                if not content or (emitted_text and content == emitted_text):
                    continue
                if emitted_text and content.startswith(emitted_text):
                    content = content[len(emitted_text):]
                normalized = normalized.model_copy(update={"content": content})
                emitted_text += content
            yield AgentEvent.from_message(normalized)


async def stream_conversation_turn(
    *,
    agent_id: int,
    objective: str,
    conversation_id: str,
    room_locator: str | None = None,
    messenger_connection_id: int | None = None,
    conversation_history: Sequence[object] = (),
    language: str = "en",
    transport_kind: str = "call",
    run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
) -> AsyncIterator[AIMessage]:
    """Compatibility message stream for consumers that do not persist driver results."""

    async for event in stream_conversation_turn_events(
        agent_id=agent_id,
        objective=objective,
        conversation_id=conversation_id,
        room_locator=room_locator,
        messenger_connection_id=messenger_connection_id,
        conversation_history=conversation_history,
        language=language,
        transport_kind=transport_kind,
        run_id=run_id,
        conversation_round_id=conversation_round_id,
    ):
        if event.kind == "message" and event.message is not None:
            yield AIMessage.model_validate(event.message)


async def request_call_recovery(driver_code: str, run_id: UUID) -> bool:
    """Ask the owner of this exact live run to interrupt only model generation."""
    from .run_control import request_call_recovery as request

    return await request(driver_code, run_id)


async def cancel(
    driver_code: str, run_id: UUID, *, task_id: UUID | None = None,
) -> HarnessCancellationReceipt:
    """Cancel a run only when the selected driver explicitly supports it."""

    spec = resolve_driver(driver_code)
    if not spec.supports_cancellation:
        raise RuntimeError(f"Driver {spec.code!r} does not support cancellation.")
    from .run_control import active_driver, request_cancellation
    from .contracts import DriverCheckpointCancellationControl
    from .task_port import task_port

    driver = active_driver(spec.code, run_id) or create_driver(spec)

    checkpoint = None
    if task_id is not None and isinstance(driver, DriverCheckpointCancellationControl):
        task = await task_port.get_by_id(task_id)
        data = _string_keyed_dict(getattr(task, "data", None))
        raw = data.get(RUN_CHECKPOINT_DATA_KEY)
        if isinstance(raw, Mapping) and _string_keyed_dict(cast(object, raw)).get("request_run_id") == str(run_id):
            candidate = _read_run_checkpoint(data)
            if candidate is not None and candidate.driver_code == spec.code:
                checkpoint = candidate
    return await request_cancellation(driver, run_id, checkpoint=checkpoint)


async def stream_task(task: AgentTask) -> AsyncIterator[AIMessage]:
    """Stream normalized events from the selected driver."""
    request = await build_run_request(task)
    terminal: ExecutionResult | None = None
    async for event in stream(request):
        if event.kind == "message" and event.message is not None:
            yield AIMessage.model_validate(event.message)
        elif event.kind == "result" and event.result is not None:
            terminal = ExecutionResult.model_validate(event.result)
    assert terminal is not None  # guaranteed by the public stream contract
    await _ensure_request_objective_is_current(
        task,
        expected_fingerprint=_objective_fingerprint(request.objective),
    )
    _apply_run_result(task, terminal, request)


async def run_workflow_step(task: AgentTask) -> None:
    """Scheduler entry point for one agentic workflow step."""
    from .workflow import run_step

    await run_step(task)


async def stream_workflow(task: AgentTask) -> AsyncIterator[AIMessage]:
    """Streaming entry point for the complete agentic workflow."""
    from .workflow import run_stream

    async for message in run_stream(task):
        yield message


async def get_plan_progress(task_id: UUID) -> dict[str, Any] | None:
    from .planner_service import get_progress

    return await get_progress(task_id)


async def handle_terminal_task(task: AgentTask) -> None:
    """Resolve agentic waits triggered by a durable terminal task."""
    from .observers import notify_terminal_task
    from .planner_service import resume_parent
    from .task_port import task_port

    if not task_port.has_terminal_outcome(task):
        return
    await task_port.resolve_from_peer_task(task)
    await resume_parent(task)
    await task_port.maybe_fan_in(task.parent_id)
    await notify_terminal_task(task)


async def reconcile_plan_parent(
    task: AgentTask,
    children: Sequence[AgentTask],
) -> bool:
    """Resume a parent whose current step is already terminal."""
    from .contracts import TaskTransition
    from .planner_service import child_for_step
    from .task_port import task_port

    plan = task.plan or {}
    cursor = int(plan.get("cursor", 0) or 0)
    current = child_for_step(children, cursor)
    if current is None or not task_port.has_terminal_outcome(current):
        return False
    task_port.transition(task, TaskTransition.ROUTE_TO_PLAN)
    task_port.release(task, task_port.PAUSE_PLAN)
    await task_port.save(task)
    return True


async def resume_expired_planner_clarifications() -> None:
    from .planner_service import resume_expired_clarifications

    await resume_expired_clarifications()
from .admin_authorization import delegated_admin as delegated_admin
from .admin_authorization import admin_available as admin_available
from .admin_schemas import PageLimit as PageLimit, PageOffset as PageOffset
from .avatars import apply_generated_avatar as apply_generated_avatar, portrait_snapshot as portrait_snapshot


async def record_scope_preflight(
    task_id: UUID, *, agent_id: int,
    descriptor: EffectDescriptorV1 | None, tool_name: str,
    arguments: Mapping[str, object], operation_id: UUID | None = None,
    expected_scope_revision: int | None = None,
) -> ScopePreflightV1:
    """Persist a native effect's admission through the injected Task port."""
    from .task_port import task_port

    return await task_port.record_scope_preflight(task_id, agent_id=agent_id,
        descriptor=descriptor, tool_name=tool_name, arguments=arguments,
        operation_id=operation_id, expected_scope_revision=expected_scope_revision)
