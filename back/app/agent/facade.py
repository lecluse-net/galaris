"""Single public facade for the agent subsystem."""

from __future__ import annotations

import asyncio
import hashlib
import traceback
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import replace
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from loguru import logger

from .contracts import (
    AIMessage,
    AgentUsage,
    AgentContextRequest,
    AgentRunCheckpoint,
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
    AgentEvent,
    ExecutionResult,
    ReasoningEffort,
    ToolExposureProfile,
    ResolvedModel,
    ResolvedExecutionCapabilities,
    ResolvedExecutionTarget,
    OBJECTIVE_IS_STANDALONE_DATA_KEY,
    StaleAgentRunError,
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
from .checkpoints import assess_checkpoint, rebase_checkpoint
from .capabilities import MANAGEMENT_CAPABILITIES, driver_capabilities, negotiate_capabilities
from .execution_errors import HarnessCheckpointError, classify_execution_error


RUN_CHECKPOINT_DATA_KEY = "_agent_run_checkpoint"
RUN_IDENTITY_DATA_KEY = "_agent_run_identity"
_CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY = "objective_fingerprint"


async def aggregate_llm_run_usage(
    run_id: UUID,
    *,
    agent_id: int,
) -> tuple[AgentUsage, float] | None:
    """Return persisted gateway accounting through the agent-domain facade."""

    from app.llm import aggregate_agent_run_usage

    payload = await aggregate_agent_run_usage(run_id, agent_id=agent_id)
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


async def submit_background_task(draft: AgentTaskDraft) -> UUID:
    """Persist and schedule a runtime-neutral Task requested by another domain."""

    from .task_port import task_port

    task = await task_port.create(draft)
    task_port.schedule(task.id)
    return task.id


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
        if limit is None or limit < 1:
            raise RuntimeError(
                "A configured external Harness must have a positive task parallelism limit."
            )
        policy, _ = await harness_selection_port.configuration(selection.provider_code)
        return min(limit, policy.max_parallel_tasks) if policy.max_parallel_tasks else limit
    driver_code = validate_agent_driver(
        getattr(agent, "agent_driver", None),
        require_available=False,
    )
    limit = get_driver_spec(driver_code).max_parallel_tasks
    policy, _ = await harness_selection_port.configuration(driver_code)
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
    from .workflow import task_uses_briefing
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
    from app.agent import briefing_service, planner_service
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
            "model_id": model.id,
            "model_code": model.code,
            "reasoning_effort": model.reasoning_effort,
            "effort": effort,
            "execution_strategy": execution_strategy,
            "objective_fingerprint": objective_fingerprint,
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

    async def save_checkpoint(checkpoint: AgentRunCheckpoint) -> None:
        """Persist resumable driver state without exposing the task implementation."""

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
        }
        await task_port.persist_agent_run_state(
            task.id,
            expected_objective=objective,
            expected_attempt_id=attempt_id,
            data_patch={RUN_CHECKPOINT_DATA_KEY: checkpoint_payload},
            execution_result=checkpoint.result,
        )

    async def publish_event(event: AgentRunEventV1) -> None:
        """Persist only semantic events; streamed token deltas remain ephemeral."""

        await task_port.append_agent_run_event(task, event)

    from core.params import runtime_settings

    limits = AgentRunLimitsV1(
        request_limit=runtime_settings.TASK_AGENT_MAX_REQUESTS,
        tool_call_limit=runtime_settings.TASK_AGENT_MAX_TOOL_CALLS,
        tool_parallelism=4,
    )
    from .executor_service import build_system_prompt

    executor_system_prompt = await build_system_prompt(
        snapshot,
        run_context_instructions=contributed_context.system_instructions,
    )

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
        briefing_result=(
            task.get_briefing_result()
            if (
                task_uses_briefing(task)
                and callable(getattr(task, "get_briefing_result", None))
            )
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
            "briefing_text": (
                briefing_service.executor_text(task)
                if task_uses_briefing(task)
                else ""
            ),
            "delegated": bool(data.get(task_port.DELEGATED_KEY)),
            **dict(contributed_context.metadata),
            _CHECKPOINT_OBJECTIVE_FINGERPRINT_KEY: objective_fingerprint,
        },
        resume_checkpoint=resume_checkpoint,
        limits=limits,
        control=AgentRunControl(
            save_progress=save_progress,
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
        "briefing_used": request.briefing_result is not None,
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
    if result.success:
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
    if request.task_id is None and "taskless_runs" not in effective:
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
            task_attempt_id=request.attempt_id,
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
    from app.tools import native_failure_key

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
            task_attempt_id=request.attempt_id,
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
        async for raw_event in driver_stream:
            event = AgentEvent.model_validate(raw_event)
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
                    kind="run.completed" if event.result.success else "run.failed",
                    result=event.result,
                    payload={"execution_stopped": True},
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
) -> AsyncIterator[AgentEvent]:
    """Execute one voice turn through the internal conversation runtime.

    A conversational turn is not a durable Task. It bypasses the Task scheduler and
    dispatcher while retaining personality, context providers, trace, and conversation
    binding. Voice is pinned to the same model and reduced tool projection as text
    conversation rounds; the agent's Task driver is not consulted.
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

    driver_spec = resolve_driver(None)
    driver_code = driver_spec.code
    effort: Literal["standard"] = "standard"
    model = await resolve_conversation_model(agent, language)
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
        )
    )
    messaging_context = dict(contributed_context.messaging_context)
    if normalized_room_locator:
        messaging_context["room_locator"] = normalized_room_locator
    request = AgentRunRequest(
        run_id=run_id or uuid4(),
        task_id=None,
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
        system_instructions=contributed_context.system_instructions,
        shared_context=contributed_context.shared_context,
        memory_context=contributed_context.memory_context,
        continuity_context=contributed_context.continuity_context,
        conversation_history=contributed_context.conversation_history,
        messaging_context=messaging_context,
        metadata={
            "briefing_text": "",
            **dict(contributed_context.metadata),
        },
    )

    emitted_text = ""
    metadata_filter = _LeadingMessageMetadataFilter()
    async for event in stream(request):
        if event.kind == "result" and event.result is not None:
            pending = metadata_filter.finish()
            if pending:
                emitted_text += pending
                yield AgentEvent.from_message(
                    AIMessage(type="text", content=pending)
                )
            terminal = ExecutionResult.model_validate(event.result)
            terminal.result = strip_leading_message_metadata(terminal.result)
            yield AgentEvent.from_result(
                _enrich_run_result(
                    terminal,
                    request,
                )
            )
            continue
        if event.message is None:
            continue
        normalized = AIMessage.model_validate(event.message)
        if normalized.type == "text" and normalized.success:
            content = strip_leading_message_metadata(
                metadata_filter.feed(normalized.content)
            )
            if not content:
                continue
            normalized = normalized.model_copy(update={"content": content})
            # Some runtimes stream token deltas, then emit the complete final
            # answer once more. Preserve low latency without repeating that
            # answer to real-time consumers such as speech synthesis.
            if emitted_text and content == emitted_text:
                continue
            if emitted_text and content.startswith(emitted_text):
                content = content[len(emitted_text):]
                if not content:
                    continue
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


async def cancel(driver_code: str, run_id: UUID) -> HarnessCancellationReceipt:
    """Cancel a run only when the selected driver explicitly supports it."""

    spec = resolve_driver(driver_code)
    if not spec.supports_cancellation:
        raise RuntimeError(f"Driver {spec.code!r} does not support cancellation.")
    from .run_control import active_driver, request_cancellation

    driver = active_driver(spec.code, run_id) or create_driver(spec)

    return await request_cancellation(driver, run_id)


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

    await task_port.resolve_from_peer_task(task)
    await resume_parent(task)
    await task_port.maybe_fan_in(task.parent_id)
    await notify_terminal_task(task)


async def reconcile_plan_parent(
    task: AgentTask,
    children: Sequence[AgentTask],
) -> bool:
    """Resume a parent whose current step is already terminal."""
    from .contracts import TaskPhase, TaskTransition
    from .planner_service import child_for_step
    from .task_port import task_port

    plan = task.plan or {}
    cursor = int(plan.get("cursor", 0) or 0)
    current = child_for_step(children, cursor)
    if current is None or current.status not in (TaskPhase.SUCCESS, TaskPhase.ERROR):
        return False
    task_port.transition(task, TaskTransition.ROUTE_TO_PLAN)
    task_port.release(task, task_port.PAUSE_PLAN)
    await task_port.save(task)
    return True


async def resume_expired_planner_clarifications() -> None:
    from .planner_service import resume_expired_clarifications

    await resume_expired_clarifications()
