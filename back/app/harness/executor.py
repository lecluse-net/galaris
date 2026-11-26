"""Execute EXEC tasks with Pydantic AI and the agent's available MCP tools."""

from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from datetime import datetime, timezone
from collections.abc import Callable, Sequence
from typing import Any, AsyncGenerator, AsyncIterator, List, Optional, TypedDict, cast
from uuid import UUID
from core.i18n import is_supported, render_prompt, t
from core.database import get_db_session, release_db_transaction
from core.params import runtime_settings
from app.llm import LLM, LLMCallPurpose, llm_service
from app.agent import HarnessCheckpointError, aggregate_llm_run_usage, assess_checkpoint
from app.agent.contracts import (
    AgentEvent,
    AgentRunRequest,
    AgentSnapshot,
    ExecutionResult,
    HarnessFailure,
    AIMessage,
    AIResult,
)
from app.services.agent_registry import (
    build_agent_tool_advertisement,
    build_tool_context_instructions,
)
from app.process import build_agent_process_advertisement
from .mcp_toolset import build_agent_mcp_toolset
from .task_tool_scope import CONSOLE_RECOVERY_TOOLS, recover_console_receipt, task_receipts_are_current, task_tool_scope
from .tool_results import decode_tool_result, document_creation_receipt
from .runtime import AgentRuntime, create_agent
from .checkpoint import HarnessRunCheckpoint
from .run_control import RunResources
from .prompt import build_harness_system_prompt
from .skills import build_internal_skill_capabilities
from app.messenger import (
    MessagingContext,
    reset_context,
    set_context,
)
from app.messenger.models import File
from app.agent.contracts import TaskMessage as Message
from app.agent.conversation_context import message_history_text


class _NativeHistoryOptions(TypedDict, total=False):
    native_history: str | None
    save_native_history: Callable[[str], None] | None

# Pydantic AI resends history on every model request. Bound it to preserve enough provider
# context for useful work; the current message and attachments have dedicated input.
_HISTORY_MAX_MESSAGES = 30
_HISTORY_MAX_CHARS_PER_MESSAGE = 760
# Minimum interval between partial task snapshots while model text is streaming.
_PROGRESS_PERSIST_INTERVAL = 0.5


def _task_language(task: AgentRunRequest | None) -> str:
    data = task.data if task is not None and isinstance(task.data, dict) else {}
    language = str(data.get("language") or "").strip().lower()
    return language if is_supported(language) else "en"


def _task_is_real_time(task: AgentRunRequest | None) -> bool:
    data = task.data if task is not None and isinstance(task.data, dict) else {}
    return bool(data.get("voice_call"))


