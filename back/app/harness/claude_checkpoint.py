"""Durable effect evidence for the embedded Claude SDK."""

import json
from collections.abc import Awaitable, Callable, Collection, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, cast
from uuid import UUID

from app.agent.contracts import (
    AIMessage, AgentRunCheckpoint, CheckpointAssessment, ExecutionResult, HarnessFailure, ToolEffectPolicy,
    WAITING_FOR_CONSOLE_RECEIPT,
)
from core.util import get_encryption_service

from .checkpoint_policy import InternalCheckpointPolicy
from .claude_session import ClaudeSession
from .task_tool_scope import CONSOLE_RECOVERY_TOOLS
from .tool_results import compact_tool_return, document_creation_receipt


_FORMAT = "galaris.claude-effects/v1"
_SETTLED = {"completed", "rejected"}
_VALID = {*_SETTLED, "started", "outcome_unknown", "waiting_for_authorization"}
EffectStatus = Literal["completed", "rejected", "outcome_unknown", "waiting_for_authorization"]


@dataclass(frozen=True)
class PendingClaudeEffect:
    operation_id: UUID
    tool_id: str
    name: str
    arguments: dict[str, Any]
    policy: ToolEffectPolicy
    request_id: UUID
    sealed_continuation: str

    def continuation(self, run_id: UUID) -> str:
        payload = get_encryption_service().decrypt(self.sealed_continuation)
        binding = f"{run_id}:{self.operation_id}:{self.request_id}:"
        if not payload.startswith(binding) or len(payload) == len(binding):
            raise ValueError("The Claude authorization continuation does not belong to this tool call.")
        return payload[len(binding):]


def _effects(checkpoint: AgentRunCheckpoint) -> list[dict[str, Any]] | None:
    if checkpoint.data.get("format") != _FORMAT:
        return None
    raw = checkpoint.data.get("effects")
    if not isinstance(raw, list):
        return None
    effects: list[dict[str, Any]] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            return None
        record = cast(dict[str, Any], item)
        status: object = record.get("status")
        if not isinstance(status, str) or status not in _VALID:
            return None
        effects.append(record)
    return effects


def _pending(record: dict[str, Any]) -> PendingClaudeEffect:
    receipt: dict[str, object] = record["result"]
    request_id, sealed = receipt["authorization_request_id"], receipt["sealed_continuation"]
    operation_id, tool_id, name = record["operation_id"], record["tool_call_id"], record["tool_name"]
    arguments, policy = record["arguments"], record["effect_policy"]
    if (not all(isinstance(value, str) and value for value in (request_id, sealed, operation_id, tool_id, name))
            or not isinstance(arguments, dict) or policy not in ("read", "idempotent", "non_idempotent")):
        raise ValueError("Invalid waiting Claude effect.")
    return PendingClaudeEffect(UUID(operation_id), tool_id, name, cast(dict[str, Any], arguments), policy,
                               UUID(cast(str, request_id)), cast(str, sealed))


def _console_operation(effect: Mapping[str, object]) -> UUID | None:
    scope, identifier = effect.get("recovery_scope"), effect.get("operation_id")
    name = effect.get("tool_name")
    if (not isinstance(name, str) or name not in CONSOLE_RECOVERY_TOOLS or not isinstance(scope, str) or not scope
            or effect.get("status") not in ("started", "outcome_unknown", "completed")
            or not isinstance(identifier, str)):
        return None
    try:
        return UUID(identifier)
    except ValueError:
        return None


def _can_reconcile_effects(effects: list[dict[str, Any]]) -> bool:
    if any(effect["status"] not in _SETTLED and _console_operation(effect) is None for effect in effects):
        return False
    if any(_console_operation(effect) is not None for effect in effects):
        return True
    completed = [effect for effect in effects if effect["status"] == "completed"]
    return bool(completed) and all(document_creation_receipt(effect) is not None for effect in completed)


def _console_receipt_pending(effects: list[dict[str, Any]]) -> bool:
    return any(item["status"] == "outcome_unknown" and item["tool_name"] in CONSOLE_RECOVERY_TOOLS for item in effects)


