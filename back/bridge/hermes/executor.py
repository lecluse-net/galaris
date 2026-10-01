"""Execute Galaris EXEC tasks through an agent's configured Hermes API server."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from datetime import datetime
from collections.abc import Mapping
from typing import Any, AsyncIterator, Optional, cast
from uuid import UUID, uuid4
from loguru import logger
from core.i18n import is_supported, render_prompt, t
from core.params import runtime_settings
from core.util import as_dict, as_list, get_encryption_service
from app.agent.contracts import (
    AgentEvent,
    AgentRunCheckpoint,
    AgentRunRequest,
    AIMessage,
    AIResult,
    AgentUsage,
    ExecutionResult,
    HarnessCancellationReceipt,
    normalize_tool_name,
)
from app.agent import message_prompt
from . import client
from . import driver as hermes_driver
from .client import HermesTarget
from . import session_binding
from .media import current_content
from .prompt import build_context_instructions, hermes_context_values

# Minimum interval between partial trace snapshots during streaming.
_PERSIST_INTERVAL = 0.5
_RUN_POLL_INTERVAL = 2.0
_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_NON_EFFECT_TOOLS = {"approval", "final_result", "reply", "thinking"}
_ACTIVE_RUNS: dict[UUID, tuple[HermesTarget, str]] = {}
_ACTIVE_RUNS_LOCK = asyncio.Lock()
_MANAGED_RUNS: set[UUID] = set()


async def _register_active_run(
    request: AgentRunRequest,
    target: HermesTarget,
    runtime_run_id: str,
) -> None:
    async with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[request.run_id] = (target, runtime_run_id)
        _ACTIVE_RUNS[request.id] = (target, runtime_run_id)
        if request.target is not None and request.target.target_ref.startswith("harness:"):
            _MANAGED_RUNS.update((request.run_id, request.id))


async def _unregister_active_run(request: AgentRunRequest) -> None:
    async with _ACTIVE_RUNS_LOCK:
        for identifier in {request.run_id, request.id}:
            _ACTIVE_RUNS.pop(identifier, None)
            _MANAGED_RUNS.discard(identifier)


async def cancel(run_id: UUID) -> None:
    """Stop the Hermes runtime run associated with a Galaris run identifier."""
    if run_id in _MANAGED_RUNS:
        from app.tools.facade import revoke_runtime_run_grant
        await revoke_runtime_run_grant(run_id)
    async with _ACTIVE_RUNS_LOCK:
        active = _ACTIVE_RUNS.get(run_id)
    if active is None:
        raise RuntimeError(
            render_prompt(
                t("hermes.errors.cancel_run_not_active"),
                run_id=run_id,
            )
        )
    target, runtime_run_id = active
    try:
        await client.stop_run(target, runtime_run_id)
    except client.HermesRunNotFound:
        logger.info("Hermes run {} was already absent while cancelling", runtime_run_id)


def _cancellation_target(target: HermesTarget) -> dict[str, str]:
    """Keep the original control endpoint with encrypted credentials in the checkpoint."""
    return {"url": target.url, "model": target.model,
            "api_key": get_encryption_service().encrypt(target.api_key)}


async def request_cancellation(
    run_id: UUID, *, checkpoint: AgentRunCheckpoint | None = None,
) -> HarnessCancellationReceipt:
    if run_id in _MANAGED_RUNS or (checkpoint is not None and checkpoint.data.get("runtime_run_context")):
        from app.tools.facade import revoke_runtime_run_grant
        await revoke_runtime_run_grant(run_id)
    async with _ACTIVE_RUNS_LOCK:
        active = _ACTIVE_RUNS.get(run_id)
    if active is None and checkpoint is not None and checkpoint.driver_code == "hermes":
        snapshot = checkpoint.data.get("cancellation_target")
        if checkpoint.data.get("execution_strategy") == "direct" and isinstance(snapshot, dict):
            active = (HermesTarget.from_config(as_dict(snapshot), agent_code="hermes"), checkpoint.runtime_run_id)
    if active is None:
        return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="unknown")
    target, runtime_run_id = active
    status = await client.get_run_status(target, runtime_run_id)
    if status.get("run_id") != runtime_run_id:
        return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="unknown")
    if status.get("status") in _TERMINAL_RUN_STATUSES and status.get("execution_stopped") is True:
        return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="confirmed")
    response = await client.stop_run(target, runtime_run_id)
    accepted = response.get("run_id") == runtime_run_id and response.get("status") in (
        _TERMINAL_RUN_STATUSES | {"stopping"}
    )
    return HarnessCancellationReceipt(
        run_id=run_id, scope="remote", state="requested" if accepted else "unknown",
    )


async def _cancel_if_active(request: AgentRunRequest) -> None:
    if request.target is not None and request.target.target_ref.startswith("harness:"):
        from app.tools.facade import revoke_runtime_run_grant
        await revoke_runtime_run_grant(request.run_id)
    async with _ACTIVE_RUNS_LOCK:
        active = _ACTIVE_RUNS.get(request.id) or _ACTIVE_RUNS.get(request.run_id)
    if active is None:
        return
    target, runtime_run_id = active
    try:
        await client.stop_run(target, runtime_run_id)
    except client.HermesRunNotFound:
        return
    except Exception:
        logger.exception("Hermes runtime cancellation failed for run={}", runtime_run_id)


def _checkpoint_has_effects(checkpoint: AgentRunCheckpoint) -> bool:
    result = checkpoint.result
    return result is not None and any(
        tool not in _NON_EFFECT_TOOLS for tool in result.tools_used
    )


async def _run_lifecycle_events(
    target: HermesTarget,
    run_id: str,
    *,
    resume: bool,
    language: str,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a fresh run, or poll a persisted run after the SSE client disappeared."""

    if not resume:
        async for event in client.run_events(target, run_id, language=language):
            yield event
            if event["event"] in {"run.completed", "run.failed", "run.cancelled"}:
                return

    while True:
        try:
            status = await client.get_run_status(target, run_id)
        except client.HermesRunNotFound:
            yield {
                "event": "run.failed",
                "data": {"error": _message(language, "errors.run_not_found", run_id=run_id)},
            }
            return
        state = str(status.get("status") or "unknown").lower()
        if state == "completed":
            yield {"event": "run.completed", "data": status}
            return
        if state in {"failed", "cancelled"}:
            yield {
                "event": "run.failed",
                "data": {
                    **status,
                    "error": status.get("error")
                    or _message(language, "errors.run_ended", status=state),
                },
            }
            return
        if state == "waiting_for_approval" and isinstance(status.get("approval"), dict):
            yield {"event": "approval.request", "data": status["approval"]}
        if state == "waiting_for_authorization":
            yield {"event": "authorization.required", "data": status}
        yield {"event": "run.status", "data": status}
        await asyncio.sleep(_RUN_POLL_INTERVAL)