def _correlation_ids(
    task: AgentRunRequest | None,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    """Keep durable Task, agent run, and conversation round identities distinct."""

    if task is None:
        return None, None, None
    raw_round_id = task.data.get("conversation_round_id")
    conversation_round_id = (
        UUID(str(raw_round_id))
        if raw_round_id is not None and str(raw_round_id).strip()
        else None
    )
    return task.task_id, task.run_id, conversation_round_id


class AgentExecutor:
    def __init__(self) -> None:
        self.agent_id: int | None
        self.tools: List[Any] = []
        self.mcp_servers: List[Any] = []
        self.capabilities: List[Any] = []
        self.llm: Optional[LLM] = None
        self.system_prompt: str | None = None
        self.agent: Optional[AgentRuntime] = None

    async def load(
        self,
        agent: AgentSnapshot,
        task: AgentRunRequest | None = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent.id
        task_id, agent_run_id, conversation_round_id = _correlation_ids(task)
        # The internal harness and Hermes consume the same aggregated MCP catalog. Pydantic AI
        # uses it in-process while Hermes uses the streamable HTTP endpoint.
        self.tools = []
        allowed_tool_names = task_tool_scope(task).eager_names if task is not None else None
        expected_catalog_version = (
            str(task.data.get("tool_catalog_version") or "").strip()
            if task is not None and isinstance(task.data, dict)
            else ""
        )
        self.mcp_servers = [
            await build_agent_mcp_toolset(
                self.agent_id,
                task_id=task_id,
                eager_tool_names=allowed_tool_names,
                expected_catalog_version=expected_catalog_version or None,
                resources=resources,
            )
        ]
        self.capabilities = await build_internal_skill_capabilities(self.agent_id)
        deep = task is not None and task.deep_session_id is not None
        galaris_tools = ""
        if not deep:
            tool_advertisement = await build_agent_tool_advertisement(
                self.agent_id,
                runtime="internal",
                allowed_tool_names=allowed_tool_names,
                task_id=task_id,
            )
            process_advertisement = await build_agent_process_advertisement(
                self.agent_id,
                tool_advertisement.tool_names,
                relevance_query=task.objective if task is not None else "",
            )
            galaris_tools = "\n\n".join(filter(None, (tool_advertisement.text, process_advertisement)))

        if task is not None:
            self.llm = await llm_service.get_llm(task.model.id)
        else:
            self.llm = await llm_service.get_llm_for_agent(agent)

        run_instructions = task.system_instructions if task is not None else ""
        self.system_prompt = run_instructions if deep else await build_harness_system_prompt(
            agent,
            has_skills=bool(self.capabilities),
            galaris_tools=galaris_tools,
            run_context_instructions=run_instructions,
        )

        if self.llm is None:
            raise RuntimeError(
                render_prompt(
                    t("agent_api.errors.executor_model_missing", _task_language(task)),
                    agent_code=repr(agent.code),
                    effort=task.effort if task is not None else "standard",
                )
            )
        self.agent = await create_agent(
            llm=self.llm,
            tools=self.tools,
            mcp_servers=self.mcp_servers,
            capabilities=self.capabilities,
            system_prompt=self.system_prompt,
            task_id=task_id,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            agent_id=agent.id,
            language=_task_language(task),
            real_time=_task_is_real_time(task),
            purpose=LLMCallPurpose.AGENT_EXEC,
            reasoning_effort=(
                task.model.reasoning_effort if task is not None else None
            ),
            checkpoint=(
                cast(HarnessRunCheckpoint, resources["checkpoint"])
                if resources is not None
                and isinstance(resources.get("checkpoint"), HarnessRunCheckpoint)
                else None
            ),
        )


async def _build_agent_executor(
    agent: AgentSnapshot,
    task: AgentRunRequest | None = None,
    resources: dict[str, Any] | None = None,
) -> AgentExecutor:
    """Build a fresh executor per task so runtime configuration never becomes stale.

    Construction only performs a few database queries; external MCP transports connect
    lazily. Caching could preserve stale tools or a half-built executor after a failure.
    """
    executor = AgentExecutor()
    await executor.load(agent, task=task, resources=resources)
    return executor


def _truncate_history_text(text: str, max_chars: int = _HISTORY_MAX_CHARS_PER_MESSAGE) -> str:
    clean = " ".join(text.strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def _message_timestamp(message: Message) -> str:
    if not message.time:
        return ""
    return datetime.fromtimestamp(message.time, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _message_label(message: Message) -> str:
    return message.sender_display_name or message.sender_external_id or "unknown"


def _prompt_section(tag: str, body: str) -> str:
    """Render one tagged prompt section without a duplicate heading."""
    content = body.strip()
    if not content:
        return ""
    return f"<{tag}>\n{content}\n</{tag}>"


def _is_current_message(task: Any, message: Message, index: int, total: int) -> bool:
    raw_data = getattr(task, "data", None)
    data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
    current_id = str(data.get("id") or data.get("message_id") or "")
    if current_id and (
        str(message.messenger_message_id or "") == current_id
        or message.external_message_id == current_id
    ):
        return True

    # Local OpenAI tasks store the full conversation; the objective already renders its
    # final message.
    if getattr(task, "message_platform", None) == "openai" and index == total - 1:
        return True

    objective = str(getattr(task, "objective", "") or "").strip()
    text = (message.text or "").strip()
    return bool(text and index == total - 1 and text == objective)


def _conversation_messages_before_current(task: Any) -> list[Message]:
    raw_messages: object = getattr(task, "messages", None)
    items = cast(Sequence[object], raw_messages) if isinstance(raw_messages, Sequence) else ()
    messages = [
        message
        if isinstance(message, Message)
        else Message.model_validate(message)
        for message in items
    ]
    total = len(messages)
    return [
        message
        for index, message in enumerate(messages)
        if message_history_text(message)
        and not _is_current_message(task, message, index, total)
    ]


def _previous_conversation_messages(task: Any) -> list[Message]:
    previous = _conversation_messages_before_current(task)
    max_messages = runtime_settings.MESSENGER_SESSION_MAX_MESSAGES
    max_chars = runtime_settings.MESSENGER_SESSION_MAX_CHARS
    bounded_reversed: list[Message] = []
    consumed = 0
    for message in reversed(previous):
        if len(bounded_reversed) >= max_messages or consumed >= max_chars:
            break
        remaining = max_chars - consumed
        text = message.text
        history_text = message_history_text(message)
        if len(text) > remaining:
            text = text[: max(0, remaining - 1)].rstrip() + "…"
            message = message.model_copy(update={"text": text})
        bounded_reversed.append(message)
        consumed += min(len(history_text), remaining)
    bounded_reversed.reverse()
    return bounded_reversed


def _conversation_history_prompt_block(  # pyright: ignore[reportUnusedFunction]
    task: Any, self_id: str | None
) -> str:
    """Render bounded history in the local executor's user prompt."""
    messages = _conversation_messages_before_current(task)
    if not messages:
        return ""

    selected = messages[-_HISTORY_MAX_MESSAGES:]
    lines: list[str] = []
    if len(messages) > len(selected):
        lines.append(f"... {len(messages) - len(selected)} older message(s) omitted.")

    for message in selected:
        timestamp = _message_timestamp(message)
        label = _message_label(message)
        prefix_parts = [part for part in (timestamp, label) if part]
        prefix = " | ".join(prefix_parts)
        lines.append(
            f"- [{prefix}] {_truncate_history_text(message_history_text(message))}"
        )

    return _prompt_section("conversation_history", "\n".join(lines))


async def _stream(
    task: AgentRunRequest,
    lifecycle: RunResources,
) -> AsyncGenerator[AgentEvent, None]:
    """Stream an internal harness run and emit a terminal execution result."""
    if bool(task.task_data.get("conversation_only")):
        from .conversation import stream_voice_conversation

        async for event in stream_voice_conversation(task):
            yield event
        return

    durable_task = task.task_id is not None and task.attempt_id is not None and task.save_checkpoint is not None
    previous = task.resume_checkpoint
    if (durable_task and previous is not None and previous.driver_code == "internal"
            and previous.status == "completed" and previous.result is not None and previous.result.success):
        if previous.runtime_run_id != str(task.run_id) or not assess_checkpoint(previous).resumable:
            raise HarnessCheckpointError("The internal Task checkpoint does not permit recovery.")
        yield AgentEvent.from_result(previous.result.model_copy(deep=True))
        return

    checkpoint = HarnessRunCheckpoint(task)
    recorded_documents = {
        receipt[0]: (effect, receipt[1])
        for effect in checkpoint.effects
        if (receipt := document_creation_receipt(effect)) is not None
    } if task.task_id is not None else {}
    if task.task_id is not None and recorded_documents:
        async with get_db_session():
            if not await task_receipts_are_current(task.agent_id, task.task_id, {"file_create"}, set(recorded_documents)):
                raise HarnessCheckpointError("The internal Task could not verify the recorded document creations.")

    from app.console import ConsoleRunResource, resolve_ssh_connection

    ssh_config = await resolve_ssh_connection(task.agent_id)
    settled_console = {
        (name, scope) for effect in checkpoint.effects
        if effect.get("status") == "completed" and isinstance(name := effect.get("tool_name"), str)
        and name in CONSOLE_RECOVERY_TOOLS and isinstance(scope := effect.get("recovery_scope"), str) and scope
    }
    if task.task_id is not None and settled_console:
        if ssh_config is None or any(scope != ssh_config.recovery_scope for _, scope in settled_console):
            raise HarnessCheckpointError("The internal Task could not verify the original Console connection.")
        async with get_db_session():
            if not await task_receipts_are_current(task.agent_id, task.task_id, {name for name, _ in settled_console}, set(),
                                                   console_scope=ssh_config.recovery_scope):
                raise HarnessCheckpointError("The internal Task could not verify the recorded Console effects.")

    start_time = time.time()
    from app.agent import executor_service

    human_prompt = task.objective
    if task.deep_session_id is None:
        human_prompt = await executor_service.build_task_prompt(task)
        tool_context = await build_tool_context_instructions(task)
        if tool_context:
            human_prompt += "\n\n" + _prompt_section("tool_instructions", tool_context)

    # Resolve room messaging and the identity used to mark assistant history.
    from app.messenger import resolve_task_messaging

    messenger, self_id = await resolve_task_messaging(task)
    self_id = self_id or "galaris-bot"
    message_history = _previous_conversation_messages(task)

    # Rebuild triggering-message attachments from canonical task data; fetch on demand.
    current_message: Optional[Message] = None
    if isinstance(task.data, dict):
        try:
            current_message = Message.model_validate(task.data)
        except Exception:
            current_message = None
    attachments: list[File] = []
    if current_message is not None and current_message.file_ids:
        from sqlalchemy import select

        from core.database import get_db

        rows = list(
            (
                await get_db().scalars(
                    select(File).where(
                        File.id.in_(current_message.file_ids)
                    )
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        attachments = [
            by_id[file_id]
            for file_id in current_message.file_ids
            if file_id in by_id
        ]

    # Scope messenger tools to the current room, message, and attachments.
    _trigger_id = task.data.get("id") if isinstance(task.data, dict) else None
    _ctx_token = set_context(
        MessagingContext(
            messenger=messenger,
            room_id=task.message_group_id,
            connection_id=task.messenger_connection_id,
            message_id=str(_trigger_id) if _trigger_id else None,
            attachments=attachments,
            agent_id=task.agent_id,
            language=str(task.data.get("language") or "") if isinstance(task.data, dict) else "",
        )
    )

    run_resources: dict[str, Any] = {
        "run": lifecycle,
        "checkpoint": checkpoint,
    }
    if ssh_config is not None:
        created_console = ConsoleRunResource(ssh_config)
        checkpoint.recovery_scope = ssh_config.recovery_scope
        run_resources["console"] = created_console

        async def recover_console_effect(effect: dict[str, Any]) -> tuple[bool, Any]:
            name, task_id = effect.get("tool_name"), task.task_id
            if not isinstance(name, str) or name not in CONSOLE_RECOVERY_TOOLS or task_id is None:
                return False, None
            try:
                operation_id = UUID(str(effect["operation_id"]))
            except (KeyError, ValueError):
                return False, None
            scope = created_console.config.recovery_scope
            async with get_db_session():
                if not await task_receipts_are_current(task.agent_id, task_id, {name}, set(), console_scope=scope):
                    return False, None
            receipt = await recover_console_receipt(created_console, name, operation_id)
            if receipt is None:
                return False, None
            async with get_db_session():
                if not await task_receipts_are_current(task.agent_id, task_id, {name}, set(), console_scope=scope):
                    return False, None
            return True, receipt.model_dump(mode="json")

        checkpoint.recover_effect = recover_console_effect

        async def cleanup_console() -> None:
            await created_console.execution.cancel_active()
            await created_console.close()

        lifecycle.add_cleanup("console", cleanup_console)
    try:
        # The task's prompt, messaging and console inputs are resolved. Give
        # back their SQL connection before waiting for local catalog capacity.
        await release_db_transaction()
        agent_executor = await _build_agent_executor(
            task.agent,
            task=task,
            resources=run_resources,
        )
    except BaseException:
        console_resource = run_resources.get("console")
        if isinstance(console_resource, ConsoleRunResource):
            await console_resource.close()
        reset_context(_ctx_token)
        raise

    system_prompt = agent_executor.system_prompt or t(
        "agent_runtime.no_system_prompt",
        _task_language(task),
    )
    prior_result = (
        task.resume_checkpoint.result
        if task.resume_checkpoint is not None
        and task.resume_checkpoint.driver_code == "internal"
        else None
    )
    ai_result = (
        AIResult.model_validate(prior_result.model_dump())
        if prior_result is not None
        else AIResult(
            prompt=human_prompt,
            system_prompt=system_prompt,
        )
    )
    prior_trace_length = len(ai_result.messages)
    checkpoint.result_factory = lambda: ExecutionResult(
        **ai_result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - start_time,
    )
    last_progress_persist = 0.0

    async def record_model_activity() -> None:
        nonlocal last_progress_persist
        record_activity = task.control.record_activity
        if record_activity is None:
            return
        now = time.monotonic()
        if now - last_progress_persist >= _PROGRESS_PERSIST_INTERVAL:
            last_progress_persist = now
            await record_activity()

    async def persist_progress(force: bool = False) -> None:
        """Publish the live trace without creating a resumable run checkpoint."""

        nonlocal last_progress_persist
        if task.save_progress is None:
            return
        now = time.monotonic()
        if not force and now - last_progress_persist < _PROGRESS_PERSIST_INTERVAL:
            return
        last_progress_persist = now
        partial_result = ExecutionResult(
            **ai_result.model_dump(exclude={"execution_time"}),
            execution_time=time.time() - start_time,
        )
        partial_result.metadata = {
            **partial_result.metadata,
            "runtime_status": "running",
        }
        await task.save_progress(partial_result)

    # Driver setup legitimately uses the sequential scheduler session. Release its
    # transaction before Pydantic AI starts parallel branches; native tools and durable
    # callbacks then shadow it with their own short sessions.
    await release_db_transaction()
    runtime_agent = agent_executor.agent
    if runtime_agent is None:
        raise RuntimeError("The internal harness runtime was not initialized.")
    native_history: _NativeHistoryOptions = {}
    if task.deep_session_id is not None:
        native_history = {"native_history": task.deep_native_history, "save_native_history": task.control.save_native_history}
    message_stream = runtime_agent.run(
        prompt=human_prompt,
        message_history=message_history or None,
        group_id=task.message_group_id,
        self_id=self_id,
        current_messages=[current_message] if current_message is not None else None,
        output_transport=None,
        checkpoint=checkpoint,
        on_model_activity=record_model_activity,
        **native_history,
    )
    from . import run_control

    try:
        cooperative_cancel = runtime_agent.request_cancel
    except AttributeError:  # Test doubles and legacy local runtimes remain cancellable.
        cooperative_cancel = None
    await run_control.set_cancel_request(task.run_id, cooperative_cancel)
    await run_control.set_call_recovery_request(task.run_id, getattr(runtime_agent, "request_call_recovery", None))
    try:
        if durable_task and previous is None:
            await checkpoint.begin_run()
        # Make the execution panel (and its live LLM-call subscription) available
        # before the first provider request starts.
        await persist_progress(force=True)
        async with aclosing(message_stream) as messages:
            async for message in messages:
                ai_result.add_message(message.model_copy(deep=True))
                if message.type == "text" and not message.success:
                    ai_result.success = False

                if message.stream_complete is not False or not message.stream_id or not message.success:
                    # The live trace records visible fragments. Tool results and
                    # closed blocks also update the durable result used on reopening.
                    await persist_progress(
                        force=(message.type == "tool" and message.tool_name != "thinking")
                        or not message.success or message.stream_complete is True,
                    )

                # Empty completion markers make a Task block visible without replaying text.
                if message.has_visible_content() or message.stream_complete is True:
                    yield AgentEvent.from_message(message)
    except (Exception, asyncio.CancelledError, GeneratorExit):
        try:
            console_resource = run_resources.get("console")
            if isinstance(console_resource, ConsoleRunResource):
                await asyncio.shield(console_resource.execution.cancel_active())
        finally:
            reset_context(_ctx_token)
        raise
    finally:
        await run_control.set_call_recovery_request(task.run_id, None)
        await run_control.set_cancel_request(task.run_id, None)
        console_resource = run_resources.get("console")
        if isinstance(console_resource, ConsoleRunResource):
            await console_resource.close()

    # Surface budget exhaustion so the task trace explains a partial delivery.
    if getattr(runtime_agent, "budget_exhausted", False):
        ai_result.metadata["budget_exhausted"] = True
    reasoning_recoveries = getattr(runtime_agent, "reasoning_recoveries", 0)
    if reasoning_recoveries:
        ai_result.metadata["reasoning_recoveries"] = reasoning_recoveries
    failure_kind = getattr(runtime_agent, "terminal_failure_kind", None)
    if failure_kind == "reasoning_degeneration":
        ai_result.metadata["reasoning_recovery_exhausted"] = True

    terminal_output = getattr(runtime_agent, "terminal_output", None)
    if ai_result.success and isinstance(terminal_output, str):
        ai_result.reconcile_terminal_text(terminal_output)

    if recorded_documents:
        displayed_documents = {
            uri for message in ai_result.messages
            if message.type == "tool" and message.tool_name == "file_create" and message.success
            and message.tool_result is not None and isinstance(uri := message.tool_result.get("uri"), str)
        }
        # A worker can lose the live tool event after committing the receipt.
        # Keep it in the Task trace even when the resumed model calls no tools.
        ai_result.messages[prior_trace_length:prior_trace_length] = [
            AIMessage(type="tool", tool_name="file_create", content=uri, stream_mode="snapshot",
                      stream_id=f"recovered-tool:{effect.get('operation_id') or effect.get('id') or uri}",
                      tool_call_external_id=call_id if isinstance(call_id := effect.get("tool_call_id"), str) else None,
                      tool_result={key: receipt[key] for key in ("operation", "state", "uri", "revision")})
            for uri, (effect, receipt) in recorded_documents.items() if uri not in displayed_documents
        ]

    if task.task_id is not None and (console_effects := checkpoint.recorded_console_effects()):
        displayed_operations = {
            run_id for message in ai_result.messages if message.type == "tool" and message.success
            and message.tool_result is not None and isinstance(run_id := message.tool_result.get("run_id"), str)
        }
        console_trace: list[AIMessage] = []
        for effect in console_effects:
            payload = decode_tool_result(effect.get("result"))
            operation_id = effect.get("operation_id")
            if not isinstance(payload, dict) or not isinstance(operation_id, str) or operation_id in displayed_operations:
                continue
            receipt = cast(dict[str, object], payload)
            if receipt.get("run_id") != operation_id:
                continue
            call_id = effect.get("tool_call_id")
            console_trace.append(AIMessage(
                type="tool", tool_name=str(effect["tool_name"]), content=str(receipt.get("stdout") or "")[:500],
                stream_id=f"recovered-tool:{operation_id}", stream_mode="snapshot",
                tool_call_external_id=call_id if isinstance(call_id, str) else None,
                tool_result={key: receipt[key] for key in ("run_id", "status", "exit_code") if key in receipt},
            ))
        ai_result.messages[prior_trace_length:prior_trace_length] = console_trace

    console_failure = checkpoint.console_failure()
    if console_failure is None:
        await executor_service.recover_after_verified_delivery(task, ai_result, failure_kind=failure_kind)
    else:
        ai_result.success = False

    result = ExecutionResult(
        **ai_result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - start_time,
        failure=console_failure or (HarnessFailure(code="runtime", message=str(getattr(runtime_agent, "error", ""))[:4000])
                                   if failure_kind == "document_read_loop" else None),
    )
    authorization_requests = getattr(runtime_agent, "authorization_requests", [])
    if getattr(runtime_agent, "waiting_for_children", False) and not authorization_requests:
        result.success = False
        result.disposition = "waiting_for_children"
        result.schema_version = "galaris.execution-result/v2"
        result.result = ""
    if authorization_requests:
        result.success = False
        result.disposition = "waiting_for_authorization"
        result.authorization_requests = list(authorization_requests)
        result.schema_version = "galaris.execution-result/v2"

    profile_fallback = getattr(runtime_agent, "profile_fallback_used", False) is True
    if profile_fallback or (durable_task and result.disposition == "waiting_for_children"):
        accounting = await aggregate_llm_run_usage(task.run_id, agent_id=task.agent_id)
        if accounting is not None:
            result.usage, result.cost = accounting
    if profile_fallback:
        result.metadata["profile_fallback_used"] = True

    # Release task-scoped messenger context.
    reset_context(_ctx_token)
    if durable_task and (result.success or result.disposition == "waiting_for_children"):
        await checkpoint.finish_run(result)
    yield AgentEvent.from_result(result)


async def stream(task: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """Register one cancellable harness run around its complete resource lifecycle."""

    from . import run_control

    lifecycle = RunResources()
    await run_control.register(task.run_id, task.task_id, lifecycle)
    try:
        async with aclosing(_stream(task, lifecycle)) as events:
            async for event in events:
                yield event
    finally:
        await asyncio.shield(lifecycle.close())
        await run_control.unregister(task.run_id, task.task_id)


async def run(task: AgentRunRequest) -> ExecutionResult:
    """Consume the webhook stream and return its terminal result."""
    terminal: ExecutionResult | None = None
    async for event in stream(task):
        if event.kind == "result":
            terminal = event.result
    if terminal is None:
        data = task.data if isinstance(task.data, dict) else {}
        language = str(data.get("language") or "").strip().lower()
        raise RuntimeError(t(
            "agent_api.errors.harness_terminal_result_missing",
            language if is_supported(language) else None,
        ))
    return terminal
