# Streamable Pydantic AI runtime owned by the internal harness entrypoints.

import asyncio
import json
import hashlib
import mimetypes
import re
import time
from collections import deque
from collections.abc import Mapping
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, List, Literal, Optional, Sequence, Tuple, Union, cast
from uuid import UUID, uuid4

import anyio
from loguru import logger
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import (
    AgentRunResultEvent,
    CancellationToken,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.exceptions import RunCancelled, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai import messages as _pydantic_messages
from pydantic_ai.capabilities import Hooks, ProcessHistory, ToolSearch
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.models.openai import (
    OpenAIChatModelSettings,
    OpenAIResponsesModelSettings,
)

from app.llm import LLM, LLMCallPurpose
from app.llm.provider_facade import ReasoningEffort
from core.i18n import render_prompt, t
from core.params import runtime_settings
from app.llm import pydantic_ai_utils as _llm_pydantic_ai_utils
from app.agent.contracts import TaskMessage as Message
from app.agent.contracts import AIMessage, AgentUsage, normalize_tool_name
from app.agent.conversation_context import (
    LeadingMessageMetadataFilter,
    message_prompt,
    strip_leading_message_metadata,
)
from app.tools import (
    catalog_entry_from_definition,
    catalog_from_entries,
    search_catalog_in_isolated_session,
)

from .media import AgentInputFile, NativeInput, message_native_parts, prepare_native_inputs
from .checkpoint import TOOL_ERROR_SCHEMA, HarnessRunCheckpoint, wrap_toolsets

_HISTORY_TOOL_ARGUMENT_MAX_CHARS = 6_000
_HISTORY_TOOL_RETURN_MAX_CHARS = 4_000
_HISTORY_TOOL_RETURN_PREVIEW_CHARS = 600
_HISTORY_TOOL_RETURNS_KEPT_INTACT = 4
# A tool-free wrap-up turns a guarded run into an honest report. Recovery with effects is
# a distinct Task retry path; leaving tools mounted here can consume the tiny budget before
# the actual delivery call and can make the report perform untracked extra work.
_WRAPUP_MAX_REQUESTS = 1
_REPEATED_TOOL_NO_PROGRESS_LIMIT = 3
_REPEATED_TEXT_NO_PROGRESS_LIMIT = 3
_TEXT_PROGRESS_WINDOW = 32
_TRACE_TOOL_RESULT_KEYS = frozenset(
    {
        "uri",
        "source_uri",
        "operation",
        "state",
        "status",
        "outcome",
        "exit_code",
        "run_id",
    }
)
_TOOL_ERROR_TYPE_RE = re.compile(
    r"(?:Technical type|Type technique)\s*:\s*([A-Za-z_][A-Za-z0-9_.]*)"
)


def _tool_failure_error_type(result_part: object, error_message: str) -> str:
    match = _TOOL_ERROR_TYPE_RE.search(error_message)
    return match.group(1).rstrip(".") if match is not None else type(result_part).__name__


def _trace_tool_result(value: object) -> dict[str, Any] | None:
    """Keep only bounded, non-sensitive fields needed to prove a tool outcome."""
    candidate: object = value
    if isinstance(candidate, str):
        if not candidate.lstrip().startswith("{"):
            return None
        try:
            candidate = cast(object, json.loads(candidate))
        except json.JSONDecodeError:
            return None
    if not isinstance(candidate, Mapping):
        return None

    raw_result = cast(Mapping[object, object], candidate)
    tool_result: dict[str, Any] = {}
    for key in _TRACE_TOOL_RESULT_KEYS:
        if key not in raw_result:
            continue
        value = raw_result.get(key)
        if isinstance(value, (str, int, float, bool, type(None))):
            tool_result[key] = value
    return tool_result or None


class RepeatedToolNoProgressError(RuntimeError):
    """Raised when successful calls repeat without producing a new effect."""


class RepeatedTextNoProgressError(RuntimeError):
    """Raised when a real-time model repeats prose without reaching an action."""


class IncompleteModelResponseError(RuntimeError):
    """Raised when a provider marks a terminal response as incomplete or filtered."""


def _empty_model_output_failure(
    exc: Exception,
    captured: list[_pydantic_messages.ModelMessage],
) -> bool:
    """Recognize exhausted output retries whose last response had no action or text."""

    if not isinstance(exc, UnexpectedModelBehavior):
        return False
    responses = [
        message
        for message in captured
        if isinstance(message, _pydantic_messages.ModelResponse)
    ]
    if not responses:
        return False
    return not any(
        isinstance(part, _pydantic_messages.ToolCallPart)
        or (
            isinstance(part, _pydantic_messages.TextPart)
            and bool(part.content.strip())
        )
        for part in responses[-1].parts
    )

build_model_for_llm = _llm_pydantic_ai_utils.build_model_for_llm
estimate_cost_from_usage = _llm_pydantic_ai_utils.estimate_cost_from_usage


def _normalized_usage(result: Any, llm: LLM, cost: float) -> AgentUsage:
    raw_usage = getattr(result, "usage", None)
    if callable(raw_usage):
        raw_usage = raw_usage()
    if raw_usage is None:
        return AgentUsage(
            cost=cost,
            cost_quality="estimated" if cost > 0 else "unknown",
        )

    def counter(name: str) -> int:
        value = getattr(raw_usage, name, 0) or 0
        return max(0, int(value)) if isinstance(value, (int, float)) else 0

    details = getattr(raw_usage, "details", None)
    reasoning_tokens = 0
    if isinstance(details, Mapping):
        usage_details = cast(Mapping[str, object], details)
        candidate = (
            usage_details.get("reasoning_tokens")
            or usage_details.get("reasoning")
            or 0
        )
        if isinstance(candidate, (int, float)):
            reasoning_tokens = max(0, int(candidate))
    reported_cost = getattr(raw_usage, "cost", None)
    cost_quality: Literal["exact", "estimated", "partial", "unknown"]
    if reported_cost is not None:
        cost_quality = "exact"
    elif cost > 0 or (
        getattr(llm, "cost_per_input_token", None) is not None
        and getattr(llm, "cost_per_output_token", None) is not None
    ):
        cost_quality = "estimated"
    else:
        cost_quality = "unknown"
    return AgentUsage(
        input_tokens=counter("input_tokens"),
        output_tokens=counter("output_tokens"),
        cache_read_tokens=counter("cache_read_tokens"),
        cache_write_tokens=counter("cache_write_tokens"),
        reasoning_tokens=reasoning_tokens,
        requests=max(1, counter("requests")),
        tool_calls=counter("tool_calls"),
        cost=cost,
        token_quality="exact",
        cost_quality=cost_quality,
    )


def _compact_history_value(value: Any) -> Any:
    """Replace large, already-executed payloads with a compact reference."""
    if isinstance(value, str):
        if len(value) <= _HISTORY_TOOL_ARGUMENT_MAX_CHARS:
            return value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return f"[content omitted after execution: {len(value)} characters, sha256={digest}]"
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        return {
            key: _compact_history_value(item) for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [_compact_history_value(item) for item in cast(list[Any], value)]
    return value


def compact_completed_tool_arguments(
    messages: list[_pydantic_messages.ModelMessage],
) -> list[_pydantic_messages.ModelMessage]:
    """Compact large arguments from completed tool calls in prior turns.

    Keep call identity, small parameters, and results while replacing large payloads with
    their size and digest.
    """
    compacted: list[_pydantic_messages.ModelMessage] = []
    answered = {
        (part.tool_name, part.tool_call_id)
        for message in messages
        if isinstance(message, _pydantic_messages.ModelRequest)
        for part in message.parts
        if isinstance(part, (_pydantic_messages.ToolReturnPart, _pydantic_messages.RetryPromptPart))
    }
    for message in messages:
        if not isinstance(message, _pydantic_messages.ModelResponse):
            compacted.append(message)
            continue
        parts: list[_pydantic_messages.ModelResponsePart] = []
        changed = False
        for part in message.parts:
            if isinstance(part, _pydantic_messages.ToolCallPart) and (part.tool_name, part.tool_call_id) in answered:
                if (
                    isinstance(part.args, str)
                    and len(part.args) > _HISTORY_TOOL_ARGUMENT_MAX_CHARS
                ):
                    try:
                        decoded_args = json.loads(part.args)
                    except json.JSONDecodeError:
                        # Do not manufacture an object which violates the original tool
                        # schema. Invalid historical JSON remains observable as-is.
                        args: Any = part.args
                    else:
                        args = json.dumps(
                            _compact_history_value(decoded_args),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                else:
                    args = _compact_history_value(part.args)
                if args != part.args:
                    part = replace(part, args=args)
                    changed = True
            parts.append(part)
        compacted.append(replace(message, parts=parts) if changed else message)
    return compacted


def compact_stale_tool_returns(
    messages: list[_pydantic_messages.ModelMessage],
) -> list[_pydantic_messages.ModelMessage]:
    """Truncate large tool results from older turns.

    Every model request resends the whole history, so a few verbose tool results
    (command output, file dumps, page analyses) can consume the model context on their
    own. The most recent results stay intact; older large ones keep a short preview
    plus size and digest so the agent can still recognize them and re-read the full
    data from its canonical resource URI when needed.
    """
    positions: list[tuple[int, int]] = []
    for message_index, message in enumerate(messages):
        if isinstance(message, _pydantic_messages.ModelRequest):
            for part_index, part in enumerate(message.parts):
                if isinstance(part, _pydantic_messages.ToolReturnPart):
                    positions.append((message_index, part_index))
    if len(positions) <= _HISTORY_TOOL_RETURNS_KEPT_INTACT:
        return messages
    stale = set(positions[: -_HISTORY_TOOL_RETURNS_KEPT_INTACT])

    compacted: list[_pydantic_messages.ModelMessage] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, _pydantic_messages.ModelRequest):
            compacted.append(message)
            continue
        parts: list[_pydantic_messages.ModelRequestPart] = []
        changed = False
        for part_index, part in enumerate(message.parts):
            if (message_index, part_index) in stale and isinstance(
                part, _pydantic_messages.ToolReturnPart
            ):
                content = part.content
                if (
                    isinstance(content, str)
                    and len(content) > _HISTORY_TOOL_RETURN_MAX_CHARS
                ):
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
                    preview = content[:_HISTORY_TOOL_RETURN_PREVIEW_CHARS].rstrip()
                    part = replace(
                        part,
                        content=(
                            f"{preview}\n[tool result truncated after use: "
                            f"{len(content)} characters, sha256={digest}]"
                        ),
                    )
                    changed = True
                elif not isinstance(content, str):
                    compacted_content = _compact_history_value(content)
                    if compacted_content != content:
                        part = replace(part, content=compacted_content)
                        changed = True
            parts.append(part)
        compacted.append(replace(message, parts=parts) if changed else message)
    return compacted


def compact_capability_load_returns(
    messages: list[_pydantic_messages.ModelMessage],
) -> list[_pydantic_messages.ModelMessage]:
    """Remove duplicated deferred-capability instructions from model history.

    Pydantic AI injects the instructions of every loaded capability into each new
    request independently. Keeping the same text in the ``load_capability`` tool
    return therefore sends it twice on the first turn and leaves another copy in
    every subsequent request. The typed call and empty typed return are sufficient
    for Pydantic AI to retain the loaded-capability state.
    """
    compacted: list[_pydantic_messages.ModelMessage] = []
    for message in messages:
        if not isinstance(message, _pydantic_messages.ModelRequest):
            compacted.append(message)
            continue
        parts: list[_pydantic_messages.ModelRequestPart] = []
        changed = False
        for part in message.parts:
            if (
                isinstance(part, _pydantic_messages.ToolReturnPart)
                and part.tool_name == "load_capability"
                and getattr(part, "tool_kind", None) == "capability-load"
                and part.content
            ):
                part = replace(part, content={})
                changed = True
            parts.append(part)
        compacted.append(replace(message, parts=parts) if changed else message)
    return compacted


def _history_message_size(message: _pydantic_messages.ModelMessage) -> int:
    dumped = _pydantic_messages.ModelMessagesTypeAdapter.dump_json([message])
    return len(dumped)


def _history_chunks(
    messages: list[_pydantic_messages.ModelMessage],
) -> list[list[_pydantic_messages.ModelMessage]]:
    """Keep a tool-call response and its following tool returns indivisible."""

    chunks: list[list[_pydantic_messages.ModelMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        chunk = [message]
        if (
            isinstance(message, _pydantic_messages.ModelResponse)
            and any(
                isinstance(part, _pydantic_messages.ToolCallPart)
                for part in message.parts
            )
            and index + 1 < len(messages)
            and isinstance(messages[index + 1], _pydantic_messages.ModelRequest)
            and any(
                isinstance(
                    part,
                    (
                        _pydantic_messages.ToolReturnPart,
                        _pydantic_messages.RetryPromptPart,
                    ),
                )
                for part in messages[index + 1].parts
            )
        ):
            chunk.append(messages[index + 1])
            index += 1
        chunks.append(chunk)
        index += 1
    return chunks


def _bound_history_context(
    messages: list[_pydantic_messages.ModelMessage],
    *,
    max_chars: int,
) -> list[_pydantic_messages.ModelMessage]:
    if sum(_history_message_size(message) for message in messages) <= max_chars:
        return messages
    chunks = _history_chunks(messages)
    kept = list(chunks)
    omitted: list[list[_pydantic_messages.ModelMessage]] = []
    while len(kept) > 4:
        candidate = kept[0]
        remaining = [message for chunk in kept[1:] for message in chunk]
        if sum(_history_message_size(message) for message in remaining) <= max_chars:
            omitted.append(candidate)
            kept.pop(0)
            break
        omitted.append(candidate)
        kept.pop(0)
    if not omitted:
        return messages
    omitted_dump = _pydantic_messages.ModelMessagesTypeAdapter.dump_json(
        [message for chunk in omitted for message in chunk]
    )
    digest = hashlib.sha256(omitted_dump).hexdigest()[:16]
    summary = _pydantic_messages.ModelRequest(
        parts=[
            _pydantic_messages.UserPromptPart(
                content=(
                    "Earlier completed history was compacted by Galaris: "
                    f"{len(omitted)} block(s), sha256={digest}. "
                    "Use durable resource URIs and tools to recover details if needed."
                )
            )
        ]
    )
    return [summary, *(message for chunk in kept for message in chunk)]


def compact_agent_history(
    messages: list[_pydantic_messages.ModelMessage],
    *,
    max_chars: int | None = None,
) -> list[_pydantic_messages.ModelMessage]:
    """Compact payloads and enforce a model-aware total history budget."""
    messages = compact_completed_tool_arguments(messages)
    messages = compact_capability_load_returns(messages)
    messages = compact_stale_tool_returns(messages)
    if max_chars is not None:
        messages = _bound_history_context(messages, max_chars=max(8_000, max_chars))
    return messages


def _close_dangling_tool_calls(
    messages: list[_pydantic_messages.ModelMessage],
    language: str,
) -> list[_pydantic_messages.ModelMessage]:
    """Append synthetic results for tool calls interrupted by a usage limit.

    Providers reject a history whose last response contains tool calls without
    matching results, which happens when the limit fires between a call and its
    execution.
    """
    calls: dict[str, str] = {}
    for message in messages:
        if isinstance(message, _pydantic_messages.ModelResponse):
            for part in message.parts:
                if isinstance(part, _pydantic_messages.ToolCallPart):
                    calls[part.tool_call_id] = part.tool_name
        else:
            for part in message.parts:
                if isinstance(
                    part,
                    (
                        _pydantic_messages.ToolReturnPart,
                        _pydantic_messages.RetryPromptPart,
                    ),
                ):
                    tool_call_id = getattr(part, "tool_call_id", None)
                    if tool_call_id:
                        calls.pop(tool_call_id, None)
    if not calls:
        return messages
    content = t("agent_runtime.budget_wrapup_tool_interrupted", language)
    returns: list[_pydantic_messages.ModelRequestPart] = [
        _pydantic_messages.ToolReturnPart(
            tool_name=tool_name,
            content=content,
            tool_call_id=tool_call_id,
        )
        for tool_call_id, tool_name in calls.items()
    ]
    return [*messages, _pydantic_messages.ModelRequest(parts=returns)]


@dataclass
class _StreamState:
    """Mutable stream accounting shared by the main run and its wrap-up pass."""

    streamed_text: bool = False
    part_stream_ids: dict[int, str] = field(default_factory=dict[int, str])
    thinking_content: dict[int, str] = field(default_factory=dict[int, str])
    last_text_stream_id: str | None = None
    leading_message_metadata: LeadingMessageMetadataFilter = field(
        default_factory=LeadingMessageMetadataFilter
    )
    tool_call_events: dict[str, FunctionToolCallEvent] = field(
        default_factory=dict[str, FunctionToolCallEvent]
    )
    next_missing_tool_call_index: int = 0
    repeated_success_signature: str | None = None
    repeated_success_count: int = 0
    observe_text_no_progress: bool = False
    text_progress_buffer: str = ""
    recent_text_units: deque[str] = field(
        default_factory=lambda: deque(maxlen=_TEXT_PROGRESS_WINDOW)
    )
    last_message_time: float = field(default_factory=time.perf_counter)

    def elapsed(self) -> float:
        now = time.perf_counter()
        elapsed = now - self.last_message_time
        self.last_message_time = now
        return elapsed

    def part_stream_id(self, index: int) -> str:
        return self.part_stream_ids.setdefault(index, uuid4().hex)


def _remember_tool_call(
    state: _StreamState,
    event: FunctionToolCallEvent,
) -> None:
    call_id = str(getattr(event.part, "tool_call_id", "") or "")
    if call_id:
        key = call_id
    else:
        key = f"missing:{state.next_missing_tool_call_index}"
        state.next_missing_tool_call_index += 1
    state.tool_call_events[key] = event


def _take_tool_call(
    state: _StreamState,
    event: FunctionToolResultEvent,
) -> FunctionToolCallEvent | None:
    call_id = str(getattr(event.part, "tool_call_id", "") or "")
    if call_id:
        return state.tool_call_events.pop(call_id, None)
    if len(state.tool_call_events) == 1:
        key = next(iter(state.tool_call_events))
        return state.tool_call_events.pop(key)
    return None


def _observe_tool_result(state: _StreamState, message: AIMessage) -> None:
    """Track progress without turning tool errors into a terminal run failure."""
    # Any tool result breaks a text-repetition streak: the no-progress text guard only
    # stops streams that repeat without interleaved tool activity, so its "without any
    # tool action" claim must stay accurate across the whole run.
    state.recent_text_units.clear()
    state.text_progress_buffer = ""
    if message.success:
        arguments = dict(message.tool_arguments or {})
        # Rewriting the same file or path with another generated body is still the
        # same operation. The working-set layer makes it idempotent; this guard then
        # stops a model that keeps asking for replacements instead of making progress.
        if message.tool_name in {"file_create", "file_write", "file_edit"}:
            arguments.pop("content", None)
        mutating_repeat_guard_tools = {
            "file_create",
            "file_edit",
            "file_write",
            "file_append",
            "file_copy",
            "file_move",
            "messenger_room_send_file",
            "messenger_send_file_to_user",
            "messenger_room_send_message",
            "messenger_send_message_to_user",
        }
        payload = json.dumps(
            {
                "tool_name": message.tool_name,
                "arguments": _compact_history_value(arguments),
                "result": (
                    "mutating_call"
                    if message.tool_name in mutating_repeat_guard_tools
                    else message.content
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if signature == state.repeated_success_signature:
            state.repeated_success_count += 1
        else:
            state.repeated_success_signature = signature
            state.repeated_success_count = 1
        if state.repeated_success_count >= _REPEATED_TOOL_NO_PROGRESS_LIMIT:
            raise RepeatedToolNoProgressError(
                "Stopped after three identical successful or no-op calls to "
                f"{message.tool_name or 'an unknown tool'}; no new progress was made."
            )
        return
    state.repeated_success_signature = None
    state.repeated_success_count = 0


def _observe_text_progress(state: _StreamState, content: str) -> None:
    """Stop a bounded real-time stream that repeats meaningful complete lines."""

    if not state.observe_text_no_progress or not content:
        return
    combined = state.text_progress_buffer + content
    complete, separator, remainder = combined.rpartition("\n")
    if not separator:
        state.text_progress_buffer = combined[-8_000:]
        return
    state.text_progress_buffer = remainder[-8_000:]
    for raw_line in complete.splitlines():
        unit = " ".join(raw_line.split()).casefold()
        words = [word for word in unit.split() if any(char.isalpha() for char in word)]
        if len(unit) < 40 or len(words) < 5:
            continue
        state.recent_text_units.append(unit)
        if sum(item == unit for item in state.recent_text_units) >= _REPEATED_TEXT_NO_PROGRESS_LIMIT:
            raise RepeatedTextNoProgressError(
                "Stopped a real-time response after the same explanatory text repeated "
                "three times without any tool action or terminal answer."
            )


def _result_finish_reason(result: Any) -> str | None:
    """Return the provider finish reason from a Pydantic AI run result."""
    for accessor_name in ("new_messages", "all_messages"):
        accessor = getattr(result, accessor_name, None)
        if not callable(accessor):
            continue
        try:
            messages = list(cast(Sequence[Any], accessor()))
        except (TypeError, ValueError):
            continue
        for message in reversed(messages):
            if isinstance(message, _pydantic_messages.ModelResponse):
                reason = getattr(message, "finish_reason", None)
                return str(reason) if reason else None
    return None


class AgentRuntime(ABC):
    """Abstract streamable AI runtime."""

    @abstractmethod
    def run(
        self,
        prompt: str,
        message_history: Optional[List[Message]] = None,
        group_id: str | None = None,
        self_id: str | None = None,
        images: Optional[List[Tuple[bytes, str]]] = None,
        input_files: Optional[List[AgentInputFile]] = None,
        output_transport: Any | None = None,
        checkpoint: HarnessRunCheckpoint | None = None,
        current_messages: Sequence[Message] | None = None,
    ) -> AsyncIterator[AIMessage]:
        """Run the agent and stream messages.

        ``self_id`` distinguishes assistant history, ``images`` supplies native multimodal
        parts, and ``input_files`` references short-lived files materialized for this run.
        """
        ...

    @abstractmethod
    def request_cancel(self) -> None:
        """Request cooperative cancellation of the active Pydantic AI run."""
        ...


class Agent(AgentRuntime):
    """Streamable Pydantic AI agent."""

    def __init__(
        self,
        llm: LLM,
        system_prompt: str = "",
        temperature: float = 0.0,
        tools: Optional[List[Any]] = None,
        mcp_servers: Optional[List[Any]] = None,
        capabilities: Optional[List[Any]] = None,
        task_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        conversation_round_id: UUID | None = None,
        agent_id: int | None = None,
        language: str = "en",
        real_time: bool = False,
        purpose: LLMCallPurpose = LLMCallPurpose.AGENT_EXEC,
        checkpoint: HarnessRunCheckpoint | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        self.llm: LLM = llm
        self.system_prompt = system_prompt
        self.temperature = temperature
        self._tools = list(tools or [])
        self._mcp_servers = list(mcp_servers or [])
        self._capabilities = list(capabilities or [])
        self._task_id = task_id
        self._agent_run_id = agent_run_id
        self._conversation_round_id = conversation_round_id
        self._agent_id = agent_id
        self._language = language
        self._real_time = real_time
        self._purpose = purpose
        self._checkpoint = checkpoint
        self._reasoning_effort: ReasoningEffort | None = reasoning_effort
        self._cancellation_token = CancellationToken()
        self._agent: Optional[PydanticAgent] = None
        self.prompt = ""
        self.messages: List[AIMessage] = []
        self.cost: float = 0.0
        self.error: str = ""
        self.budget_exhausted: bool = False
        self.terminal_failure_kind: str | None = None
        self.terminal_output: str | None = None

    async def init(self) -> None:
        """Initialize the Pydantic AI model and tools."""

        model = await build_model_for_llm(
            self.llm,
            enable_native_media=True,
            task_id=self._task_id,
            agent_run_id=self._agent_run_id,
            conversation_round_id=self._conversation_round_id,
            agent_id=self._agent_id,
            purpose=self._purpose,
            reasoning_effort=self._reasoning_effort,
        )

        max_parallel_tools = (
            self._checkpoint.request.limits.tool_parallelism
            if self._checkpoint is not None
            else 1
        )
        if isinstance(model, _llm_pydantic_ai_utils.InternalLLMResponsesModel):
            responses_settings: OpenAIResponsesModelSettings = {
                "temperature": self.temperature,
                "parallel_tool_calls": max_parallel_tools > 1,
            }
            responses_policy = model.responses_policy
            if responses_policy.store is not None:
                responses_settings["openai_store"] = responses_policy.store
            if responses_policy.reasoning_context is not None:
                responses_settings["openai_reasoning_context"] = (
                    responses_policy.reasoning_context
                )
            if responses_policy.reasoning_summary is not None:
                responses_settings["openai_reasoning_summary"] = (
                    responses_policy.reasoning_summary
                )
            if responses_policy.send_reasoning_ids is not None:
                responses_settings["openai_send_reasoning_ids"] = (
                    responses_policy.send_reasoning_ids
                )
            if self._reasoning_effort is not None:
                responses_settings["openai_reasoning_effort"] = self._reasoning_effort
            model_settings: OpenAIChatModelSettings | OpenAIResponsesModelSettings = (
                responses_settings
            )
        else:
            model_settings = {
                "temperature": self.temperature,
                "parallel_tool_calls": max_parallel_tools > 1,
            }
        if self._real_time and self._reasoning_effort is None:
            from app.llm.provider_facade import runtime_policy_for
            from app.llm.resource_discovery import provider_connection

            policy = runtime_policy_for(
                provider_connection(self.llm.provider, None)
            )
            if policy.realtime_reasoning_effort:
                model_settings["openai_reasoning_effort"] = (
                    policy.realtime_reasoning_effort
                )

        raw_context_length = getattr(self.llm, "context_length", None)
        model_context_window = getattr(model, "context_window", None)
        context_length = (
            int(raw_context_length)
            if isinstance(raw_context_length, (int, float))
            and raw_context_length > 0
            else model_context_window
            if isinstance(model_context_window, int) and model_context_window > 0
            else 32_000
        )
        history_max_chars = max(16_000, int(context_length * 4 * 0.55))

        def process_history(
            messages: list[_pydantic_messages.ModelMessage],
        ) -> list[_pydantic_messages.ModelMessage]:
            return compact_agent_history(messages, max_chars=history_max_chars)

        async def compact_native_history(
            ctx: Any,
            request_context: ModelRequestContext,
        ) -> ModelRequestContext:
            messages = request_context.messages
            if sum(_history_message_size(message) for message in messages) <= history_max_chars:
                return request_context
            chunks = _history_chunks(messages)
            if len(chunks) <= 2:
                return request_context
            prefix = [message for chunk in chunks[:-2] for message in chunk]
            suffix = [message for chunk in chunks[-2:] for message in chunk]
            if not prefix:
                return request_context
            compact_context = replace(request_context, messages=prefix)
            try:
                compacted = await model.compact_messages(
                    compact_context,
                    instructions=self.system_prompt,
                )
            except Exception as exc:
                logger.warning(
                    "Native Responses compaction failed; applying bounded local history "
                    "fallback: {}",
                    exc,
                )
                return replace(
                    request_context,
                    messages=_bound_history_context(messages, max_chars=history_max_chars),
                )
            ctx.usage.incr(compacted.usage)
            return replace(request_context, messages=[compacted, *suffix])

        history_capability = (
            Hooks(
                before_model_request=compact_native_history,
                id="galaris-native-responses-compaction",
            )
            if isinstance(model, _llm_pydantic_ai_utils.InternalLLMResponsesModel)
            and model.responses_policy.supports_compaction
            else ProcessHistory(process_history)
        )

        self._agent = PydanticAgent(
            model,
            # Pydantic AI omits ``system_prompt`` when an existing message history is
            # supplied. Harness runs always need their current governed prompt, so use
            # instructions, which are injected into every model request.
            instructions=self.system_prompt,
            tools=self._tools,
            toolsets=wrap_toolsets(
                self._mcp_servers,
                self._checkpoint,
                max_parallel=max_parallel_tools,
            ),
            capabilities=[
                history_capability,
                ToolSearch(
                    strategy=self._search_deferred_tools,
                    max_results=10,
                    tool_description=(
                        "Search the remaining authorized MCP tools by intent. "
                        "Use this when the eager tools do not cover the task."
                    ),
                ),
                *self._capabilities,
            ],
            model_settings=model_settings,
            retries={"tools": 3, "output": 2},
        )

    def request_cancel(self) -> None:
        """Cancel the active run through Pydantic AI's resumable path."""

        self._cancellation_token.cancel()

    async def _search_deferred_tools(
        self,
        _ctx: Any,
        queries: Sequence[str],
        tools: Sequence[ToolDefinition],
    ) -> list[str]:
        """Use the shared hybrid retriever on Pydantic AI's authorized corpus."""

        entries = [
            catalog_entry_from_definition(
                runtime="internal",
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters_json_schema,
            )
            for tool in tools
        ]
        catalog = catalog_from_entries(
            agent_id=self._agent_id or 0,
            runtime="internal",
            entries=entries,
        )
        result = await search_catalog_in_isolated_session(
            catalog,
            query="\n".join(queries),
            limit=10,
            surface="executor",
        )
        return [hit.entry.name for hit in result.hits]

    async def run(
        self,
        prompt: str,
        message_history: Optional[List[Message]] = None,
        group_id: str | None = None,
        self_id: str | None = None,
        images: Optional[List[Tuple[bytes, str]]] = None,
        input_files: Optional[List[AgentInputFile]] = None,
        output_transport: Any | None = None,
        checkpoint: HarnessRunCheckpoint | None = None,
        current_messages: Sequence[Message] | None = None,
    ) -> AsyncIterator[AIMessage]:  # type: ignore
        """Run in streaming mode and yield each partial or tool message in real time."""

        if self._agent is None:
            error_msg = t("agent_runtime.not_initialized", self._language)
            self.error = error_msg
            yield AIMessage(
                type="text", content=error_msg, success=False, execution_time=0.0
            )
            return

        active_checkpoint = checkpoint or self._checkpoint
        pydantic_history: List[_pydantic_messages.ModelMessage] = []
        if active_checkpoint is not None:
            await active_checkpoint.prepare_resume()
        native_inputs: dict[str, NativeInput] = {}
        if self._agent_id is not None and not (active_checkpoint is not None and active_checkpoint.history):
            from app.file_share import ResourceContext
            native_inputs = await prepare_native_inputs(
                self.llm,
                ResourceContext(self._agent_id, "internal", self._task_id),
                current_messages or (), message_history or (),
            )
            if native_inputs:
                from core.database import release_db_transaction
                await release_db_transaction()
        if active_checkpoint is not None and active_checkpoint.history:
            pydantic_history = cast(
                List[_pydantic_messages.ModelMessage],
                active_checkpoint.restored_messages(),
            )
        elif message_history:
            pydantic_history = _convert_message_history_to_pydantic(message_history, self_id, native_inputs)

        self.prompt = prompt
        self.terminal_output = None
        # Canonical attachment resources become bounded native content for this run.
        agent_input: Union[str, Sequence[Any]] = (
            (
                "Continue the interrupted run from the supplied model history. "
                "Do not repeat completed tool effects; use their recorded results."
            )
            if active_checkpoint is not None and active_checkpoint.history
            else prompt
        )
        input_parts: list[Any] = []
        for current_message in current_messages or ():
            input_parts.extend(message_native_parts(current_message, native_inputs))
        if input_files:
            input_parts.extend(await self._build_file_input_parts(input_files))
        if images:
            input_parts.extend(_build_binary_image_parts(images))
        if input_parts:
            agent_input = [agent_input, *input_parts]

        state = _StreamState(observe_text_no_progress=self._real_time)
        captured_messages: list[_pydantic_messages.ModelMessage] = []
        try:
            with capture_run_messages() as captured_messages:
                execution_mode = (
                    "parallel"
                    if active_checkpoint is not None
                    and active_checkpoint.request.limits.tool_parallelism > 1
                    else "sequential"
                )
                with self._agent.parallel_tool_call_execution_mode(execution_mode):
                    async with self._agent.run_stream_events(
                        agent_input,
                        message_history=pydantic_history or None,
                        cancellation_token=self._cancellation_token,
                        usage_limits=UsageLimits(
                            request_limit=runtime_settings.TASK_AGENT_MAX_REQUESTS,
                            tool_calls_limit=runtime_settings.TASK_AGENT_MAX_TOOL_CALLS,
                            count_tokens_before_request=True,
                        ),
                    ) as event_stream:
                        async for message in self._emit_stream_messages(
                            event_stream, state, output_transport
                        ):
                            yield message
        except asyncio.CancelledError as cancellation_error:
            cancelled_run = RunCancelled.from_cancellation(cancellation_error)
            interrupted_history = (
                cancelled_run.all_messages()
                if cancelled_run is not None
                else list(captured_messages)
            )
            if active_checkpoint is not None and interrupted_history:
                await asyncio.shield(
                    active_checkpoint.interrupted(interrupted_history)
                )
            raise
        except RunCancelled as cancellation_error:
            if active_checkpoint is not None:
                await active_checkpoint.interrupted(
                    cancellation_error.all_messages()
                )
            raise asyncio.CancelledError from cancellation_error
        except anyio.BrokenResourceError:
            # A disconnected websocket or SSE client is a normal stream termination.
            return
        except UsageLimitExceeded as limit_error:
            async for message in self._wrap_up_exhausted_run(
                limit_error,
                list(captured_messages),
                state,
                output_transport,
            ):
                yield message
        except RepeatedToolNoProgressError as no_progress_error:
            async for message in self._wrap_up_no_progress_run(
                no_progress_error,
                list(captured_messages),
                state,
                output_transport,
            ):
                yield message
        except Exception as e:
            yield self._stream_failure(e, captured_messages)

    async def _emit_stream_messages(
        self,
        event_stream: AsyncIterator[
            _pydantic_messages.AgentStreamEvent | AgentRunResultEvent[Any]
        ],
        state: _StreamState,
        output_transport: Any | None,
    ) -> AsyncIterator[AIMessage]:
        """Translate one run's event stream into trace messages."""
        task_trace = self._task_id is not None and not self._real_time
        async for event in event_stream:
            # 1. Store a tool call until its matching result arrives.
            if isinstance(event, FunctionToolCallEvent):
                pending = state.leading_message_metadata.finish()
                if pending:
                    _observe_text_progress(state, pending)
                    state.streamed_text = True
                    msg = AIMessage(
                        type="text",
                        content=pending,
                        stream_id=state.last_text_stream_id,
                        stream_complete=True if task_trace else None,
                        cost=0.0,
                        execution_time=state.elapsed(),
                    )
                    self.messages.append(msg)
                    yield msg
                state.leading_message_metadata = LeadingMessageMetadataFilter()
                _remember_tool_call(state, event)
                continue

            # 2. Merge the result with its pending call into one trace message.
            if isinstance(event, FunctionToolResultEvent):
                tool_call_event = _take_tool_call(state, event)
                msg = _function_to_message(
                    event,
                    tool_call_event,
                    self._language,
                )
                msg.stream_id = f"tool:{msg.tool_call_external_id or uuid4().hex}"
                if not msg.success:
                    await self._record_tool_failure(event, tool_call_event, msg)
                _observe_tool_result(state, msg)
                msg.execution_time = state.elapsed()
                self.messages.append(msg)
                self.cost += msg.cost
                yield msg
                continue

            # 3. Append text and reasoning deltas to their own identified messages.
            if isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, _pydantic_messages.ThinkingPartDelta):
                    content = event.delta.content_delta
                    if content:
                        state.thinking_content[event.index] = state.thinking_content.get(event.index, "") + content
                        msg = AIMessage(
                            type="tool", tool_name="thinking", content=content,
                            stream_id=state.part_stream_id(event.index),
                            stream_complete=False if task_trace else None,
                            execution_time=state.elapsed(),
                        )
                        self.messages.append(msg)
                        yield msg
                    continue
                if isinstance(event.delta, _pydantic_messages.TextPartDelta):
                    delta_text = getattr(event.delta, "content_delta", "")
                    if delta_text:
                        delta_text = state.leading_message_metadata.feed(delta_text)
                    if delta_text:
                        _observe_text_progress(state, delta_text)
                        state.streamed_text = True
                        msg = AIMessage(
                            type="text",
                            content=delta_text,
                            stream_id=state.part_stream_id(event.index),
                            stream_complete=False if task_trace else None,
                            cost=0.0,
                            execution_time=state.elapsed(),
                        )
                        self.messages.append(msg)
                        self.cost += msg.cost
                        yield msg
                continue

            # 4. Pydantic AI places the first text fragment in PartStartEvent. Emit
            #    only TextPart here or the first token would be lost.
            if isinstance(event, PartStartEvent):
                part = event.part
                state.part_stream_ids[event.index] = uuid4().hex
                state.thinking_content.pop(event.index, None)
                if isinstance(part, _pydantic_messages.ThinkingPart) and part.content:
                    state.thinking_content[event.index] = part.content
                    msg = AIMessage(
                        type="tool", tool_name="thinking", content=part.content,
                        stream_id=state.part_stream_id(event.index),
                        stream_complete=False if task_trace else None,
                        execution_time=state.elapsed(),
                    )
                    self.messages.append(msg)
                    yield msg
                if isinstance(part, _pydantic_messages.TextPart):
                    state.last_text_stream_id = state.part_stream_id(event.index)
                if isinstance(part, _pydantic_messages.TextPart) and part.content:
                    content = state.leading_message_metadata.feed(part.content)
                    if not content:
                        continue
                    _observe_text_progress(state, content)
                    state.streamed_text = True
                    msg = AIMessage(
                        type="text",
                        content=content,
                        stream_id=state.part_stream_id(event.index),
                        stream_complete=False if task_trace else None,
                        cost=0.0,
                        execution_time=state.elapsed(),
                    )
                    self.messages.append(msg)
                    self.cost += msg.cost
                    yield msg
                continue

            # PartEnd repeats cumulative content; reasoning was already emitted as deltas.
            if isinstance(event, PartEndEvent):
                part = getattr(event, "part", None)
                thinking_part = getattr(_pydantic_messages, "ThinkingPart", None)
                if task_trace and isinstance(part, _pydantic_messages.TextPart):
                    # Keep deltas available to guards/checkpoints, but let Task views
                    # publish this block only once the provider has closed it.
                    pending = state.leading_message_metadata.finish()
                    msg = AIMessage(
                        type="text", content=pending,
                        stream_id=state.part_stream_id(event.index),
                        stream_complete=True,
                    )
                    self.messages.append(msg)
                    yield msg
                    continue
                if isinstance(part, _pydantic_messages.FilePart):
                    msg = await _file_part_to_message(
                        part,
                        output_transport,
                        self._language,
                    )
                    if msg is not None:
                        msg.stream_id = state.part_stream_id(event.index)
                        msg.execution_time = state.elapsed()
                        self.messages.append(msg)
                        yield msg
                    continue
                if (
                    thinking_part is not None
                    and part is not None
                    and isinstance(part, thinking_part)
                    and (part.content or "").strip()
                ):
                    observed = state.thinking_content.get(event.index, "")
                    if observed.startswith(part.content):
                        if task_trace:
                            yield AIMessage(
                                type="tool", tool_name="thinking", content="",
                                stream_id=state.part_stream_id(event.index), stream_complete=True,
                            )
                        continue
                    if part.content.startswith(observed):
                        content = part.content[len(observed):]
                    else:
                        # A divergent completion is a distinct block, never an
                        # overwrite of already published reasoning.
                        state.part_stream_ids[event.index] = uuid4().hex
                        content = part.content
                    msg = AIMessage(
                        type="tool",
                        tool_name="thinking",
                        content=content,
                        stream_id=state.part_stream_id(event.index),
                        stream_complete=True if task_trace else None,
                        cost=0.0,
                    )
                    self.messages.append(msg)
                    state.thinking_content[event.index] = part.content
                    yield msg
                continue

            # 5. The final event carries exact cost accounting.
            if isinstance(event, AgentRunResultEvent):
                result = cast(Any, event.result)
                finish_reason = _result_finish_reason(result)
                if finish_reason in {"length", "content_filter"}:
                    raise IncompleteModelResponseError(
                        "The provider returned an incomplete model response "
                        f"(finish_reason={finish_reason}); it was not delivered as a success."
                    )
                cost = estimate_cost_from_usage(result, self.llm)
                self.terminal_output = strip_leading_message_metadata(
                    str(getattr(result, "output", "") or "")
                )

                # If deltas already carried the answer, emit an empty cost carrier;
                # otherwise emit the complete non-streaming output once.
                content = "" if state.streamed_text else self.terminal_output

                msg = AIMessage(
                    type="text",
                    content=content,
                    stream_id=uuid4().hex if content else None,
                    stream_complete=True if task_trace and content else None,
                    cost=cost,
                    usage=_normalized_usage(result, self.llm, cost),
                    success=True,
                    execution_time=state.elapsed(),
                )
                self.messages.append(msg)
                self.cost += msg.cost
                yield msg
                continue

    async def _record_tool_failure(
        self,
        event: FunctionToolResultEvent,
        tool_call_event: FunctionToolCallEvent | None,
        message: AIMessage,
    ) -> None:
        """Persist the tool error before its user-facing trace is compacted."""

        from core.failure_journal import FailureEvent, record_failure_event
        from app.tools import native_failure_key

        call_part = tool_call_event.part if tool_call_event is not None else None
        result_part = event.part
        call_external_id = message.tool_call_external_id
        fallback_key = hashlib.sha256(
            json.dumps(
                {
                    "run": str(self._agent_run_id or ""),
                    "tool": message.tool_name or "",
                    "arguments": message.tool_arguments or {},
                    "result": str(getattr(result_part, "data", result_part)),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        key = call_external_id or fallback_key
        error_message = str(
            getattr(result_part, "data", None)
            or getattr(result_part, "content", None)
            or result_part
        )
        error_type = _tool_failure_error_type(result_part, error_message)
        await record_failure_event(
            FailureEvent(
                idempotency_key=(
                    native_failure_key(error_message)
                    or f"tool-call:{self._agent_run_id or 'unscoped'}:{key}"
                ),
                kind="tool",
                phase="tool_execution",
                error_type=error_type,
                error_message=error_message,
                retryable=True,
                retry_limit=message.tool_retry_limit,
                will_retry=True if message.tool_retry_limit is not None else None,
                task_id=self._task_id,
                conversation_round_id=self._conversation_round_id,
                agent_id=self._agent_id,
                run_uuid=self._agent_run_id,
                driver_code="internal",
                model_code=str(
                    getattr(self.llm, "code", "")
                    or getattr(self.llm, "llm_name", "")
                ),
                tool_name=message.tool_name,
                tool_call_external_id=call_external_id,
                trace={
                    "source": "pydantic_ai.tool_result",
                    "tool_call": call_part,
                    "tool_result": result_part,
                    "normalized_message": message.model_dump(mode="json"),
                    "correlation": {
                        "task_id": self._task_id,
                        "run_uuid": self._agent_run_id,
                        "conversation_round_id": self._conversation_round_id,
                        "agent_id": self._agent_id,
                    },
                },
            )
        )

    async def _wrap_up_exhausted_run(
        self,
        limit_error: UsageLimitExceeded,
        captured: list[_pydantic_messages.ModelMessage],
        _state: _StreamState,
        output_transport: Any | None,
    ) -> AsyncIterator[AIMessage]:
        """Ask the agent for an immediate final report after a usage guard fires.

        A run that hits its usage limit has usually produced real work already;
        aborting would discard it. This pass replays the captured history with
        delivery instructions so the caller receives a partial result instead of
        an error.
        """
        async for message in self._wrap_up_guarded_run(
            limit_error,
            captured,
            output_transport,
            tool_name="budget_guard",
            notice_key="agent_runtime.budget_wrapup_notice",
            prompt_key="agent_runtime.budget_wrapup_prompt",
            budget_exhausted=True,
        ):
            yield message

    async def _wrap_up_no_progress_run(
        self,
        no_progress_error: RepeatedToolNoProgressError,
        captured: list[_pydantic_messages.ModelMessage],
        _state: _StreamState,
        output_transport: Any | None,
    ) -> AsyncIterator[AIMessage]:
        """Turn an anti-loop stop into one bounded finalization attempt."""

        async for message in self._wrap_up_guarded_run(
            no_progress_error,
            captured,
            output_transport,
            tool_name="no_progress_guard",
            notice_key="agent_runtime.no_progress_wrapup_notice",
            prompt_key="agent_runtime.no_progress_wrapup_prompt",
            budget_exhausted=False,
        ):
            yield message

    async def _wrap_up_guarded_run(
        self,
        guard_error: Exception,
        captured: list[_pydantic_messages.ModelMessage],
        output_transport: Any | None,
        *,
        tool_name: str,
        notice_key: str,
        prompt_key: str,
        budget_exhausted: bool,
    ) -> AsyncIterator[AIMessage]:
        """Request one bounded final report after a recoverable execution guard."""

        if self._agent is None or not captured:
            yield self._stream_failure(guard_error, captured)
            return

        self.budget_exhausted = budget_exhausted
        logger.warning(
            "Agent run guard fired; requesting a final wrap-up: {}",
            guard_error,
        )
        notice_usage = self._run_usage_from_history(captured)
        notice = AIMessage(
            type="tool",
            tool_name=tool_name,
            content=render_prompt(
                t(notice_key, self._language),
                detail=str(guard_error),
            ),
            cost=notice_usage.cost,
            usage=notice_usage,
        )
        self.messages.append(notice)
        self.cost += notice.cost
        yield notice

        # The recovery pass is a new bounded opportunity with independent streaming and
        # anti-loop state. In particular, text emitted before the guard must not suppress
        # a non-streamed final report from this pass.
        wrapup_state = _StreamState()
        history = _close_dangling_tool_calls(captured, self._language)
        wrapup_captured: list[_pydantic_messages.ModelMessage] = []
        try:
            with capture_run_messages() as wrapup_captured:
                # Override both statically registered tools and MCP toolsets. This pass
                # reports recorded facts only; it cannot create, mutate, or deliver.
                with self._agent.override(tools=[], toolsets=[]):
                    with self._agent.parallel_tool_call_execution_mode("sequential"):
                        async with self._agent.run_stream_events(
                            t(prompt_key, self._language),
                            message_history=history,
                            cancellation_token=self._cancellation_token,
                            usage_limits=UsageLimits(
                                request_limit=_WRAPUP_MAX_REQUESTS,
                            ),
                        ) as event_stream:
                            async for message in self._emit_stream_messages(
                                event_stream, wrapup_state, output_transport
                            ):
                                yield message
        except anyio.BrokenResourceError:
            return
        except Exception as wrapup_error:
            yield self._stream_failure(wrapup_error, wrapup_captured)

    def _stream_failure(
        self,
        exc: Exception,
        captured: list[_pydantic_messages.ModelMessage],
    ) -> AIMessage:
        """Build the terminal failure message, keeping the cost of consumed requests."""
        error_msg = _format_exception(exc)
        self.error = error_msg
        if _empty_model_output_failure(exc, captured):
            self.terminal_failure_kind = "empty_model_output"
        if any(message.type == "text" and message.content for message in self.messages):
            logger.exception("Agent stream finalization failed after emitting content")
        usage = self._run_usage_from_history(captured)
        self.cost += usage.cost
        return AIMessage(
            type="text",
            content=error_msg,
            success=False,
            cost=usage.cost,
            usage=usage,
            execution_time=0.0,
        )

    def _run_cost_from_history(
        self,
        captured: list[_pydantic_messages.ModelMessage],
    ) -> float:
        """Estimate the cost of an aborted run, whose result event never fires."""
        return sum(
            estimate_cost_from_usage(message, self.llm)
            for message in captured
            if isinstance(message, _pydantic_messages.ModelResponse)
        )

    def _run_usage_from_history(
        self,
        captured: list[_pydantic_messages.ModelMessage],
    ) -> AgentUsage:
        """Keep measured tokens and requests when an aborted run has no result event."""

        usage = AgentUsage()
        for message in captured:
            if not isinstance(message, _pydantic_messages.ModelResponse):
                continue
            cost = estimate_cost_from_usage(message, self.llm)
            usage = usage.merged(_normalized_usage(message, self.llm, cost))
        return usage

    async def _build_file_input_parts(self, files: List[AgentInputFile]) -> list[Any]:
        """Build Pydantic AI parts for files already staged on disk."""
        parts: list[Any] = []
        for file in files:
            if not file.path.is_file():
                logger.warning("Pydantic AI input file not found: {}", file.path)
                continue
            part = await self._build_file_input_part(file)
            if part is not None:
                parts.append(part)
        return parts

    async def _build_file_input_part(self, file: AgentInputFile) -> Any | None:
        from app.llm import normalized_media_type, supports_native_input
        media_type = normalized_media_type(file.media_type, file.display_name)
        if not supports_native_input(self.llm, media_type):
            return None

        size = file.path.stat().st_size
        max_bytes = runtime_settings.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES
        if size > max_bytes:
            logger.warning(
                "File {} not sent to the model because size {} exceeds {}",
                file.agent_path,
                size,
                max_bytes,
            )
            return None

        try:
            from pydantic_ai import BinaryContent  # type: ignore
        except Exception:
            logger.warning("BinaryContent unavailable; ignoring file {}", file.agent_path)
            return None
        return BinaryContent(
            data=await anyio.Path(file.path).read_bytes(),
            media_type=media_type,
            identifier=file.display_name,
        )


async def create_agent(
    llm: LLM,
    system_prompt: str = "",
    temperature: float = 0.0,
    tools: Optional[List[Any]] = None,
    mcp_servers: Optional[List[Any]] = None,
    capabilities: Optional[List[Any]] = None,
    task_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    agent_id: int | None = None,
    language: str = "en",
    real_time: bool = False,
    purpose: LLMCallPurpose = LLMCallPurpose.AGENT_EXEC,
    checkpoint: HarnessRunCheckpoint | None = None,
    reasoning_effort: ReasoningEffort | None = None,
) -> AgentRuntime:
    """Create and initialize a Pydantic AI agent runtime."""
    agent = Agent(
        llm=llm,
        system_prompt=system_prompt,
        temperature=temperature,
        tools=tools,
        mcp_servers=mcp_servers,
        capabilities=capabilities,
        task_id=task_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        agent_id=agent_id,
        language=language,
        real_time=real_time,
        purpose=purpose,
        checkpoint=checkpoint,
        reasoning_effort=reasoning_effort,
    )

    await agent.init()
    return agent


def _build_binary_image_parts(images: List[Tuple[bytes, str]]) -> list[Any]:
    """Build BinaryContent parts for images already held in memory."""
    try:
        from pydantic_ai import BinaryContent  # type: ignore
    except Exception:
        logger.warning("BinaryContent unavailable; ignoring images and using text only")
        return []

    parts: List[Any] = []
    for data, mime in images:
        parts.append(BinaryContent(data=data, media_type=mime or "image/png"))
    return parts


async def _file_part_to_message(
    part: Any,
    output_transport: Any | None,
    language: str = "en",
) -> AIMessage | None:
    """Persist binary Pydantic AI FilePart content through an explicit output transport."""
    content = getattr(part, "content", None)
    binary_content = getattr(_pydantic_messages, "BinaryContent", None)
    if binary_content is None:
        try:
            from pydantic_ai import BinaryContent as binary_content  # type: ignore
        except Exception:
            binary_content = None

    if binary_content is None or not isinstance(content, binary_content):
        file_id = getattr(part, "id", None)
        if file_id:
            return AIMessage(
                type="tool",
                tool_name="file_output",
                content=render_prompt(
                    t("agent_runtime.provider_file", language),
                    file_id=file_id,
                ),
                cost=0.0,
            )
        return None

    if output_transport is None:
        return AIMessage(
            type="tool",
            tool_name="file_output",
            content=t("agent_runtime.file_destination_unavailable", language),
            cost=0.0,
        )

    data = getattr(content, "data", b"")
    if not isinstance(data, bytes) or not data:
        return None

    media_type = str(getattr(content, "media_type", "") or "application/octet-stream")
    identifier = str(getattr(content, "identifier", "") or getattr(part, "id", "") or "output")
    filename = _safe_filename(identifier, media_type)
    target = output_transport.resolve_path(f"outputs/{filename}")
    await anyio.Path(target).write_bytes(data)
    agent_path = output_transport.agent_path(target)
    return AIMessage(
        type="tool",
        tool_name="file_output",
        content=render_prompt(
            t("agent_runtime.produced_file", language),
            path=agent_path,
            size=len(data),
        ),
        cost=0.0,
    )


def _safe_filename(name: str, media_type: str) -> str:
    raw = Path(name.strip() or "output").name
    cleaned = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in raw)
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "output"
    if "." not in cleaned:
        extension = mimetypes.guess_extension(media_type) or ".bin"
        cleaned += extension
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{cleaned}"


def _function_to_message(
    event: FunctionToolResultEvent,
    tool_call_event: FunctionToolCallEvent | None,
    language: str = "en",
) -> AIMessage:
    if tool_call_event:
        part = tool_call_event.part
        tool_name = normalize_tool_name(getattr(part, "tool_name", "?"))
        raw_args = getattr(part, "args", {})

        # Pydantic AI may return a raw JSON string instead of a mapping.
        if isinstance(raw_args, str):
            try:
                args: Any = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"raw": raw_args}
        else:
            args = raw_args

        pending_tool_call: dict[str, Any] | None = {
            "tool_name": tool_name,
            "args": args,
            "raw_args": raw_args,
        }
    else:
        pending_tool_call = None

    result = event.part
    tool_name = normalize_tool_name(
        getattr(result, "tool_name", "?") if hasattr(result, "tool_name") else "?"
    )
    data = cast(
        object,
        (
            getattr(result, "data", "")
            if hasattr(result, "data")
            else getattr(result, "content", "")
        ),
    )
    tool_result = _trace_tool_result(data)

    content = render_prompt(
        t("agent_runtime.tool_called", language),
        tool_name=tool_name,
    )
    if data:
        content = render_prompt(
            t("agent_runtime.tool_called_with_result", language),
            tool_name=tool_name,
            result=str(data)[:500],
        )

    reported_error = (
        isinstance(data, dict)
        and cast(dict[str, object], data).get("schema") == TOOL_ERROR_SCHEMA
    )
    success = type(result).__name__ != "RetryPromptPart" and not reported_error

    msg = AIMessage(
        type="tool",
        content=content,
        tool_name=tool_name,
        tool_arguments=pending_tool_call.get("args") if pending_tool_call else None,
        tool_result=tool_result,
        tool_call_external_id=str(
            getattr(result, "tool_call_id", "")
            or (getattr(tool_call_event.part, "tool_call_id", "") if tool_call_event else "")
        )
        or None,
        tool_retry_limit=3 if not success and not reported_error else None,
        cost=0.0,
        success=success,
    )
    return msg


def _format_exception(exc: Exception) -> str:
    """Format an exception readably, unwrapping MCP initialization groups."""
    import traceback

    # ExceptionGroup (PEP 654) — Python 3.11+
    if hasattr(exc, "exceptions") and callable(getattr(exc, "exceptions", None)):
        sub_exceptions: Any = getattr(exc, "exceptions")()
        if isinstance(sub_exceptions, (list, tuple)) and sub_exceptions:
            parts: list[str] = ["ExceptionGroup (MCP init):"]
            for i, sub in enumerate(cast("list[Any]", sub_exceptions)):
                parts.append(f"  [{i}] {type(sub).__name__}: {sub}")
                # Log every nested traceback in full.
                logger.opt(exception=sub).error(
                    f"MCP sub-exception [{i}]: {type(sub).__name__}"
                )
            return "\n".join(parts)

    # ExceptionGroup legacy (anyio, trio)
    if hasattr(exc, "exceptions"):
        sub_exceptions = getattr(exc, "exceptions")
        if isinstance(sub_exceptions, (list, tuple)) and sub_exceptions:
            parts = ["ExceptionGroup (MCP init):"]
            for i, sub in enumerate(cast("list[Any]", sub_exceptions)):
                parts.append(f"  [{i}] {type(sub).__name__}: {sub}")
                logger.opt(exception=sub).error(
                    f"MCP sub-exception [{i}]: {type(sub).__name__}"
                )
            return "\n".join(parts)

    # Simple exception.
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    logger.error("".join(tb))
    return f"{type(exc).__name__}: {exc}"


def _convert_message_history_to_pydantic(
    messages: List[Message],
    self_id: str | None = None,
    native_inputs: dict[str, NativeInput] | None = None,
) -> List[_pydantic_messages.ModelMessage]:
    """Convert canonical messages with compact metadata local to each message."""
    result: List[_pydantic_messages.ModelMessage] = []

    for msg in messages:
        is_self = bool(
            (self_id and msg.sender_external_id == str(self_id))
            or msg.is_ai
        )
        content = message_prompt(msg).strip()
        if not content:
            continue

        sender_info: dict[str, Any] = {
            "user_id": str(msg.sender_id) if msg.sender_id else None,
            "external_id": msg.sender_external_id or None,
            "nickname": msg.sender_display_name or None,
            "kind": "AI" if is_self else "human",
        }

        timestamp: datetime | None = None
        if msg.time:
            timestamp = datetime.fromtimestamp(msg.time, tz=timezone.utc)

        msg_kwargs: dict[str, Any] = {"metadata": {"sender": sender_info}}
        if timestamp is not None:
            msg_kwargs["timestamp"] = timestamp

        if is_self:
            msg_kwargs["parts"] = [
                _pydantic_messages.TextPart(content=content)
            ]
            result.append(_pydantic_messages.ModelResponse(**msg_kwargs))
            native_parts = message_native_parts(msg, native_inputs or {})
            if native_parts:
                # Provider APIs accept binary input in user messages, not assistant text.
                result.append(_pydantic_messages.ModelRequest(parts=[
                    _pydantic_messages.UserPromptPart(content=[
                        "Files belonging to the preceding assistant message:", *native_parts,
                    ]),
                ]))
        else:
            native_parts = message_native_parts(msg, native_inputs or {})
            msg_kwargs["parts"] = [
                _pydantic_messages.UserPromptPart(content=[content, *native_parts] if native_parts else content)
            ]
            result.append(_pydantic_messages.ModelRequest(**msg_kwargs))

    return result