def _task_language(task: AgentRunRequest) -> str:
    data = task.data if isinstance(task.data, dict) else {}
    language = str(data.get("language") or "").strip().lower()
    return language if is_supported(language) else "en"


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"hermes.{key}", language), **values)


def _coerce_tool_args(raw: Any) -> dict[str, Any] | None:
    """Normalize Hermes tool arguments from a mapping, JSON text, or scalar value."""
    if isinstance(raw, dict):
        return as_dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": raw}
        return as_dict(parsed) if isinstance(parsed, dict) else {"value": parsed}
    if raw is not None:
        return {"value": raw}
    return None


def _normalize_hermes_tool(
    raw_name: Any,
    raw_arguments: Any,
) -> tuple[str, dict[str, Any]]:
    """Expose a deferred Hermes call as the underlying tool in Galaris traces."""

    tool_name = normalize_tool_name(raw_name or "tool")
    arguments = _coerce_tool_args(raw_arguments) or {}
    if tool_name != "tool_call":
        return tool_name, arguments

    underlying_name = str(arguments.get("name") or "").strip()
    if not underlying_name:
        return tool_name, arguments

    return (
        normalize_tool_name(underlying_name),
        _coerce_tool_args(arguments.get("arguments")) or {},
    )


def _tool_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _llm_tool_content(tool: dict[str, Any], language: str = "en") -> str:
    """Return visible tool-block content copied from ``LLMCall.tool_calls``."""
    if "error" in tool and tool.get("error") not in (None, ""):
        return _tool_value_to_text(tool.get("error"))
    if "result" in tool:
        result = _tool_value_to_text(tool.get("result"))
        return result or _message(language, "tool_completed")
    return _message(language, "tool_running")


def _llm_tool_success(tool: dict[str, Any]) -> bool:
    status = str(tool.get("status") or "").lower()
    return status not in {"failed", "error"} and "error" not in tool


