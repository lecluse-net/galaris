"""Execute EXEC tasks with Pydantic AI and the agent's available MCP tools."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Any, AsyncIterator, List, Optional, cast
from uuid import UUID
from core.i18n import is_supported, render_prompt, t
from core.params import runtime_settings
from app.llm import LLM, LLMCallPurpose, llm_service
from app.agent.contracts import (
    AgentEvent,
    AgentRunRequest,
    AgentSnapshot,
    ExecutionResult,
    AIResult,
    AIMessage,
)
from app.tools.agent_registry import (
    build_agent_tool_advertisement,
    build_tool_context_instructions,
)
from app.process import build_agent_process_advertisement
from .mcp_toolset import build_agent_mcp_toolset
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

# Pydantic AI resends history on every model request. Bound it to preserve enough provider
# context for useful work; the current message and attachments have dedicated input.
_HISTORY_MAX_MESSAGES = 30
_HISTORY_MAX_CHARS_PER_MESSAGE = 760
# Minimum interval between partial task snapshots while model text is streaming.
_PROGRESS_PERSIST_INTERVAL = 0.5

_DELIVERY_TOOLS = frozenset(
    {
        "messenger_room_send_message",
        "messenger_send_message_to_user",
        "messenger_room_send_file",
        "messenger_send_file_to_user",
    }
)
_SCOPED_PROCESS_TOOLS = frozenset(
    {
        "process_list",
        "process_get",
        "process_start",
        "process_list_runs",
        "process_get_run",
        "process_analyze_run",
    }
)
_SCOPED_TOOL_COMPANIONS: dict[str, frozenset[str]] = {
    # A writer without its read/inspection companions leaves an executor unable to
    # verify the artifact it just produced. These are capability dependencies, not
    # driver-specific branches.
    "file_write": frozenset(
        {"file_schemes", "file_list", "file_info", "file_read"}
    ),
    "file_create": frozenset(
        {"file_schemes", "file_list", "file_info", "file_read"}
    ),
    "file_append": frozenset(
        {"file_schemes", "file_list", "file_info", "file_read"}
    ),
    "file_edit": frozenset(
        {"file_schemes", "file_list", "file_info", "file_read"}
    ),
    # A human name is not an SMTP address. Keep the governed Memory lookup
    # functions in every planner-narrowed run that is allowed to send Mail.
    "mail_send": frozenset({"file_search", "file_read"}),
}


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


def _scoped_tool_names(task: AgentRunRequest) -> set[str] | None:
    """Return the planner or briefing tool scope when one exists."""
    selected: set[str] = set()
    data = task.data if isinstance(task.data, dict) else {}
    raw_plan_tools = data.get("plan_tools")
    if isinstance(raw_plan_tools, list):
        selected.update(
            str(item).strip()
            for item in cast(list[Any], raw_plan_tools)
            if str(item).strip()
        )
    # Legacy plans created before ``plan_tools`` often name exact MCP functions in their
    # objectives. Extract only snake_case identifiers; the toolset drops unknown names.
    if task.parent_id is not None and not selected:
        selected.update(
            re.findall(
                r"(?<![\w])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)(?![\w])",
                task.objective or "",
            )
        )

    if data.get("goal_referrer_type") == "AGENT":
        selected.add("task_run")

    briefing = task.get_briefing_result()
    if briefing is not None and briefing.success:
        selected.update(
            choice.identifier.strip()
            for choice in briefing.choices
            if choice.kind == "tool" and choice.identifier.strip()
        )
        if any(choice.kind == "process" for choice in briefing.choices):
            selected.update(_SCOPED_PROCESS_TOOLS)

    if not selected:
        return None
    # A planned leaf may only publish when its materialized step explicitly permits it.
    # Delivery tools are no longer unconditional support capabilities: adding them behind
    # the planner's back caused intermediate artifacts to be sent and consumed too early.
    if task.parent_id is not None and data.get("delivery_policy") != "required":
        selected.difference_update(_DELIVERY_TOOLS)
    raw_delivery_recovery = data.get("delivery_recovery")
    delivery_recovery = (
        cast(dict[str, Any], raw_delivery_recovery)
        if isinstance(raw_delivery_recovery, dict)
        else None
    )
    if (
        delivery_recovery is not None
        and delivery_recovery.get("status") == "running"
    ):
        # Recovery is intentionally narrower than an ordinary planned leaf: the final
        # artifact already exists and only the exact recorded delivery may be retried.
        # Exposing process discovery or mutation companions here would reopen the work
        # and make a duplicate or altered delivery possible.
        return selected
    for tool_name in tuple(selected):
        selected.update(_SCOPED_TOOL_COMPANIONS.get(tool_name, ()))
    # Personal process discovery is a core executor capability, including inside a planner-
    # narrowed leaf. This expands only the task scope: connection, per-function, and runtime
    # authorization are still applied by the shared MCP projection before prompt advertising.
    return selected | set(_SCOPED_PROCESS_TOOLS)


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
        allowed_tool_names = _scoped_tool_names(task) if task is not None else None
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
        tool_advertisement = await build_agent_tool_advertisement(
            self.agent_id,
            runtime="internal",
            allowed_tool_names=allowed_tool_names,
        )
        process_advertisement = await build_agent_process_advertisement(
            self.agent_id,
            tool_advertisement.tool_names,
            relevance_query=task.objective if task is not None else "",
        )
        galaris_tools = "\n\n".join(
            section
            for section in (tool_advertisement.text, process_advertisement)
            if section
        )

        if task is not None:
            self.llm = await llm_service.get_llm(task.model.id)
        else:
            self.llm = await llm_service.get_llm_for_agent(agent)

        # This harness runtime is always Pydantic AI; driver selection happens above it.
        self.system_prompt = await build_harness_system_prompt(
            agent,
            has_skills=bool(self.capabilities),
            galaris_tools=galaris_tools,
            run_context_instructions=(
                task.system_instructions if task is not None else ""
            ),
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
) -> AsyncIterator[AgentEvent]:
    """Stream an internal harness run and emit a terminal execution result."""
    if bool(task.task_data.get("conversation_only")):
        from .conversation import stream_voice_conversation

        async for event in stream_voice_conversation(task):
            yield event
        return

    start_time = time.time()
    from app.agent import executor_service

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

    checkpoint = HarnessRunCheckpoint(task)
    run_resources: dict[str, Any] = {
        "run": lifecycle,
        "checkpoint": checkpoint,
    }
    from app.console import ConsoleRunResource, resolve_ssh_connection
    ssh_config = await resolve_ssh_connection(task.agent_id)
    if ssh_config is not None:
        import hashlib
        import json

        checkpoint.recovery_scope = hashlib.sha256(
            json.dumps([ssh_config.connection_id, ssh_config.host, ssh_config.port,
                        ssh_config.username, ssh_config.known_host_key], separators=(",", ":")).encode()
        ).hexdigest()
        created_console = ConsoleRunResource(ssh_config)
        run_resources["console"] = created_console

        async def recover_console_effect(effect: dict[str, Any]) -> tuple[bool, Any]:
            if effect.get("tool_name") not in {"console_exec", "console_start"}:
                return False, None
            try:
                recovered = await created_console.execution.recover_operation(
                    UUID(str(effect["operation_id"])),
                    allow_running=effect.get("tool_name") == "console_start",
                )
            except Exception:
                # A failed reconciliation cannot authorize a new execution.
                return False, None
            return (True, recovered.model_dump(mode="json")) if recovered is not None else (False, None)

        checkpoint.recover_effect = recover_console_effect

        async def cleanup_console() -> None:
            await created_console.execution.cancel_active()
            await created_console.close()

        lifecycle.add_cleanup("console", cleanup_console)
    try:
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
    checkpoint.result_factory = lambda: ExecutionResult(
        **ai_result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - start_time,
    )
    last_progress_persist = 0.0

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
    from core.database import release_db_transaction

    await release_db_transaction()
    runtime_agent = agent_executor.agent
    if runtime_agent is None:
        raise RuntimeError("The internal harness runtime was not initialized.")
    message_stream: AsyncIterator[AIMessage] = runtime_agent.run(
        prompt=human_prompt,
        message_history=message_history or None,
        group_id=task.message_group_id,
        self_id=self_id,
        current_messages=[current_message] if current_message is not None else None,
        output_transport=None,
        checkpoint=checkpoint,
    )
    from . import run_control

    try:
        cooperative_cancel = runtime_agent.request_cancel
    except AttributeError:  # Test doubles and legacy local runtimes remain cancellable.
        cooperative_cancel = None
    await run_control.set_cancel_request(task.run_id, cooperative_cancel)
    try:
        # Make the execution panel (and its live LLM-call subscription) available
        # before the first provider request starts.
        await persist_progress(force=True)
        async for message in message_stream:
            ai_result.add_message(message.model_copy(deep=True))
            if message.type == "text" and not message.success:
                ai_result.success = False

            # Tool lifecycle blocks are sparse and important, while text deltas can be
            # very frequent. Publish tools and failures immediately and throttle text.
            await persist_progress(
                force=message.type == "tool" or not message.success or message.stream_complete is True,
            )

            # Empty completion markers make a Task block visible without replaying text.
            if message.has_visible_content() or message.stream_complete is True:
                yield AgentEvent.from_message(message)
    except asyncio.CancelledError:
        console_resource = run_resources.get("console")
        if isinstance(console_resource, ConsoleRunResource):
            await asyncio.shield(console_resource.execution.cancel_active())
        raise
    except Exception:
        console_resource = run_resources.get("console")
        if isinstance(console_resource, ConsoleRunResource):
            await asyncio.shield(console_resource.execution.cancel_active())
        raise
    finally:
        await run_control.set_cancel_request(task.run_id, None)
        console_resource = run_resources.get("console")
        if isinstance(console_resource, ConsoleRunResource):
            await console_resource.close()

    # Surface budget exhaustion so the task trace explains a partial delivery.
    if getattr(runtime_agent, "budget_exhausted", False):
        ai_result.metadata["budget_exhausted"] = True

    terminal_output = getattr(runtime_agent, "terminal_output", None)
    if ai_result.success and isinstance(terminal_output, str):
        ai_result.reconcile_terminal_text(terminal_output)

    await executor_service.recover_after_verified_delivery(
        task,
        ai_result,
        failure_kind=getattr(
            runtime_agent,
            "terminal_failure_kind",
            None,
        ),
    )

    result = ExecutionResult(
        **ai_result.model_dump(exclude={"execution_time"}),
        execution_time=time.time() - start_time,
    )

    # Release task-scoped messenger context.
    reset_context(_ctx_token)
    yield AgentEvent.from_result(result)


async def stream(task: AgentRunRequest) -> AsyncIterator[AgentEvent]:
    """Register one cancellable harness run around its complete resource lifecycle."""

    from . import run_control

    lifecycle = RunResources()
    await run_control.register(task.run_id, task.task_id, lifecycle)
    try:
        async for event in _stream(task, lifecycle):
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
