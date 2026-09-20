"""Durable, effect-safe checkpoints for the internal Pydantic AI harness."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, AsyncGenerator, Literal, cast
from uuid import UUID, uuid4
from datetime import datetime, timezone

from pydantic_ai import ModelRetry
from pydantic_core import to_jsonable_python
from app.tools.contracts import ToolExecutionContext, tool_execution
from .recovery_metrics import observe_recovery

from app.agent.contracts import (
    AgentRunCheckpoint,
    AgentRunRequest,
    ExecutionResult,
    ToolConcurrencyPolicy,
    ToolEffectPolicy,
)

_CHECKPOINT_VERSION = 4
_COMPATIBLE_CHECKPOINT_VERSIONS = frozenset({1, 2, 3, _CHECKPOINT_VERSION})
TOOL_ERROR_SCHEMA = "galaris.tool-error/v1"


def _tool_error_result(error: Exception, outcome: Literal["rejected", "unknown"]) -> dict[str, Any]:
    return {
        "schema": TOOL_ERROR_SCHEMA,
        "status": "error",
        "outcome": outcome,
        "error": error.message if isinstance(error, ModelRetry) else f"{type(error).__name__}: tool execution failed.",
        "instruction": (
            "The call was rejected before its effect. Correct the call, choose another approach, "
            "or stop and explain the blocker. You decide how to continue."
            if outcome == "rejected" else
            "The tool reported an error, but its effect is unknown. Verify the current state "
            "before repeating a potentially non-idempotent action. You may inspect the result, "
            "choose another approach, continue other work, or stop and explain the blocker. "
            "Do not claim this action succeeded without evidence."
        ),
    }


class UnsafeCheckpointError(RuntimeError):
    """Raised when a previous process died during a potentially effectful call."""


class ToolOutcomeUnknownError(UnsafeCheckpointError):
    """A non-idempotent call may have completed before its acknowledgement was saved."""


def _jsonable(value: Any) -> Any:
    return to_jsonable_python(
        value,
        serialize_unknown=True,
        fallback=lambda item: str(item),
    )


def _signature(name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(
        {"name": name, "arguments": _jsonable(arguments)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _execution_policy_for_toolset_tool(
    name: str,
    tool: Any,
) -> tuple[ToolEffectPolicy, ToolConcurrencyPolicy]:
    """Merge native policy with standard MCP effect annotations."""

    from app.tools.mcp_loader import execution_policy_for_tool

    effect_policy, concurrency_policy = execution_policy_for_tool(name)
    raw_metadata: object = getattr(getattr(tool, "tool_def", None), "metadata", None)
    if not isinstance(raw_metadata, dict):
        return effect_policy, concurrency_policy
    metadata = cast(dict[object, object], raw_metadata)
    raw_annotations = metadata.get("annotations")
    if not isinstance(raw_annotations, dict):
        return effect_policy, concurrency_policy
    annotations = cast(dict[object, object], raw_annotations)
    if annotations.get("destructiveHint") is True:
        return "non_idempotent", "exclusive"
    if annotations.get("readOnlyHint") is True:
        return "read", "safe"
    if annotations.get("idempotentHint") is True and annotations.get("destructiveHint") is not True:
        return "idempotent", "exclusive"
    return effect_policy, concurrency_policy


@dataclass
class HarnessRunCheckpoint:
    """Own checkpoint state for one logical run across process attempts."""

    request: AgentRunRequest
    result_factory: Callable[[], ExecutionResult] | None = None
    recover_effect: Callable[[dict[str, Any]], Awaitable[tuple[bool, Any]]] | None = None
    recovery_scope: str | None = None
    effects: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    history: list[Any] = field(default_factory=list[Any])
    _compatible: bool = True
    _replay: dict[str, deque[dict[str, Any]]] = field(default_factory=lambda: defaultdict(deque))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _repaired: bool = False

    def __post_init__(self) -> None:
        checkpoint = self.request.resume_checkpoint
        if checkpoint is None or checkpoint.driver_code != "internal":
            return
        data = dict(checkpoint.data)
        if int(data.get("version") or 0) not in _COMPATIBLE_CHECKPOINT_VERSIONS:
            self._compatible = False
            return
        raw_effects_value = data.get("effects")
        if isinstance(raw_effects_value, list):
            raw_effects = cast(list[object], raw_effects_value)
            self.effects = [
                dict(cast(dict[str, Any], effect))
                for effect in raw_effects
                if isinstance(effect, dict)
            ]
        raw_history_value = data.get("message_history")
        if isinstance(raw_history_value, list):
            self.history = list(cast(list[object], raw_history_value))
        for effect in self.effects:
            if (
                effect.get("status") == "failed"
                and effect.get("outcome") != "rejected"
                and effect.get("effect_policy", "non_idempotent") == "non_idempotent"
            ):
                effect["status"] = "outcome_unknown"
                self._repaired = True
            if effect.get("status") in {"completed", "failed", "error_reported"} and effect.get(
                "effect_policy"
            ) not in {"read", "idempotent"}:
                self._replay[str(effect.get("signature") or "")].append(effect)

    @property
    def runtime_run_id(self) -> str:
        checkpoint = self.request.resume_checkpoint
        if checkpoint is not None and checkpoint.driver_code == "internal":
            return checkpoint.runtime_run_id
        return str(self.request.run_id)

    def restored_messages(self) -> list[Any]:
        if not self.history:
            return []
        from pydantic_ai import messages

        return list(messages.ModelMessagesTypeAdapter.validate_python(self.history))

    def ensure_resumable(self) -> None:
        if not self._compatible:
            raise UnsafeCheckpointError(
                "The internal checkpoint format is not supported; the objective was "
                "not replayed automatically."
            )
        self._repair_recorded_failures()
        self._repair_conservative_effect_policies()
        unresolved = [
            effect
            for effect in self.effects
            if effect.get("status") in {"started", "outcome_unknown"}
        ]
        ambiguous = [
            effect
            for effect in unresolved
            if str(effect.get("effect_policy") or "non_idempotent") == "non_idempotent"
        ]
        for effect in ambiguous:
            if effect.get("status") != "outcome_unknown":
                effect["status"] = "outcome_unknown"
                self._repaired = True
        if ambiguous:
            observe_recovery("blocked", run_id=self.runtime_run_id)
            names = ", ".join(sorted({str(effect.get("tool_name") or "?") for effect in ambiguous}))
            raise ToolOutcomeUnknownError(
                "The previous harness run stopped while a non-idempotent tool call was "
                f"in flight ({names}); its outcome is unknown and it was not replayed."
            )
        retryable = [effect for effect in unresolved if effect not in ambiguous]
        if retryable:
            self._close_retryable_effects(retryable)
            for effect in retryable:
                effect["status"] = "interrupted"
            self._repaired = True

    def _repair_recorded_failures(self) -> None:
        """Recover acknowledgements persisted in older histories but not in the journal."""

        from pydantic_ai import messages

        failures = {
            (part.tool_name, part.tool_call_id): part
            for message in self.restored_messages()
            if isinstance(message, messages.ModelRequest)
            for part in message.parts
            if isinstance(part, messages.RetryPromptPart)
            and part.tool_name
            and isinstance(part.content, list)
        }
        for effect in self.effects:
            if effect.get("status") not in {"started", "outcome_unknown"}:
                continue
            failure = failures.get(
                (str(effect.get("tool_name") or ""), str(effect.get("tool_call_id") or ""))
            )
            if failure is None:
                continue
            effect["status"] = "failed"
            effect["outcome"] = "rejected"
            effect["error"] = failure.model_response()
            self._replay[str(effect.get("signature") or "")].append(effect)
            self._repaired = True

    def _repair_conservative_effect_policies(self) -> None:
        """Upgrade legacy defaults only when the current native contract is replay-safe."""

        from app.tools.mcp_loader import execution_policy_for_tool

        for effect in self.effects:
            if effect.get("policy_version") == _CHECKPOINT_VERSION:
                continue
            if effect.get("status") not in {"started", "outcome_unknown"}:
                continue
            if str(effect.get("effect_policy") or "non_idempotent") != "non_idempotent":
                continue
            tool_name = str(effect.get("tool_name") or "")
            effect_policy, concurrency_policy = execution_policy_for_tool(tool_name)
            if effect_policy == "non_idempotent":
                continue
            effect["effect_policy"] = effect_policy
            effect["concurrency_policy"] = concurrency_policy
            self._repaired = True

    async def prepare_resume(self) -> None:
        """Repair safe interrupted reads and durably classify ambiguous effects."""

        try:
            if self.recover_effect is not None and self._compatible:
                for effect in self.effects:
                    if (
                        effect.get("status") not in {"started", "outcome_unknown", "error_reported"}
                        or not effect.get("operation_id")
                        or not self.recovery_scope
                        or effect.get("recovery_scope") != self.recovery_scope
                    ):
                        continue
                    try:
                        recovered, result = await self.recover_effect(dict(effect))
                    except Exception:
                        if effect.get("status") != "error_reported":
                            raise
                        # Receipt lookup is optional for a recorded tool error:
                        # the model can still resume with its uncertainty intact.
                        continue
                    if recovered:
                        already_queued = effect.get("status") == "error_reported"
                        effect["status"] = "completed"
                        effect["outcome"] = "returned"
                        effect["result"] = _jsonable(result)
                        if not already_queued:
                            self._replay[str(effect.get("signature") or "")].append(effect)
                        self._append_recovered_result(effect)
                        self._repaired = True
                        observe_recovery(
                            "recovered",
                            run_id=self.runtime_run_id,
                            operation_id=str(effect["operation_id"]),
                        )
            self.ensure_resumable()
        finally:
            if self._repaired:
                await self._save()

    def _append_recovered_result(self, effect: dict[str, Any]) -> None:
        from pydantic_ai import messages

        call_id = str(effect.get("tool_call_id") or effect["id"])
        self._replace_tool_return(
            messages.ToolReturnPart(
                tool_name=str(effect["tool_name"]),
                tool_call_id=call_id,
                content=effect["result"],
            )
        )

    def _replace_tool_return(self, replacement: Any) -> None:
        """Keep one response beside its call, even after cancellation placeholders."""
        from dataclasses import replace
        from pydantic_ai import messages

        restored = self.restored_messages()
        repaired: list[Any] = []
        inserted = False
        for message in restored:
            if isinstance(message, messages.ModelRequest):
                parts: list[Any] = []
                for part in message.parts:
                    if (
                        isinstance(part, (messages.ToolReturnPart, messages.RetryPromptPart))
                        and part.tool_call_id == replacement.tool_call_id
                    ):
                        if not inserted:
                            parts.append(replacement)
                            inserted = True
                    else:
                        parts.append(part)
                if parts:
                    repaired.append(replace(message, parts=parts))
            else:
                repaired.append(message)
        if not inserted:
            for index, message in enumerate(repaired):
                if any(
                    isinstance(part, messages.ToolCallPart)
                    and part.tool_call_id == replacement.tool_call_id
                    for part in message.parts
                ):
                    if index + 1 < len(repaired) and isinstance(
                        repaired[index + 1], messages.ModelRequest
                    ):
                        following = repaired[index + 1]
                        repaired[index + 1] = replace(
                            following, parts=[*following.parts, replacement]
                        )
                    else:
                        repaired.insert(index + 1, messages.ModelRequest(parts=[replacement]))
                    break
        self.history = self._dump_messages(repaired)

    def _close_retryable_effects(self, effects: list[dict[str, Any]]) -> None:
        if not self.history:
            return
        from pydantic_ai import messages as model_messages

        returns = [
            model_messages.ToolReturnPart(
                tool_name=str(effect.get("tool_name") or "?"),
                tool_call_id=str(effect.get("tool_call_id") or effect.get("id") or ""),
                content={
                    "status": "interrupted",
                    "retryable": True,
                    "instruction": "Call this read/idempotent tool again if its result is needed.",
                },
            )
            for effect in effects
        ]
        for result in returns:
            self._replace_tool_return(result)

    def take_replay(self, name: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
        queue = self._replay.get(_signature(name, arguments))
        if not queue:
            return False, None
        effect = queue.popleft()
        observe_recovery(
            "replayed", run_id=self.runtime_run_id, operation_id=str(effect.get("id") or "")
        )
        if effect.get("status") == "failed":
            raise ModelRetry(str(effect["error"]))
        return True, effect.get("result")

    async def started(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        messages: list[Any],
        tool_call_id: str | None,
        effect_policy: ToolEffectPolicy = "non_idempotent",
        concurrency_policy: ToolConcurrencyPolicy = "exclusive",
    ) -> str:
        async with self._lock:
            effect_id = str(uuid4())
            self.effects.append(
                {
                    "id": effect_id,
                    "operation_id": effect_id,
                    "recovery_scope": self.recovery_scope
                    if name in {"console_exec", "console_start"}
                    else None,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "tool_name": name,
                    "tool_call_id": tool_call_id or effect_id,
                    "arguments": _jsonable(arguments),
                    "signature": _signature(name, arguments),
                    "status": "started",
                    "policy_version": _CHECKPOINT_VERSION,
                    "effect_policy": effect_policy,
                    "concurrency_policy": concurrency_policy,
                }
            )
            self.history = self._dump_messages(messages)
            await self._save()
            observe_recovery("started", run_id=self.runtime_run_id, operation_id=effect_id)
        return effect_id

    async def completed(
        self,
        *,
        effect_id: str,
        name: str,
        result: Any,
        messages: list[Any],
        tool_call_id: str | None,
        retry_error: str | None = None,
        tool_error_outcome: Literal["rejected", "unknown"] | None = None,
    ) -> None:
        async with self._lock:
            serialized_result = _jsonable(result)
            for effect in self.effects:
                if effect.get("id") == effect_id:
                    effect["status"] = "completed" if retry_error is None else "failed"
                    effect["outcome"] = "returned" if retry_error is None else "rejected"
                    effect["finished_at"] = datetime.now(timezone.utc).isoformat()
                    if retry_error is None:
                        effect["result"] = serialized_result
                    else:
                        effect["error"] = retry_error
                    if tool_error_outcome is not None:
                        effect["status"] = "error_reported"
                        effect["outcome"] = tool_error_outcome
                    break

            from pydantic_ai import messages as model_messages

            response_call_ids: set[str] = set()
            for message in reversed(messages):
                if not isinstance(message, model_messages.ModelResponse):
                    continue
                response_call_ids = {
                    part.tool_call_id
                    for part in message.parts
                    if isinstance(part, model_messages.ToolCallPart)
                }
                break
            returns = [
                model_messages.RetryPromptPart(
                    tool_name=str(effect.get("tool_name") or "?"),
                    content=str(effect["error"]),
                    tool_call_id=str(effect.get("tool_call_id") or effect["id"]),
                )
                if effect.get("status") == "failed"
                else model_messages.ToolReturnPart(
                    tool_name=str(effect.get("tool_name") or "?"),
                    content=effect.get("result"),
                    tool_call_id=str(effect.get("tool_call_id") or effect["id"]),
                )
                for effect in self.effects
                if effect.get("status") in {"completed", "failed", "error_reported"}
                and str(effect.get("tool_call_id") or "") in response_call_ids
            ]
            if not returns:
                returns = [
                    model_messages.RetryPromptPart(
                        tool_name=name,
                        content=retry_error,
                        tool_call_id=tool_call_id or effect_id,
                    )
                    if retry_error is not None
                    else model_messages.ToolReturnPart(
                        tool_name=name,
                        content=serialized_result,
                        tool_call_id=tool_call_id or effect_id,
                    )
                ]
            completed_history = [
                *messages,
                model_messages.ModelRequest(parts=returns),
            ]
            self.history = self._dump_messages(completed_history)
            await self._save()
            observe_recovery(
                ("unknown" if tool_error_outcome == "unknown" else "rejected")
                if tool_error_outcome is not None else
                ("completed" if retry_error is None else "rejected"),
                run_id=self.runtime_run_id,
                operation_id=effect_id,
            )

    async def mark_unknown(self, effect_id: str) -> None:
        async with self._lock:
            for effect in self.effects:
                if effect.get("id") == effect_id:
                    effect["status"] = "outcome_unknown"
                    break
            await self._save()
            observe_recovery("unknown", run_id=self.runtime_run_id, operation_id=effect_id)

    async def interrupted(self, messages: list[Any]) -> None:
        """Persist Pydantic AI's detached history after a cancelled run.

        Effect safety remains governed by the journal: an interrupted non-idempotent
        call still makes the checkpoint unsafe, while completed calls and retryable
        reads may resume from the richer provider history recorded here.
        """

        if not messages:
            return
        async with self._lock:
            self.history = self._dump_messages(messages)
            await self._save(status="interrupted")

    @staticmethod
    def _dump_messages(messages: list[Any]) -> list[Any]:
        from pydantic_ai import messages as model_messages

        dumped = model_messages.ModelMessagesTypeAdapter.dump_python(
            messages,
            mode="json",
        )
        return list(cast(list[Any], dumped))

    async def _save(self, *, status: str = "running") -> None:
        if self.request.save_checkpoint is None:
            return
        result = self.result_factory() if self.result_factory is not None else None
        if result is not None:
            recorded = Counter(result.tools_used)
            completed: Counter[str] = Counter()
            for effect in self.effects:
                name = str(effect.get("tool_name") or "")
                if effect.get("status") == "completed" and name:
                    completed[name] += 1
            for name, count in completed.items():
                result.tools_used.extend([name] * max(0, count - recorded[name]))
        await self.request.save_checkpoint(
            AgentRunCheckpoint(
                driver_code="internal",
                runtime_run_id=self.runtime_run_id,
                status=status,
                result=result.model_copy(deep=True) if result is not None else None,
                data={
                    "version": _CHECKPOINT_VERSION,
                    "execution_strategy": self.request.execution_strategy,
                    "resume_safe": not any(
                        effect.get("status") in {"started", "outcome_unknown"}
                        and str(effect.get("effect_policy") or "non_idempotent") == "non_idempotent"
                        for effect in self.effects
                    ),
                    "resume_reconcilable": bool(self.recovery_scope)
                    and all(
                        effect.get("tool_name") in {"console_exec", "console_start"}
                        and bool(effect.get("operation_id"))
                        and effect.get("recovery_scope") == self.recovery_scope
                        for effect in self.effects
                        if effect.get("status") in {"started", "outcome_unknown"}
                        and effect.get("effect_policy", "non_idempotent") == "non_idempotent"
                    ),
                    "message_history": deepcopy(self.history),
                    "effects": deepcopy(self.effects),
                },
            )
        )


def checkpoint_is_safe(checkpoint: AgentRunCheckpoint) -> bool:
    if checkpoint.driver_code != "internal":
        return True
    return (
        checkpoint.data.get("version") in _COMPATIBLE_CHECKPOINT_VERSIONS
        and checkpoint.data.get("resume_safe") is True
    )


class _ToolCallScheduler:
    """Bounded reader/exclusive barrier shared by every toolset in one run."""

    def __init__(self, max_parallel: int) -> None:
        self._safe_slots = asyncio.Semaphore(max(1, max_parallel))
        self._condition = asyncio.Condition()
        self._active_safe = 0
        self._exclusive_active = False
        self._exclusive_waiting = 0
        self._next_ticket = 0
        self._next_result = 0
        self._finished: set[int] = set()

    def ticket(self) -> int:
        ticket = self._next_ticket
        self._next_ticket += 1
        return ticket

    @asynccontextmanager
    async def slot(self, policy: ToolConcurrencyPolicy) -> AsyncGenerator[None]:
        if policy == "safe":
            async with self._safe_slots:
                async with self._condition:
                    await self._condition.wait_for(
                        lambda: not self._exclusive_active and self._exclusive_waiting == 0
                    )
                    self._active_safe += 1
                try:
                    yield
                finally:
                    async with self._condition:
                        self._active_safe -= 1
                        self._condition.notify_all()
            return

        async with self._condition:
            self._exclusive_waiting += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._exclusive_active and self._active_safe == 0
                )
                self._exclusive_active = True
            finally:
                self._exclusive_waiting -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._exclusive_active = False
                self._condition.notify_all()

    async def wait_result_turn(self, ticket: int) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: ticket == self._next_result)

    async def finish_result(self, ticket: int) -> None:
        async with self._condition:
            self._finished.add(ticket)
            while self._next_result in self._finished:
                self._finished.remove(self._next_result)
                self._next_result += 1
            self._condition.notify_all()


def wrap_toolsets(
    toolsets: list[Any],
    checkpoint: HarnessRunCheckpoint | None,
    *,
    max_parallel: int = 1,
) -> list[Any]:
    from pydantic_ai import RunContext
    from pydantic_ai.toolsets import ToolsetTool, WrapperToolset

    scheduler = _ToolCallScheduler(max_parallel)

    class _CheckpointingToolset(WrapperToolset[Any]):
        async def call_tool(
            self,
            name: str,
            tool_args: dict[str, Any],
            ctx: RunContext[Any],
            tool: ToolsetTool[Any],
        ) -> Any:
            effect_policy, concurrency_policy = _execution_policy_for_toolset_tool(
                name,
                tool,
            )
            ticket = scheduler.ticket()
            result: Any = None
            error: BaseException | None = None
            try:
                async with scheduler.slot(concurrency_policy):
                    if checkpoint is not None:
                        replayed, replay_result = checkpoint.take_replay(name, tool_args)
                        if replayed:
                            result = replay_result
                        else:
                            effect_id = await checkpoint.started(
                                name=name,
                                arguments=tool_args,
                                messages=list(ctx.messages),
                                tool_call_id=ctx.tool_call_id,
                                effect_policy=effect_policy,
                                concurrency_policy=concurrency_policy,
                            )
                            execution = ToolExecutionContext(UUID(effect_id), name)
                            tool_error_outcome: Literal["rejected", "unknown"] | None = None
                            try:
                                with tool_execution(execution):
                                    result = await self.wrapped.call_tool(
                                        name, tool_args, ctx, tool
                                    )
                            except Exception as exc:
                                tool_error_outcome = (
                                    "rejected" if execution.outcome == "rejected"
                                    or effect_policy == "read" else "unknown"
                                )
                                result = _tool_error_result(exc, tool_error_outcome)
                            await checkpoint.completed(
                                effect_id=effect_id,
                                name=name,
                                result=result,
                                messages=list(ctx.messages),
                                tool_call_id=ctx.tool_call_id,
                                tool_error_outcome=tool_error_outcome,
                            )
                    else:
                        execution = ToolExecutionContext(uuid4(), name)
                        try:
                            with tool_execution(execution):
                                result = await self.wrapped.call_tool(name, tool_args, ctx, tool)
                        except Exception as exc:
                            result = _tool_error_result(
                                exc, "rejected" if execution.outcome == "rejected"
                                or effect_policy == "read" else "unknown",
                            )
            except BaseException as exc:
                error = exc

            try:
                await scheduler.wait_result_turn(ticket)
                if error is not None:
                    raise error
                return result
            finally:
                await scheduler.finish_result(ticket)

    return [_CheckpointingToolset(toolset) for toolset in toolsets]