def _llm_tool_result(tool: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only bounded outcome fields needed by cross-driver terminal guards."""

    raw_result = tool.get("result")
    if isinstance(raw_result, str) and raw_result.lstrip().startswith("{"):
        try:
            result = as_dict(json.loads(raw_result))
        except json.JSONDecodeError:
            result = {}
    else:
        result = as_dict(raw_result)
    allowed = {
        "uri",
        "source_uri",
        "operation",
        "state",
        "status",
        "exit_code",
        "run_id",
    }
    compact = {
        key: value
        for key, value in result.items()
        if key in allowed and isinstance(value, (str, int, float, bool, type(None)))
    }
    return compact or None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _llm_tool_execution_time(tool: dict[str, Any]) -> float:
    duration = tool.get("duration")
    if isinstance(duration, (int, float)):
        return max(0.0, float(duration))

    started_at = _parse_datetime(tool.get("started_at"))
    completed_at = _parse_datetime(tool.get("completed_at"))
    if started_at is None or completed_at is None:
        return 0.0
    return max(0.0, (completed_at - started_at).total_seconds())


def _current_llm_calls(calls: list[Any], excluded_call_ids: set[str]) -> list[Any]:
    """Return provider calls created during the current executor attempt."""

    return [call for call in calls if str(call.id) not in excluded_call_ids]


def _llm_failure_text(calls: list[Any], language: str = "en") -> str | None:
    """Return the latest terminal call error, including silent disconnection."""

    if not calls:
        return None
    latest = calls[-1]
    status = str(latest.status or "").lower()
    # A finish reason proves the provider completed before a client-side cancellation.
    if status == "cancelled" and getattr(latest, "finish_reason", None):
        return None
    if status not in {"error", "cancelled", "running"}:
        return None
    detail = str(latest.error or "").strip()
    return detail or _message(
        language,
        "errors.llm_interrupted",
        status=status,
    )


def _resolve_run_error(
    terminal_event: str | None,
    calls: list[Any],
    event_error: str | None,
    language: str = "en",
) -> str | None:
    """Give explicit run termination priority over later auxiliary LLM calls."""

    if terminal_event == "completed":
        return None
    if terminal_event == "failed":
        return (
            event_error
            or _llm_failure_text(calls, language)
            or _message(language, "errors.generic")
        )
    return _llm_failure_text(calls, language) or event_error


async def sync_llm_tool_messages(
    task_id: UUID,
    ai_result: AIResult,
    tool_messages_by_id: dict[str, AIMessage],
    *,
    excluded_call_ids: set[str] | None = None,
    language: str = "en",
) -> None:
    """Copy proxy-observed tool calls for the dormant Kanban trace fallback."""
    if not hermes_driver.HERMES_HIGH_KANBAN_ENABLED:
        return

    from app.llm import llm_call_service

    for call in await llm_call_service.list_calls(task_id=task_id, limit=500):
        call_id = str(getattr(call, "id", "") or "")
        if call_id in (excluded_call_ids or set()):
            continue
        for index, raw_tool in enumerate(as_list(getattr(call, "tool_calls", []))):
            tool = as_dict(raw_tool)
            tool_call_id = str(tool.get("id") or f"{call_id}:{index}")
            tool_name, arguments = _normalize_hermes_tool(
                tool.get("name"), tool.get("arguments")
            )
            if tool_name == "final_result":
                continue
            content = _llm_tool_content(tool, language)
            success = _llm_tool_success(tool)
            tool_result = _llm_tool_result(tool)
            execution_time = _llm_tool_execution_time(tool)

            existing = tool_messages_by_id.get(tool_call_id)
            if existing is not None:
                existing.tool_call_external_id = tool_call_id
                existing.tool_name = tool_name
                existing.tool_arguments = arguments
                existing.tool_result = tool_result
                existing.content = content
                existing.success = success
                existing.execution_time = execution_time
                continue

            message = AIMessage(
                type="tool",
                tool_call_external_id=tool_call_id,
                content=content,
                tool_name=tool_name,
                tool_arguments=arguments,
                tool_result=tool_result,
                execution_time=execution_time,
                success=success,
            )
            ai_result.add_message(message)
            tool_messages_by_id[tool_call_id] = message


def _session_message_key(message: dict[str, Any], index: int) -> str:
    """Return a stable key for one message from Hermes session history."""

    message_id = message.get("id")
    if message_id not in (None, ""):
        return str(message_id)
    return ":".join(
        (
            "legacy",
            str(index),
            str(message.get("timestamp") or ""),
            str(message.get("role") or ""),
            str(message.get("tool_call_id") or ""),
        )
    )


def _session_seen_through_latest_user(messages: list[dict[str, Any]]) -> set[str]:
    """Recover a pre-run cursor for checkpoints created before session tracing existed."""

    latest_user_index = max(
        (
            index
            for index, message in enumerate(messages)
            if message.get("role") == "user"
        ),
        default=len(messages) - 1,
    )
    return {
        _session_message_key(message, index)
        for index, message in enumerate(messages)
        if index <= latest_user_index
    }


def _session_tool_call(raw: Any) -> tuple[str, str, dict[str, Any]]:
    """Normalize an OpenAI-like tool call stored in Hermes session history."""

    tool = as_dict(raw)
    function = as_dict(tool.get("function"))
    tool_call_id = str(tool.get("id") or tool.get("call_id") or "")
    tool_name, arguments = _normalize_hermes_tool(
        tool.get("name") or function.get("name"),
        tool.get("arguments")
        if "arguments" in tool
        else function.get("arguments"),
    )
    return tool_call_id, tool_name, arguments


async def _sync_hermes_session_messages(
    target: HermesTarget,
    session_id: str,
    ai_result: AIResult,
    seen_message_ids: set[str],
    tool_messages_by_id: dict[str, AIMessage],
    *,
    language: str = "en",
) -> None:
    """Recover reasoning and tools from Hermes' canonical persistent history.

    The SSE run stream is destructive and cannot be reopened after a backend reload. Native
    Hermes LLM mode also bypasses Galaris' LLM proxy entirely. Session history is therefore the
    durable source that keeps both live and resumed traces inspectable in those two cases.
    """

    messages = await client.get_session_messages(target, session_id)
    for index, message in enumerate(messages):
        message_key = _session_message_key(message, index)
        if message_key in seen_message_ids:
            continue

        role = str(message.get("role") or "")
        if role == "assistant":
            thought = str(
                message.get("reasoning_content")
                or message.get("reasoning")
                or ""
            ).strip()
            if thought and not any(
                item.type == "tool"
                and item.tool_name == "thinking"
                and item.content.strip() == thought
                for item in ai_result.messages
            ):
                # Reasoning is visible trace data, not an executable tool.
                ai_result.messages.append(AIMessage(
                    type="tool",
                    tool_name="thinking",
                    content=thought,
                ))

            for raw_tool in as_list(message.get("tool_calls")):
                tool_call_id, tool_name, arguments = _session_tool_call(raw_tool)
                if not tool_call_id or tool_name == "final_result":
                    continue
                existing = tool_messages_by_id.get(tool_call_id)
                if existing is not None:
                    existing.tool_call_external_id = tool_call_id
                    existing.tool_name = tool_name
                    existing.tool_arguments = arguments
                    continue
                tool_message = AIMessage(
                    type="tool",
                    tool_call_external_id=tool_call_id,
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    content=_message(language, "tool_running"),
                )
                ai_result.add_message(tool_message)
                tool_messages_by_id[tool_call_id] = tool_message

        elif role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if tool_call_id:
                existing = tool_messages_by_id.get(tool_call_id)
                content = _tool_value_to_text(message.get("content"))
                if existing is None:
                    existing = AIMessage(
                        type="tool",
                        tool_call_external_id=tool_call_id,
                        tool_name=normalize_tool_name(
                            message.get("tool_name") or "tool"
                        ),
                        content=content or _message(language, "tool_completed"),
                    )
                    ai_result.add_message(existing)
                    tool_messages_by_id[tool_call_id] = existing
                else:
                    existing.tool_call_external_id = tool_call_id
                    existing.content = content or _message(language, "tool_completed")

        seen_message_ids.add(message_key)


def _conversation_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce Hermes session history to the /v1/runs input format."""
    history: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant", "tool", "system"}:
            continue
        content = message.get("content")
        if content is None:
            continue
        history.append({"role": str(role), "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)})
    return history


def _request_conversation_history(task: AgentRunRequest) -> list[dict[str, Any]]:
    """Project the common Messenger snapshot into Hermes run history."""

    history: list[dict[str, Any]] = []
    for raw in task.conversation_history:
        role = str(raw.get("role") or "")
        sender_raw = raw.get("sender")
        sender: Mapping[str, Any] = (
            cast(Mapping[str, Any], sender_raw)
            if isinstance(sender_raw, Mapping)
            else cast(Mapping[str, Any], {})
        )
        if role not in {"user", "assistant", "system"}:
            role = (
                "assistant"
                if raw.get("sender_agent_id") is not None
                or bool(raw.get("sender_is_ai"))
                or sender.get("agent_id") is not None
                else "user"
            )
        content = message_prompt(raw).strip()
        if not content:
            content = str(raw.get("content") or "").strip()
        if content:
            history.append({"role": role, "content": content})
    return history


def _merged_conversation_history(
    task: AgentRunRequest, session_messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Use the canonical Galaris snapshot; Hermes persistence is only a fallback."""

    canonical = _request_conversation_history(task)
    if not canonical:
        return _conversation_history(session_messages)[
            -runtime_settings.MESSENGER_SESSION_MAX_MESSAGES :
        ]
    return canonical[-runtime_settings.MESSENGER_SESSION_MAX_MESSAGES :]



async def _stream(task: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """Consume a Hermes SSE run, stream visible events, and return a terminal result."""
    start_time = time.time()
    language = _task_language(task)

    # Resolve room messaging through the shared facade.
    from app.messenger import resolve_task_messaging

    messenger, _self_id = await resolve_task_messaging(task)

    # Merge Hermes transport context into the shared task prompt.
    from app.agent import executor_service

    memory_context = str(task.metadata.get("memory_context_rendered") or "")
    prompt_shared_context = task.shared_context
    if memory_context:
        if prompt_shared_context == memory_context:
            prompt_shared_context = ""
        elif prompt_shared_context.endswith(f"\n\n{memory_context}"):
            prompt_shared_context = prompt_shared_context[: -(len(memory_context) + 2)]
    prompt_task = replace(task, shared_context=prompt_shared_context)
    human_prompt = await executor_service.build_task_prompt(
        prompt_task, extra_context=hermes_context_values(task)
    )

    # Decrypt and validate the immutable driver configuration snapshot.
    try:
        configuration = task.agent.driver_config
        if task.resume_checkpoint is not None and task.resume_checkpoint.driver_code == task.driver_code:
            saved_target = task.resume_checkpoint.data.get("cancellation_target")
            if isinstance(saved_target, dict):
                configuration = as_dict(saved_target)
        target = HermesTarget.from_config(
            configuration,
            agent_code=task.agent.code,
        )
    except ValueError as e:
        result = ExecutionResult(
            prompt=human_prompt,
            system_prompt="",
            result=_message(language, "errors.execution_failed", error=e),
            success=False, execution_time=time.time() - start_time,
        )
        message = AIMessage(type="text", content=result.result or "", success=False)
        yield AgentEvent.from_message(message)
        yield AgentEvent.from_result(result)
        return

    logger.info(
        "Hermes executor: task={} agent={} url={} model={}",
        task.id, task.agent_id, target.url, target.model,
    )

    # Keep the ephemeral system prompt static for provider caching; task correlation remains
    # in the shared message context.
    # The common conversation snapshot is sent as actual role history below.
    # Keep the current objective as the sole user message to avoid prompt duplication.
    final_prompt = human_prompt
    context_instructions = await build_context_instructions(
        task.agent,
        run_context_instructions=task.system_instructions,
    )
    # Current content may contain model-supported OpenAI multimodal parts.
    current_message_content = await current_content(task, messenger, final_prompt)

    # The binding points at the current transcript tip. The Hermes session key identifies
    # the logical channel and intentionally remains stable when that transcript rotates.
    binding_session_id = await session_binding.get_or_create_session_id(task)
    hermes_session_key = session_binding.stable_session_key(task)
    checkpoint = (
        task.resume_checkpoint
        if task.resume_checkpoint is not None
        and task.resume_checkpoint.driver_code == task.driver_code
        else None
    )
    checkpoint_data = dict(checkpoint.data) if checkpoint is not None else {}
    managed = task.target is not None and task.target.target_ref.startswith("harness:")
    run_context: str | None = None
    if managed:
        await client.verify_authorization_control(target)
    if managed and checkpoint is not None:
        from app.tools.facade import renew_runtime_run_grant
        encrypted_context = checkpoint_data.get("runtime_run_context")
        if not isinstance(encrypted_context, str) or not encrypted_context:
            raise PermissionError("The Hermes continuation has no server-issued runtime context")
        run_context = get_encryption_service().decrypt(encrypted_context)
        await renew_runtime_run_grant(run_context, task)
    checkpoint_session_id = str(checkpoint_data.get("session_id") or "").strip()
    session_id = checkpoint_session_id or binding_session_id
    checkpoint_effective_session_id = str(
        checkpoint_data.get("effective_session_id") or ""
    ).strip()
    effective_session_id = checkpoint_effective_session_id or session_id
    try:
        await client.ensure_session(
            target,
            effective_session_id,
            title=f"Galaris — {effective_session_id}",
        )
    except Exception as e:
        result = ExecutionResult(
            prompt=human_prompt, system_prompt=context_instructions,
            result=_message(
                language,
                "errors.session_create_failed",
                session_id=effective_session_id,
                error=e,
            ),
            success=False, execution_time=time.time() - start_time,
        )
        message = AIMessage(type="text", content=result.result or "", success=False)
        yield AgentEvent.from_message(message)
        yield AgentEvent.from_result(result)
        return

    from app.llm import llm_call_service

    current_call_ids = {
        str(call.id)
        for call in await llm_call_service.list_calls(task_id=task.id, limit=500)
    }
    raw_prior_call_ids = checkpoint_data.get("prior_llm_call_ids")
    prior_llm_call_ids = (
        {str(call_id) for call_id in as_list(raw_prior_call_ids)}
        if isinstance(raw_prior_call_ids, list)
        else current_call_ids
    )
    try:
        cost_before = float(checkpoint_data.get("cost_before", 0.0))
    except (TypeError, ValueError):
        cost_before = 0.0
    if checkpoint is None:
        cost_before = client.session_cost(await client.get_session(target, session_id))

    resume_run = checkpoint is not None
    run_id = ""
    if checkpoint is not None:
        run_id = checkpoint.runtime_run_id
        try:
            await client.get_run_status(target, run_id)
        except client.HermesRunNotFound:
            if managed or _checkpoint_has_effects(checkpoint):
                if run_context:
                    from app.tools.facade import close_runtime_run_grant
                    await close_runtime_run_grant(run_context)
                lost_result = (
                    checkpoint.result.model_copy(deep=True)
                    if checkpoint.result is not None
                    else ExecutionResult(
                        prompt=human_prompt,
                        system_prompt=context_instructions,
                    )
                )
                lost_result.success = False
                lost_result.result = _message(
                    language, "errors.run_not_found", run_id=run_id
                )
                lost_message = AIMessage(
                    type="text", content=lost_result.result, success=False
                )
                lost_result.messages.append(lost_message)
                yield AgentEvent.from_message(lost_message)
                yield AgentEvent.from_result(lost_result)
                return
            checkpoint = None
            checkpoint_data = {}
            resume_run = False
            prior_llm_call_ids = current_call_ids
            session_id = binding_session_id
            effective_session_id = binding_session_id
            await client.ensure_session(
                target,
                binding_session_id,
                title=f"Galaris — {binding_session_id}",
            )
            cost_before = client.session_cost(
                await client.get_session(target, session_id)
            )

    session_messages = await client.get_session_messages(
        target, effective_session_id
    )
    raw_seen_session_message_ids = checkpoint_data.get("seen_session_message_ids")
    if isinstance(raw_seen_session_message_ids, list):
        seen_session_message_ids = {
            str(message_id) for message_id in as_list(raw_seen_session_message_ids)
        }
    else:
        seen_session_message_ids = (
            _session_seen_through_latest_user(session_messages)
            if checkpoint is not None
            else {
                _session_message_key(message, index)
                for index, message in enumerate(session_messages)
            }
        )

    if checkpoint is None:
        history = _merged_conversation_history(task, session_messages)
        if managed:
            import hashlib
            from app.tools.facade import issue_runtime_run_grant
            run_context = await issue_runtime_run_grant(task)
            checkpoint_data["runtime_run_context"] = get_encryption_service().encrypt(run_context)
            # A lost start reply cannot prove that the runtime did not execute effects.
            # Persist that boundary before contacting the SDK, and never restart it.
            if task.save_checkpoint:
                await task.save_checkpoint(AgentRunCheckpoint(driver_code=task.driver_code,
                    runtime_run_id=hashlib.sha256(run_context.encode()).hexdigest(), status="admitting",
                    data={**checkpoint_data, "execution_strategy": "direct",
                        "cancellation_target": _cancellation_target(target), "session_id": session_id,
                        "effective_session_id": effective_session_id}))
        start_context = {"run_context": run_context} if run_context else {}
        try:
            run_id = await client.start_run(
                target,
                session_id=session_id,
                message=current_message_content,
                system_message=context_instructions,
                conversation_history=history,
                session_key=hermes_session_key,
                **start_context,
            )
        except Exception as e:
            if run_context:
                from app.tools.facade import close_runtime_run_grant
                await close_runtime_run_grant(run_context)
            result = ExecutionResult(
                prompt=human_prompt,
                system_prompt=context_instructions,
                result=_message(language, "errors.run_start_failed", error=e),
                success=False,
                execution_time=time.time() - start_time,
            )
            message = AIMessage(type="text", content=result.result or "", success=False)
            yield AgentEvent.from_message(message)
            yield AgentEvent.from_result(result)
            return

    await _register_active_run(task, target, run_id)
    cancellation_target = _cancellation_target(target)

    # Convert structured SSE events into the same trace contract as the internal harness.
    ai_result = (
        AIResult.model_validate(checkpoint.result.model_dump())
        if checkpoint is not None and checkpoint.result is not None
        else AIResult(prompt=human_prompt, system_prompt=context_instructions)
    )
    ai_result.prompt = human_prompt
    ai_result.system_prompt = context_instructions
    error_text: Optional[str] = None
    terminal_event: str | None = None
    terminal_llm_call_ids: set[str] | None = None
    final_answer = ""
    # Direct runs use Hermes' streamed and persistent session trace. The legacy
    # checkpoint key is read only so an interrupted direct run remains resumable.
    hermes_tool_messages: dict[str, AIMessage] = {}
    raw_tool_indexes = checkpoint_data.get("hermes_tool_message_indexes")
    if not isinstance(raw_tool_indexes, dict):
        raw_tool_indexes = checkpoint_data.get("llm_tool_message_indexes")
    if isinstance(raw_tool_indexes, dict):
        for tool_call_id, raw_index in as_dict(raw_tool_indexes).items():
            if not isinstance(raw_index, int):
                continue
            if 0 <= raw_index < len(ai_result.messages):
                ai_result.messages[raw_index].tool_call_external_id = str(tool_call_id)
                hermes_tool_messages[str(tool_call_id)] = ai_result.messages[raw_index]
    last_persist = 0.0
    runtime_status = checkpoint.status if checkpoint is not None else "running"
    execution_stopped = False
    live_semantic_signatures: dict[int, tuple[str, str, bool, str]] = {}

    # Attribute each inter-event interval to its resulting block so trace timing accounts for
    # reasoning and generation, not only tools.
    last_event_at = time.monotonic()

    def _gap() -> float:
        """Return elapsed time since the previous event and reset the clock."""
        nonlocal last_event_at
        now = time.monotonic()
        elapsed = now - last_event_at
        last_event_at = now
        return elapsed

    async def _persist(force: bool = False) -> None:
        """Persist a partial trace, throttling text deltas."""
        nonlocal last_persist
        now = time.monotonic()
        if not force and now - last_persist < _PERSIST_INTERVAL:
            return
        last_persist = now
        await _sync_hermes_session_messages(
            target,
            effective_session_id,
            ai_result,
            seen_session_message_ids,
            hermes_tool_messages,
            language=language,
        )
        # HTTP checkpoints and live events describe the same cumulative blocks.
        # Persist their identity before publishing either projection, including
        # reasoning and checkpoints resumed from older versions.
        for message in ai_result.messages:
            if not message.stream_id:
                message.stream_id = f"hermes:{run_id}:{uuid4().hex}"
            message.stream_mode = "snapshot"
        if task.save_checkpoint is None:
            return
        tool_indexes = {
            tool_call_id: ai_result.messages.index(message)
            for tool_call_id, message in hermes_tool_messages.items()
            if message in ai_result.messages
        }
        partial_result = ExecutionResult(
            **ai_result.model_dump(exclude={"execution_time"}),
            execution_time=time.time() - start_time,
        )
        partial_result.metadata = {
            **partial_result.metadata,
            "runtime_run_id": run_id,
            "runtime_status": runtime_status,
        }
        await task.save_checkpoint(AgentRunCheckpoint(
            driver_code=task.driver_code,
            runtime_run_id=run_id,
            status=runtime_status,
            result=partial_result,
            data={
                "execution_strategy": "direct",
                "cancellation_target": cancellation_target,
                "session_id": session_id,
                "effective_session_id": effective_session_id,
                "cost_before": cost_before,
                "prior_llm_call_ids": sorted(prior_llm_call_ids),
                "seen_session_message_ids": sorted(seen_session_message_ids),
                "hermes_tool_message_indexes": tool_indexes,
                "runtime_authorization": checkpoint_data.get("runtime_authorization"),
                "runtime_run_context": checkpoint_data.get("runtime_run_context"),
            },
        ))

    def _semantic_updates(*, mark_only: bool = False) -> list[AIMessage]:
        """Return changed semantic blocks while suppressing transient running cards."""

        updates: list[AIMessage] = []
        running_text = _message(language, "tool_running")
        for message in ai_result.messages:
            if message.type != "tool":
                continue
            signature = (
                message.tool_name or "",
                message.content,
                message.success,
                json.dumps(message.tool_arguments or {}, sort_keys=True, default=str),
            )
            key = id(message)
            if live_semantic_signatures.get(key) == signature:
                continue
            live_semantic_signatures[key] = signature
            if not mark_only and message.content != running_text:
                updates.append(message.model_copy(deep=True))
        return updates

    # The run identifier must be durable before Galaris starts consuming its event stream.
    await _persist(force=True)
    _semantic_updates(mark_only=True)

    async for event in _run_lifecycle_events(
        target,
        run_id,
        resume=resume_run,
        language=language,
    ):
        name: str = event["event"]
        data: dict[str, Any] = as_dict(event["data"])

        if name in {"run.completed", "run.failed", "run.cancelled"}:
            execution_stopped = data.get("run_id") == run_id and data.get("execution_stopped") is True

        # Session compaction may return a new tip ID in terminal events.
        effective_session_id = session_binding.effective_session_id(
            effective_session_id, name, data
        )

        if name in ("assistant.delta", "message.delta"):
            delta = data.get("delta") or ""
            if not delta:
                delta = data.get("text") or ""
            if not delta:
                delta = data.get("content") or ""
            if not delta:
                delta = data.get("message") or ""
            if not delta and name == "message.delta":
                delta = data.get("delta") or ""
            if delta:
                # Coalesced text deltas accumulate generation time for later reply folding.
                previous = ai_result.messages[-1] if ai_result.messages else None
                message = AIMessage(
                    type="text", content=delta, execution_time=_gap(),
                    stream_id=(
                        previous.stream_id
                        if previous is not None and previous.type == "text"
                        else f"hermes:{run_id}:{uuid4().hex}"
                    ),
                )
                ai_result.add_message(message)
                block = next(
                    (item for item in ai_result.messages if item.stream_id == message.stream_id),
                    None,
                )
                await _persist()
                if block is None:
                    continue
                yield AgentEvent.from_message(block.model_copy(
                    deep=True, update={"stream_mode": "snapshot"},
                ))

        elif name in ("tool.progress", "reasoning.available"):
            # Add reasoning directly as a synthetic trace block, not a real tool call.
            thought = (data.get("delta") or data.get("text") or "").strip()
            if thought:
                gap = _gap()
                # Hermes may emit reasoning first as text and then as _thinking. Reclassify the
                # duplicate immediately so it never pollutes the answer or visible live trace.
                prev = ai_result.messages[-1] if ai_result.messages else None
                if prev is not None and prev.type == "text" and prev.content.strip() == thought:
                    if prev.content and ai_result.result.endswith(prev.content):
                        ai_result.result = ai_result.result[: -len(prev.content)]
                    prev.type = "tool"
                    prev.tool_name = "thinking"
                    prev.content = thought
                    prev.execution_time += gap
                else:
                    ai_result.messages.append(AIMessage(
                        type="tool",
                        tool_name="thinking",
                        content=thought,
                        execution_time=gap,
                    ))
                await _persist(force=True)
                for semantic_message in _semantic_updates():
                    yield AgentEvent.from_message(semantic_message)

        elif name == "tool.started":
            _gap()
            await _persist(force=True)
            for semantic_message in _semantic_updates():
                yield AgentEvent.from_message(semantic_message)

        elif name in ("tool.completed", "tool.failed"):
            _gap()
            await _persist(force=True)
            for semantic_message in _semantic_updates():
                yield AgentEvent.from_message(semantic_message)

        elif name == "assistant.completed":
            final_answer = data.get("content") or ""

        elif name == "run.completed":
            runtime_status = "completed"
            final_answer = data.get("output") or final_answer
            terminal_event = "completed"
            # Freeze run-owned call IDs before any post-run Hermes skill review starts.
            terminal_llm_call_ids = {
                str(call.id)
                for call in _current_llm_calls(
                    await llm_call_service.list_calls(task_id=task.id, limit=500),
                    prior_llm_call_ids,
                )
            }

        elif name == "authorization.required":
            raw_requests = data.get("authorization_requests")
            if not isinstance(raw_requests, list) or not raw_requests:
                raise PermissionError("Hermes returned no exact pending authorization")
            requests = [UUID(str(identifier)) for identifier in as_list(raw_requests)]
            runtime_status = "waiting_for_authorization"
            await _persist(force=True)
            waiting = ExecutionResult(**ai_result.model_dump(exclude={"success", "execution_time"}),
                success=False, execution_time=time.time() - start_time,
                schema_version="galaris.execution-result/v2", disposition="waiting_for_authorization",
                authorization_requests=requests)
            yield AgentEvent.from_result(waiting)
            return

        elif name == "approval.request":
            from app.agent import get_agent_record
            from app.tools.facade import (
                AuthorizationAction, AuthorizationClosed, AuthorizationRequired,
                claim_action, finish_action,
            )
            from .config_service import execution_snapshot

            request_key = str(data.get("request_id") or "")
            action_digest = str(data.get("action_digest") or "")
            # A redacted command alone cannot bind an agreement to the actual operation.
            if not request_key or len(action_digest) != 64:
                await client.stop_run(target, run_id)
                error_text = "The runtime cannot bind this approval to an exact action."
                terminal_event = "failed"
                break
            current = await client.get_run_status(target, run_id)
            current_approval = as_dict(current.get("approval"))
            if (current.get("status") != "waiting_for_approval"
                or current_approval.get("request_id") != request_key
                or current_approval.get("action_digest") != action_digest):
                continue
            agent = await get_agent_record(task.agent_id)
            if agent is None:
                raise PermissionError("The runtime agent is no longer available")
            live_target = HermesTarget.from_config(await execution_snapshot(agent), agent_code=agent.code)
            action = AuthorizationAction(
                agent_id=task.agent_id, runtime="hermes", source="runtime",
                context_key=f"task:{task.task_id}" if task.task_id else f"principal:hermes:{run_id}",
                callback_key=f"{run_id}:{request_key}", name=str(data.get("tool") or "runtime_action"),
                arguments={"action_digest": action_digest, "command": data.get("command"),
                    "arguments": data.get("arguments"), "arguments_fingerprint": data.get("arguments_fingerprint"),
                    "file_precondition": data.get("file_precondition"),
                    "request_id": request_key, "session": effective_session_id},
                configuration={"url": live_target.url, "model": live_target.model, "credential": live_target.api_key,
                    "runtime_run": run_id}, preview=f"Hermes: {data.get('tool') or 'runtime action'}",
            )
            try:
                permit = await claim_action(action)
            except AuthorizationRequired as required:
                runtime_status = "waiting_for_authorization"
                checkpoint_data["runtime_authorization"] = {"request_id": str(required.request_id)}
                await _persist(force=True)
                waiting = ExecutionResult(
                    **ai_result.model_dump(exclude={"success", "execution_time"}), success=False,
                    execution_time=time.time() - start_time,
                    schema_version="galaris.execution-result/v2", disposition="waiting_for_authorization",
                    authorization_requests=[required.request_id],
                )
                yield AgentEvent.from_result(waiting)
                return
            except AuthorizationClosed:
                await client.submit_run_approval(target, run_id, "deny", request_id=request_key)
            else:
                try:
                    response = await client.submit_run_approval(target, run_id, "once", request_id=request_key)
                except BaseException:
                    await finish_action(permit, outcome="outcome_unknown")
                    raise
                await finish_action(permit, receipt=response)
            checkpoint_data.pop("runtime_authorization", None)
            runtime_status = "running"
            await _persist(force=True)

        elif name == "error":
            error_text = data.get("message") or _message(language, "errors.generic")
        elif name in {"run.failed", "run.cancelled"}:
            runtime_status = str(data.get("status") or name.removeprefix("run."))
            error_text = data.get("error") or _message(language, "errors.generic")
            terminal_event = "failed"
            terminal_llm_call_ids = {
                str(call.id)
                for call in _current_llm_calls(
                    await llm_call_service.list_calls(task_id=task.id, limit=500),
                    prior_llm_call_ids,
                )
            }
        elif name == "run.status":
            runtime_status = str(data.get("status") or "running")
            await _persist(force=True)
        # run.started, message.started, and done carry nothing useful for the trace.

    all_current_llm_calls = _current_llm_calls(
        await llm_call_service.list_calls(task_id=task.id, limit=500),
        prior_llm_call_ids,
    )
    current_llm_calls = (
        [
            call
            for call in all_current_llm_calls
            if str(call.id) in terminal_llm_call_ids
        ]
        if terminal_llm_call_ids is not None
        else all_current_llm_calls
    )
    error_text = _resolve_run_error(
        terminal_event,
        current_llm_calls,
        error_text,
        language,
    )

    success = error_text is None

    # Persist the returned tip in the checkpoint before advancing the binding. A restart in
    # either half of this sequence therefore resumes the compacted transcript.
    await _persist(force=True)
    for semantic_message in _semantic_updates():
        yield AgentEvent.from_message(semantic_message)
    await session_binding.follow_rotation(
        task, session_id, effective_session_id
    )

    # ``assistant.completed`` is authoritative; deltas may contain intermediate text.
    if success and final_answer:
        if any(m.type == "text" for m in ai_result.messages):
            ai_result.result = final_answer
        else:
            # Add a complete response when server-side delta streaming was disabled.
            final_message = AIMessage(type="text", content=final_answer)
            ai_result.add_message(final_message)
            yield AgentEvent.from_message(final_message)
        # Remove a duplicated final answer that Hermes re-emitted as _thinking.
        trimmed = final_answer.strip()
        ai_result.messages = [
            m for m in ai_result.messages
            if not (m.type == "tool" and m.tool_name == "thinking"
                    and trimmed.startswith(m.content))
        ]
    elif error_text:
        # Discard partial or stale session output before surfacing a provider failure.
        ai_result.result = ""
        ai_result.messages = [message for message in ai_result.messages if message.type != "text"]
        error_message = AIMessage(type="text", content=error_text, success=False)
        ai_result.add_message(error_message)
        yield AgentEvent.from_message(error_message)

    # Prefer traced LLM cost; fall back to the Hermes session cost delta.
    cost_after = client.session_cost(
        await client.get_session(target, effective_session_id)
    )
    traced_task_cost = sum(float(call.cost or 0.0) for call in current_llm_calls)
    task_cost = (
        traced_task_cost
        if current_llm_calls
        else max(0.0, cost_after - cost_before)
    )
    ai_result.cost = task_cost
    if current_llm_calls:
        completed_statuses = {"success", "completed"}
        ai_result.usage = AgentUsage(
            input_tokens=sum(max(0, int(call.input_tokens or 0)) for call in current_llm_calls),
            output_tokens=sum(max(0, int(call.output_tokens or 0)) for call in current_llm_calls),
            cache_read_tokens=sum(
                max(0, int(call.cache_read_tokens or 0)) for call in current_llm_calls
            ),
            cache_write_tokens=sum(
                max(0, int(call.cache_write_tokens or 0)) for call in current_llm_calls
            ),
            reasoning_tokens=sum(
                max(0, int(call.reasoning_tokens or 0)) for call in current_llm_calls
            ),
            requests=len(current_llm_calls),
            cost=task_cost,
            token_quality=(
                "exact"
                if all(str(call.status or "").lower() in completed_statuses for call in current_llm_calls)
                else "partial"
            ),
            cost_quality=(
                "estimated"
                if any(bool(call.cost_estimated) for call in current_llm_calls)
                else "exact"
            ),
        )
    else:
        ai_result.usage = AgentUsage(
            cost=task_cost,
            token_quality="unknown",
            cost_quality="partial" if task_cost > 0 else "unknown",
        )

    ai_result.success = success

    result = ExecutionResult(
        **ai_result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - start_time,
    )
    result.metadata = {
        **result.metadata,
        "runtime_run_id": run_id,
        "runtime_status": runtime_status,
        "execution_stopped": execution_stopped,
    }
    if run_context:
        from app.tools.facade import close_runtime_run_grant
        await close_runtime_run_grant(run_context)
    yield AgentEvent.from_result(result)


async def stream(task: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """Stream one run and stop its Hermes process if local execution is cancelled."""
    from .memory_provider import bind_memory_context, clear_memory_context

    memory_context = str(task.metadata.get("memory_context_rendered") or "")
    if memory_context:
        bind_memory_context(
            agent_id=task.agent_id,
            task_id=task.id,
            context=memory_context,
        )
    suspended = False
    try:
        async for event in _stream(task):
            if event.result is not None:
                suspended = event.result.disposition == "waiting_for_authorization"
                event.result.metadata.setdefault("execution_stopped", False)
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        if not suspended:
            await asyncio.shield(_cancel_if_active(task))
        raise
    finally:
        clear_memory_context(agent_id=task.agent_id, task_id=task.id)
        await asyncio.shield(_unregister_active_run(task))


async def run(task: AgentRunRequest) -> ExecutionResult:
    """Consume a non-streaming Hermes run and return its terminal result."""
    terminal: ExecutionResult | None = None
    async for event in stream(task):
        if event.kind == "result":
            terminal = event.result
    if terminal is None:
        raise RuntimeError(
            t("hermes.errors.terminal_result_missing", _task_language(task))
        )
    return terminal
