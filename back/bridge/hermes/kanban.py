"""Retained adapter for resumed or explicitly re-enabled Hermes Kanban runs."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from loguru import logger

from app.agent.contracts import (
    AIMessage,
    AIResult,
    AgentEvent,
    AgentRunCheckpoint,
    AgentRunRequest,
    ExecutionResult,
)
from core.i18n import is_supported, render_prompt, t
from core.util import as_list

from .client import HermesTarget
from .manager import manager
from .prompt import build_context_instructions, hermes_context_values


_POLL_INTERVAL = 1.0
_DISPATCH_RETRY_INTERVAL = 10.0
_TERMINAL_TRACE_ATTEMPTS = 4
_TERMINAL_TRACE_RETRY_INTERVAL = 0.25
_TERMINAL_STATUSES = frozenset({"done", "blocked", "review", "archived"})
_STRATEGY = "kanban"


@dataclass(frozen=True)
class _KanbanConfiguration:
    transport: str
    board: str
    assignee: str
    workspace_path: str


@dataclass
class _ActiveKanbanRun:
    agent_code: str
    transport: str
    create_payload: dict[str, Any]
    card_id: str | None = None


_ACTIVE_RUNS: dict[UUID, _ActiveKanbanRun] = {}


def _language(request: AgentRunRequest) -> str:
    value = str(request.task_data.get("language") or "en").strip().lower()
    return value if is_supported(value) else "en"


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"hermes.{key}", language), **values)


def _string_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _configuration(
    request: AgentRunRequest,
    *,
    checkpoint_data: Mapping[str, Any] | None = None,
) -> _KanbanConfiguration:
    config = (
        _string_mapping(checkpoint_data)
        if checkpoint_data is not None
        else _string_mapping(request.agent.driver_config.get("kanban"))
    )
    transport = str(config.get("transport") or "").strip().lower()
    board = str(config.get("board") or "").strip().lower()
    assignee = str(config.get("assignee") or "").strip().lower()
    workspace_path = str(config.get("workspace_path") or "").strip()
    if transport != "legacy":
        raise ValueError(
            _message(
                _language(request),
                "errors.kanban_transport_invalid",
                transport=transport or "?",
            )
        )
    if board != "default":
        raise ValueError(
            _message(
                _language(request),
                "errors.kanban_board_unsupported",
                board=board or "?",
            )
        )
    if not assignee or not workspace_path.startswith("/opt/data/"):
        raise ValueError(
            _message(_language(request), "errors.kanban_configuration_incomplete")
        )
    return _KanbanConfiguration(
        transport=transport,
        board=board,
        assignee=assignee,
        workspace_path=workspace_path,
    )


def _checkpoint(request: AgentRunRequest) -> AgentRunCheckpoint | None:
    checkpoint = request.resume_checkpoint
    if checkpoint is None or checkpoint.driver_code != request.driver_code:
        return None
    data = _string_mapping(checkpoint.data)
    return checkpoint if data.get("execution_strategy") == _STRATEGY else None


def _card(detail: Mapping[str, Any]) -> dict[str, Any]:
    return _string_mapping(detail.get("task"))


def _card_id(detail: Mapping[str, Any]) -> str:
    identifier = str(_card(detail).get("id") or "").strip().lower()
    if not identifier:
        raise RuntimeError("Hermes Kanban returned no task id.")
    return identifier


def _register_active(request: AgentRunRequest, active: _ActiveKanbanRun) -> None:
    _ACTIVE_RUNS[request.run_id] = active
    _ACTIVE_RUNS[request.id] = active


def _unregister_active(request: AgentRunRequest) -> None:
    for identifier in {request.run_id, request.id}:
        _ACTIVE_RUNS.pop(identifier, None)


async def cancel_if_active(run_id: UUID) -> bool:
    """Cancel a registered card and report whether this module owned the run."""

    active = _ACTIVE_RUNS.get(run_id)
    if active is None:
        return False
    if active.card_id is None:
        created = await manager.create_kanban_task(
            active.agent_code,
            transport=active.transport,
            payload=active.create_payload,
        )
        active.card_id = _card_id(created)
    await manager.cancel_kanban_task(
        active.agent_code,
        active.card_id,
        transport=active.transport,
        reason="Galaris execution cancelled",
    )
    return True


async def _cancel_if_active(request: AgentRunRequest) -> None:
    try:
        await cancel_if_active(request.id)
    except Exception:
        logger.exception("Hermes Kanban cancellation failed for task={}", request.id)


async def _build_card_body(
    request: AgentRunRequest,
) -> tuple[str, str, str]:
    """Render the immutable Galaris prompt into a self-contained Kanban card."""

    from app.agent import executor_service

    memory_context = str(request.metadata.get("memory_context_rendered") or "")
    prompt_shared_context = request.shared_context
    if memory_context:
        if prompt_shared_context == memory_context:
            prompt_shared_context = ""
        elif prompt_shared_context.endswith(f"\n\n{memory_context}"):
            prompt_shared_context = prompt_shared_context[: -(len(memory_context) + 2)]
    prompt_request = replace(request, shared_context=prompt_shared_context)
    human_prompt = await executor_service.build_task_prompt(
        prompt_request,
        extra_context=hermes_context_values(request),
    )
    system_prompt = await build_context_instructions(
        request.agent,
        run_context_instructions=request.system_instructions,
    )

    correlation = {
        "task_id": str(request.id),
        "run_id": str(request.run_id),
        "driver_code": request.driver_code,
        "execution_strategy": request.execution_strategy,
        "effort": request.effort,
        "llm_id": request.model.id,
        "llm_code": request.model.code,
    }
    sections = [
        (
            "This card is a subordinate execution handle for the Galaris Task identified "
            "below. Galaris remains the source of truth for scheduling and final state."
        ),
        "<galaris-run-context>\n"
        + json.dumps(correlation, ensure_ascii=False, indent=2)
        + "\n</galaris-run-context>",
        f"<galaris-system-instructions>\n{system_prompt}\n</galaris-system-instructions>",
    ]
    if request.conversation_history:
        sections.append(
            "<galaris-conversation-history>\n"
            + json.dumps(
                list(request.conversation_history),
                ensure_ascii=False,
                default=str,
            )
            + "\n</galaris-conversation-history>"
        )
    sections.append(f"<galaris-task>\n{human_prompt}\n</galaris-task>")
    return human_prompt, system_prompt, "\n\n".join(sections)


def _title(request: AgentRunRequest) -> str:
    raw = request.label.strip() or request.objective.strip() or f"Task {request.id}"
    compact = " ".join(raw.split())[:220]
    return f"Galaris — {compact}"


def _create_payload(
    request: AgentRunRequest,
    config: _KanbanConfiguration,
    *,
    card_body: str,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "title": _title(request),
        "body": card_body,
        "assignee": config.assignee,
        "tenant": "galaris",
        "priority": 100,
        "workspace_kind": "dir",
        "workspace_path": config.workspace_path,
        "idempotency_key": idempotency_key,
        "triage": False,
        "goal_mode": False,
    }


async def _save_checkpoint(
    request: AgentRunRequest,
    *,
    runtime_run_id: str,
    status: str,
    config: _KanbanConfiguration,
    idempotency_key: str,
    prior_call_ids: set[str],
    result: ExecutionResult | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    if request.save_checkpoint is None:
        return
    card = _card(detail or {})
    await request.save_checkpoint(
        AgentRunCheckpoint(
            driver_code=request.driver_code,
            runtime_run_id=runtime_run_id,
            status=status,
            result=result,
            data={
                "execution_strategy": _STRATEGY,
                "transport": config.transport,
                "board": config.board,
                "assignee": config.assignee,
                "workspace_path": config.workspace_path,
                "idempotency_key": idempotency_key,
                "prior_llm_call_ids": sorted(prior_call_ids),
                "kanban_run_id": card.get("current_run_id"),
                "kanban_failures": card.get("consecutive_failures", 0),
            },
        )
    )


def _latest_run(detail: Mapping[str, Any]) -> dict[str, Any]:
    runs = as_list(detail.get("runs"))
    for raw in reversed(runs):
        if isinstance(raw, Mapping):
            return _string_mapping(cast(object, raw))
    return {}


def _worker_session_id(detail: Mapping[str, Any]) -> str:
    """Return the worker transcript stamped by Hermes on a terminal run."""

    for raw in reversed(as_list(detail.get("runs"))):
        if not isinstance(raw, Mapping):
            continue
        run = _string_mapping(cast(object, raw))
        metadata = _string_mapping(run.get("metadata"))
        session_id = str(metadata.get("worker_session_id") or "").strip()
        if session_id:
            return session_id
    return ""


def _trace_signature(result: ExecutionResult) -> str:
    """Ignore elapsed wall time while detecting an observable trace change."""

    return json.dumps(
        {
            "messages": [message.model_dump(mode="json") for message in result.messages],
            "cost": result.cost,
            "source": result.metadata.get("trace_source"),
            "runtime_status": result.metadata.get("runtime_status"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def _provisional_result(
    request: AgentRunRequest,
    detail: Mapping[str, Any],
    *,
    human_prompt: str,
    system_prompt: str,
    prior_call_ids: set[str],
    started_at: float,
) -> ExecutionResult:
    """Project proxy telemetry when available, otherwise expose coarse Kanban progress."""

    from app.llm import llm_call_service
    from . import executor
    from . import driver as hermes_driver

    language = _language(request)
    result = AIResult(prompt=human_prompt, system_prompt=system_prompt)
    tool_messages: dict[str, AIMessage] = {}
    project_tool_calls = hermes_driver.HERMES_HIGH_KANBAN_ENABLED
    if project_tool_calls:
        await executor.sync_llm_tool_messages(
            request.id,
            result,
            tool_messages,
            excluded_call_ids=prior_call_ids,
            language=language,
        )
    calls = [
        call
        for call in await llm_call_service.list_calls(task_id=request.id, limit=500)
        if str(getattr(call, "id", "") or "") not in prior_call_ids
    ]

    ordered_messages: list[AIMessage] = []
    ordered_tool_ids: set[str] = set()
    for call in calls:
        call_id = str(getattr(call, "id", "") or "")
        reasoning = str(getattr(call, "reasoning", "") or "").strip()
        if reasoning:
            ordered_messages.append(
                AIMessage(type="tool", tool_name="thinking", content=reasoning)
            )
        raw_tools = (
            as_list(getattr(call, "tool_calls", []))
            if project_tool_calls
            else []
        )
        for index, raw_tool in enumerate(raw_tools):
            tool = _string_mapping(raw_tool)
            tool_call_id = str(tool.get("id") or f"{call_id}:{index}")
            message = tool_messages.get(tool_call_id)
            if message is None:
                continue
            ordered_messages.append(message)
            ordered_tool_ids.add(tool_call_id)

        error = str(getattr(call, "error", "") or "").strip()
        if error and not reasoning and not raw_tools:
            ordered_messages.append(
                AIMessage(
                    type="tool",
                    tool_name="llm_call",
                    content=error,
                    success=False,
                )
            )

    # A call may appear between the two durable reads above. Keep it visible now;
    # the next poll will place it in its exact chronological position.
    ordered_messages.extend(
        message
        for tool_call_id, message in tool_messages.items()
        if tool_call_id not in ordered_tool_ids
    )
    result.messages = ordered_messages
    result.cost = sum(float(getattr(call, "cost", 0.0) or 0.0) for call in calls)

    card = _card(detail)
    status = str(card.get("status") or "").strip().lower()
    trace_source = "llm_calls" if ordered_messages else "kanban"
    if not ordered_messages:
        result.add_message(
            AIMessage(
                type="tool",
                tool_name="hermes_kanban",
                tool_arguments={
                    "task_id": str(card.get("id") or ""),
                    "status": status,
                    "run_id": card.get("current_run_id"),
                },
                content=_message(language, "tool_running"),
            )
        )

    partial = ExecutionResult(
        **result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - started_at,
    )
    partial.metadata = {
        **partial.metadata,
        "runtime_kind": _STRATEGY,
        "runtime_run_id": str(card.get("id") or ""),
        "runtime_status": status,
        "kanban_run_id": card.get("current_run_id") or _latest_run(detail).get("id"),
        "trace_source": trace_source,
        "trace_provisional": True,
        "trace_reconciled": False,
    }
    return partial


async def _canonical_session_trace(
    request: AgentRunRequest,
    detail: Mapping[str, Any],
    *,
    human_prompt: str,
    system_prompt: str,
) -> AIResult | None:
    """Recover the terminal worker transcript without making it a run dependency."""

    session_id = _worker_session_id(detail)
    if not session_id:
        return None
    try:
        target = HermesTarget.from_config(
            request.agent.driver_config,
            agent_code=request.agent.code,
        )
        from . import executor

        result = AIResult(prompt=human_prompt, system_prompt=system_prompt)
        seen_message_ids: set[str] = set()
        tool_messages: dict[str, AIMessage] = {}
        for attempt in range(_TERMINAL_TRACE_ATTEMPTS):
            session = await executor.client.get_session(target, session_id)
            # Reuse the direct adapter's pure transcript normalizer without entering
            # its run/session lifecycle; only this Kanban code path calls it here.
            await executor._sync_hermes_session_messages(  # pyright: ignore[reportPrivateUsage]
                target,
                session_id,
                result,
                seen_message_ids,
                tool_messages,
                language=_language(request),
            )
            if (
                session is None
                or session.get("ended_at") is not None
                or attempt == _TERMINAL_TRACE_ATTEMPTS - 1
            ):
                break
            await asyncio.sleep(_TERMINAL_TRACE_RETRY_INTERVAL)
    except Exception:
        logger.exception(
            "Hermes Kanban terminal trace recovery failed for task={} session={}",
            request.id,
            session_id,
        )
        return None
    return result if result.messages else None


def _terminal_text(
    detail: Mapping[str, Any],
    *,
    status: str,
    language: str,
) -> str:
    card = _card(detail)
    run = _latest_run(detail)
    candidates = (
        card.get("result"),
        detail.get("latest_summary"),
        card.get("latest_summary"),
        run.get("summary"),
        run.get("error"),
        card.get("last_failure_error"),
    )
    text = next((str(item).strip() for item in candidates if str(item or "").strip()), "")
    if status == "done":
        return text or _message(language, "kanban_completed_without_summary")
    return _message(
        language,
        "errors.kanban_terminal_failure",
        status=status,
        reason=text or _message(language, "errors.generic"),
    )


async def _terminal_result(
    request: AgentRunRequest,
    detail: Mapping[str, Any],
    *,
    human_prompt: str,
    system_prompt: str,
    prior_call_ids: set[str],
    started_at: float,
    provisional: ExecutionResult,
) -> ExecutionResult:
    from app.llm import llm_call_service

    card = _card(detail)
    status = str(card.get("status") or "").strip().lower()
    success = status == "done"
    language = _language(request)
    text = _terminal_text(detail, status=status, language=language)
    canonical = await _canonical_session_trace(
        request,
        detail,
        human_prompt=human_prompt,
        system_prompt=system_prompt,
    )
    if canonical is not None:
        result = canonical
        trace_source = "hermes_session"
        trace_reconciled = True
    elif provisional.metadata.get("trace_source") == "llm_calls":
        result = AIResult.model_validate(provisional.model_dump())
        trace_source = "llm_calls"
        trace_reconciled = False
    else:
        # The running-status placeholder is not part of a terminal trace.
        result = AIResult(prompt=human_prompt, system_prompt=system_prompt)
        trace_source = "kanban"
        trace_reconciled = False

    lifecycle_tool = "kanban_complete" if success else "kanban_block"
    if lifecycle_tool not in result.tools_used:
        result.add_message(
            AIMessage(
                type="tool",
                tool_name=lifecycle_tool,
                tool_arguments={
                    "task_id": str(card.get("id") or ""),
                    "status": status,
                    "run_id": card.get("current_run_id") or _latest_run(detail).get("id"),
                },
                content=text,
                success=success,
            )
        )
    result.add_message(AIMessage(type="text", content=text, success=success))
    calls = await llm_call_service.list_calls(task_id=request.id, limit=500)
    result.cost = sum(
        float(getattr(call, "cost", 0.0) or 0.0)
        for call in calls
        if str(getattr(call, "id", "") or "") not in prior_call_ids
    )
    result.success = success
    terminal = ExecutionResult(
        **result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - started_at,
    )
    terminal.metadata = {
        **terminal.metadata,
        "runtime_kind": _STRATEGY,
        "runtime_run_id": str(card.get("id") or ""),
        "runtime_status": status,
        "kanban_run_id": card.get("current_run_id") or _latest_run(detail).get("id"),
        "trace_source": trace_source,
        "trace_provisional": False,
        "trace_reconciled": trace_reconciled,
    }
    return terminal


async def _stream(request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    started_at = time.time()
    checkpoint = _checkpoint(request)
    checkpoint_data = _string_mapping(checkpoint.data) if checkpoint is not None else {}
    config = _configuration(
        request,
        checkpoint_data=checkpoint_data if checkpoint is not None else None,
    )
    human_prompt, system_prompt, card_body = await _build_card_body(request)

    from app.llm import llm_call_service

    raw_prior_call_ids = checkpoint_data.get("prior_llm_call_ids")
    if isinstance(raw_prior_call_ids, list):
        prior_call_ids = {str(item) for item in as_list(raw_prior_call_ids)}
    else:
        prior_call_ids = {
            str(call.id)
            for call in await llm_call_service.list_calls(task_id=request.id, limit=500)
        }

    idempotency_key = str(checkpoint_data.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = f"galaris:{request.id}:{request.run_id}"
    create_payload = _create_payload(
        request,
        config,
        card_body=card_body,
        idempotency_key=idempotency_key,
    )

    card_id = ""
    if checkpoint is not None and not checkpoint.runtime_run_id.startswith("pending:"):
        card_id = checkpoint.runtime_run_id
    if not card_id:
        await _save_checkpoint(
            request,
            runtime_run_id=f"pending:{idempotency_key}",
            status="creating",
            config=config,
            idempotency_key=idempotency_key,
            prior_call_ids=prior_call_ids,
            result=ExecutionResult(prompt=human_prompt, system_prompt=system_prompt),
        )

    active = _ActiveKanbanRun(
        agent_code=request.agent.code,
        transport=config.transport,
        create_payload=create_payload,
        card_id=card_id or None,
    )
    _register_active(request, active)

    if not card_id:
        created = await manager.create_kanban_task(
            request.agent.code,
            transport=config.transport,
            payload=create_payload,
        )
        card_id = _card_id(created)
        active.card_id = card_id
        created_status = str(_card(created).get("status") or "ready").strip().lower()
        await _save_checkpoint(
            request,
            runtime_run_id=card_id,
            status=created_status,
            config=config,
            idempotency_key=idempotency_key,
            prior_call_ids=prior_call_ids,
            result=ExecutionResult(prompt=human_prompt, system_prompt=system_prompt),
            detail=created,
        )

    # This is idempotent and closes the crash window between create and the
    # gateway's periodic dispatcher tick. On resume it also wakes a ready card.
    await manager.dispatch_kanban(request.agent.code, transport=config.transport)
    last_dispatch_at = time.monotonic()

    last_signature: tuple[str, object, object] | None = None
    last_trace_signature: str | None = None
    provisional = ExecutionResult(prompt=human_prompt, system_prompt=system_prompt)
    detail: dict[str, Any]
    while True:
        detail = await manager.get_kanban_task(
            request.agent.code,
            card_id,
            transport=config.transport,
        )
        card = _card(detail)
        status = str(card.get("status") or "").strip().lower()
        if not status:
            raise RuntimeError("Hermes Kanban returned a card without status.")
        signature = (
            status,
            card.get("current_run_id"),
            card.get("consecutive_failures", 0),
        )
        provisional = await _provisional_result(
            request,
            detail,
            human_prompt=human_prompt,
            system_prompt=system_prompt,
            prior_call_ids=prior_call_ids,
            started_at=started_at,
        )
        trace_signature = _trace_signature(provisional)
        status_changed = signature != last_signature
        trace_changed = trace_signature != last_trace_signature
        checkpoint_saved = False
        if status_changed:
            await _save_checkpoint(
                request,
                runtime_run_id=card_id,
                status=status,
                config=config,
                idempotency_key=idempotency_key,
                prior_call_ids=prior_call_ids,
                result=provisional,
                detail=detail,
            )
            checkpoint_saved = request.save_checkpoint is not None
            last_signature = signature
        if trace_changed and not checkpoint_saved and request.save_progress is not None:
            await request.save_progress(provisional)
        last_trace_signature = trace_signature
        if status in _TERMINAL_STATUSES:
            break
        if (
            status == "ready"
            and time.monotonic() - last_dispatch_at >= _DISPATCH_RETRY_INTERVAL
        ):
            # A first nudge can legitimately hit the Kanban concurrency cap.
            # Retry while the card is ready so deployments that disable the
            # gateway's periodic dispatcher still make progress.
            await manager.dispatch_kanban(
                request.agent.code,
                transport=config.transport,
            )
            last_dispatch_at = time.monotonic()
        await asyncio.sleep(_POLL_INTERVAL)

    terminal = await _terminal_result(
        request,
        detail,
        human_prompt=human_prompt,
        system_prompt=system_prompt,
        prior_call_ids=prior_call_ids,
        started_at=started_at,
        provisional=provisional,
    )
    await _save_checkpoint(
        request,
        runtime_run_id=card_id,
        status=str(_card(detail).get("status") or ""),
        config=config,
        idempotency_key=idempotency_key,
        prior_call_ids=prior_call_ids,
        result=terminal,
        detail=detail,
    )
    for message in terminal.messages:
        yield AgentEvent.from_message(message)
    yield AgentEvent.from_result(terminal)


async def stream(request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """Stream a high-effort card and archive it when local execution is cancelled."""

    from .memory_provider import bind_memory_context, clear_memory_context

    memory_context = str(request.metadata.get("memory_context_rendered") or "")
    if memory_context:
        bind_memory_context(
            agent_id=request.agent_id,
            task_id=request.id,
            context=memory_context,
        )
    try:
        async for event in _stream(request):
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        await asyncio.shield(_cancel_if_active(request))
        raise
    finally:
        clear_memory_context(agent_id=request.agent_id, task_id=request.id)
        _unregister_active(request)


async def run(request: AgentRunRequest) -> ExecutionResult:
    """Consume the Kanban stream and return its unique terminal result."""

    terminal: ExecutionResult | None = None
    async for event in stream(request):
        if event.kind == "result":
            terminal = event.result
    if terminal is None:
        raise RuntimeError(t("hermes.errors.terminal_result_missing", _language(request)))
    return terminal