def needs_effect_reconciliation(checkpoint: AgentRunCheckpoint) -> bool:
    effects = _effects(checkpoint)
    return (effects is not None and checkpoint.status in {"running", "interrupted", WAITING_FOR_CONSOLE_RECEIPT}
            and _can_reconcile_effects(effects))


def checkpoint_tool_calls_used(checkpoint: AgentRunCheckpoint | None) -> int:
    if checkpoint is None:
        return 0
    effects = _effects(checkpoint)
    if effects is None:
        return 0
    used = checkpoint.data.get("tool_calls_used")
    # Legacy checkpoints can account only for the operations they recorded.
    return max(len(effects), used) if type(used) is int else len(effects)


class ClaudeCheckpointPolicy:
    """A lost SDK conversation cannot regenerate mutations from a fresh prompt."""

    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        effects = _effects(checkpoint)
        if effects is None:
            return CheckpointAssessment(state="unsafe", reason="Invalid Claude effect journal.")
        statuses = {item["status"] for item in effects}
        if (checkpoint.status == "waiting_for_authorization" and effects
                and effects[-1]["status"] == "waiting_for_authorization"
                and all(item["status"] in _SETTLED for item in effects[:-1])):
            session = checkpoint.data.get("sdk_session")
            if not isinstance(session, str) or not session:
                return CheckpointAssessment(state="unsafe", reason="The waiting Claude SDK session is unavailable.")
            try:
                _pending(effects[-1])
            except (ValueError, KeyError, TypeError, AttributeError):
                return CheckpointAssessment(state="unsafe", reason="Invalid Claude authorization receipt.")
            return CheckpointAssessment(state="reconcile")
        if needs_effect_reconciliation(checkpoint):
            return CheckpointAssessment(state="reconcile")
        if statuses - _SETTLED:
            return CheckpointAssessment(state="unsafe", reason="Claude tool effects or authorization are unresolved.")
        if (checkpoint.status == "waiting_for_children" and checkpoint.data.get("child_wait_requested") is True
                and "completed" in statuses):
            return CheckpointAssessment(state="reconcile")
        if ("completed" in statuses and (checkpoint.status != "completed"
                or checkpoint.result is None or not checkpoint.result.success)):
            return CheckpointAssessment(state="unsafe", reason="Claude lost its continuation after a confirmed tool effect.")
        return CheckpointAssessment(state="safe")

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None:
        effects = _effects(checkpoint)
        if effects is None or any(item["status"] != "rejected" for item in effects):
            return None
        return replace(checkpoint, status="interrupted", result=None)

    def prepare_retry(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint:
        return self.rebase(checkpoint) or checkpoint

    tool_history = InternalCheckpointPolicy.tool_history


class ClaudeEffectJournal:
    def __init__(
        self, *, driver_code: str, run_id: UUID,
        save: Callable[[AgentRunCheckpoint], Awaitable[None]],
        previous: AgentRunCheckpoint | None = None,
        attempt_id: UUID | None = None,
        console_scope: str | None = None,
        tool_calls_used: int = 0,
    ) -> None:
        self.save = save
        self.driver_code = driver_code
        self.run_id = run_id
        self.console_scope = console_scope
        if previous is not None and previous.runtime_run_id != str(run_id):
            raise ValueError("The Claude checkpoint belongs to another run.")
        self._has_checkpoint = previous is not None
        self._records = deepcopy((_effects(previous) if previous is not None else None) or [])
        self._tool_calls_used = max(tool_calls_used, checkpoint_tool_calls_used(previous))
        self._sealed_session: str | None = previous.data.get("sdk_session") if previous is not None else None
        self._child_wait_requested = previous is not None and previous.data.get("child_wait_requested") is True
        self.child_wait_attempt = attempt_id
        if previous is not None and previous.status == "waiting_for_children":
            restored_attempt = previous.data.get("child_wait_attempt")
            if isinstance(restored_attempt, str):
                self.child_wait_attempt = UUID(restored_attempt)

    @property
    def pending(self) -> PendingClaudeEffect | None:
        if self.waiting:
            return _pending(self._records[-1])
        return None

    @property
    def waiting(self) -> bool:
        return bool(self._records and self._records[-1]["status"] == "waiting_for_authorization")

    @property
    def waiting_for_children(self) -> bool:
        return self._child_wait_requested and not self.unresolved

    def restore_session(self) -> ClaudeSession:
        if not self._sealed_session:
            raise ValueError("The Claude SDK session is missing.")
        payload = json.loads(get_encryption_service().decrypt(self._sealed_session))
        if payload["run_id"] != str(self.run_id):
            raise ValueError("The Claude SDK session belongs to another run.")
        return ClaudeSession(UUID(payload["session_id"]), payload["transcript"])

    async def retain_session(self, session: ClaudeSession) -> None:
        if not self._records or self._records[-1]["status"] != "waiting_for_authorization":
            return
        self._sealed_session = get_encryption_service().encrypt(json.dumps({
            "run_id": str(self.run_id),
            "session_id": str(session.id),
            "transcript": session.transcript,
        }, ensure_ascii=False))
        await self._write(self._records)

    async def resume_effect(self) -> None:
        self._sealed_session = None
        last = {key: value for key, value in self._records[-1].items() if key != "result"}
        await self._write([*self._records[:-1], {**last, "status": "started"}])

    def previous_calls(self) -> list[tuple[str, dict[str, Any]]]:
        return [(item["tool_name"], item["arguments"]) for item in self._records]

    @property
    def tool_calls_used(self) -> int:
        return self._tool_calls_used

    async def reserve_tool(self) -> None:
        await self._write(self._records, tool_calls_used=self._tool_calls_used + 1)

    async def reconcile_effects(
        self, available_tools: Collection[str], recover: Callable[[str, UUID], Awaitable[object]],
        verify: Callable[[set[str], set[str]], Awaitable[bool]],
    ) -> list[AIMessage] | None:
        """Resolve exact operation IDs and persist receipts before starting inference."""
        records = self._records.copy()
        tools: set[str] = set()
        documents: set[str] = set()
        for index, effect in enumerate(self._records):
            creation = document_creation_receipt(effect)
            if creation is not None:
                if "file_create" not in available_tools:
                    return None
                tools.add("file_create")
                documents.add(creation[0])
            operation_id = _console_operation(effect)
            if operation_id is None:
                continue
            name: str = effect["tool_name"]
            if effect["recovery_scope"] != self.console_scope or name not in available_tools:
                return None
            tools.add(name)
            if effect["status"] == "completed":
                continue
            receipt = await recover(name, operation_id)
            if receipt is None:
                return None
            records[index] = {**effect, "status": "completed", "result": compact_tool_return(receipt)}
        if not await verify(tools, documents):
            return None
        if records != self._records:
            await self._write(records)
        history: list[AIMessage] = []
        for effect in records[-10:]:
            if effect["status"] not in _SETTLED:
                continue
            creation = document_creation_receipt(effect)
            receipt: object = creation[1] if creation is not None else effect.get("result")
            arguments = compact_tool_return(effect["arguments"])
            history.append(AIMessage(
                type="tool", content=json.dumps(receipt, ensure_ascii=False), tool_name=effect["tool_name"],
                tool_arguments=cast(dict[str, Any], arguments) if isinstance(arguments, dict) else None,
                tool_result=cast(dict[str, Any], receipt) if isinstance(receipt, dict) else {"result": receipt},
                success=effect["status"] == "completed", stream_mode="snapshot",
                stream_id=f"claude-tool:{effect['operation_id']}", tool_call_external_id=effect["tool_call_id"],
            ))
        return history

    def authorization_receipt(self, operation_id: UUID, request_id: UUID, continuation: str | None) -> dict[str, str]:
        receipt = {"authorization_request_id": str(request_id)}
        if continuation:
            binding = f"{self.run_id}:{operation_id}:{request_id}:"
            receipt["sealed_continuation"] = get_encryption_service().encrypt(binding + continuation)
        return receipt

    @property
    def unresolved(self) -> bool:
        return any(item["status"] not in _SETTLED for item in self._records)

    @property
    def applied(self) -> bool:
        return any(item["status"] == "completed" for item in self._records)

    @property
    def waiting_for_console_receipt(self) -> bool:
        return _console_receipt_pending(self._records)

    async def start(self, *, operation_id: UUID, tool_id: str, name: str,
                    arguments: Mapping[str, object], effect_policy: ToolEffectPolicy, count_tool: bool = False) -> None:
        reference = str(operation_id)
        await self._write([*self._records, {
            "id": reference, "operation_id": reference, "tool_call_id": tool_id,
            "tool_name": name, "arguments": dict(arguments), "effect_policy": effect_policy,
            "status": "started",
            **({"recovery_scope": self.console_scope} if self.console_scope and name in CONSOLE_RECOVERY_TOOLS else {}),
        }], tool_calls_used=self._tool_calls_used + 1 if count_tool else None)

    async def finish(self, status: EffectStatus, *, receipt: object, wait_for_children: bool = False) -> None:
        if status != "waiting_for_authorization":
            self._sealed_session = None
        if status == "completed" and wait_for_children:
            self._child_wait_requested = True
        await self._write([*self._records[:-1], {**self._records[-1], "status": status, "result": receipt}])

    async def ensure_started(self) -> None:
        if not self._has_checkpoint:
            await self._write([])

    async def finalize(self, result: ExecutionResult, *, terminal: bool = True) -> None:
        pending = [item for item in self._records if item["status"] == "waiting_for_authorization"]
        if pending:
            result.success = False
            result.schema_version = "galaris.execution-result/v2"
            result.disposition = "waiting_for_authorization"
            result.failure = None
            result.authorization_requests = [UUID(item["result"]["authorization_request_id"]) for item in pending]
            result.reconcile_terminal_text("")
        elif self.unresolved:
            result.success = False
            result.failure = HarnessFailure(
                code="effect_unknown", message="A Claude tool effect or authorization needs reconciliation.",
                retry="reconcile" if _can_reconcile_effects(self._records) else "never",
            )
            result.reconcile_terminal_text("")
        elif self.waiting_for_children:
            result.success = False
            result.schema_version = "galaris.execution-result/v2"
            result.disposition = "waiting_for_children"
            result.failure = None
            result.reconcile_terminal_text("")
        elif self.applied and not result.success:
            result.failure = HarnessFailure(
                code="effect_unknown", message="Claude stopped after a confirmed effect before completing its answer.",
                retry="reconcile" if _can_reconcile_effects(self._records) else "never",
            )
        if terminal and self._has_checkpoint and (result.success or self.waiting_for_children):
            await self._write(self._records, terminal=result)

    async def _write(
        self, effects: list[dict[str, Any]], *, terminal: ExecutionResult | None = None,
        tool_calls_used: int | None = None,
    ) -> None:
        status = "completed" if terminal is not None else "running"
        data: dict[str, Any] = {"format": _FORMAT, "effects": effects}
        used = self._tool_calls_used if tool_calls_used is None else tool_calls_used
        if used:
            data["tool_calls_used"] = used
        if self._child_wait_requested:
            data["child_wait_requested"] = True
        if effects and effects[-1]["status"] == "waiting_for_authorization":
            status = "waiting_for_authorization"
        elif _console_receipt_pending(effects):
            status = WAITING_FOR_CONSOLE_RECEIPT
        elif self._child_wait_requested and all(effect["status"] in _SETTLED for effect in effects):
            status = "waiting_for_children"
            if self.child_wait_attempt is not None:
                data["child_wait_attempt"] = str(self.child_wait_attempt)
        if self._sealed_session is not None and status == "waiting_for_authorization":
            data["sdk_session"] = self._sealed_session
        await self.save(AgentRunCheckpoint(
            driver_code=self.driver_code, runtime_run_id=str(self.run_id),
            status=status, result=terminal,
            data=data,
        ))
        self._records = effects
        self._tool_calls_used = used
        self._has_checkpoint = True


def create_policy() -> ClaudeCheckpointPolicy:
    return ClaudeCheckpointPolicy()
