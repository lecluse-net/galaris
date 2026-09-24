"""Public agent contracts that are independent from concrete runtimes.

This module is the shared data boundary between the Galaris orchestrator and its
drivers. It must never import Pydantic AI, Hermes, or the ``Task`` ORM model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
import re
from typing import (
    Annotated,
    Any,
    Literal,
    Protocol,
    Self,
    TypeAlias,
    cast,
    runtime_checkable,
)
from urllib.parse import quote
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from core.i18n import is_supported


ExecutionEffort = Literal["standard", "high"]


def _legacy_reasoning_effort(value: object) -> object:
    return "low" if value == "minimal" else value


ReasoningEffort: TypeAlias = Annotated[
    Literal["none", "low", "medium", "high", "xhigh", "max"],
    BeforeValidator(_legacy_reasoning_effort),
]
ForcedRoute = Literal["EXEC", "BRIEFING", "PLAN"]
# ``END`` remains accepted when historical dispatch traces are deserialized. New task
# dispatch decisions use ``ActiveDispatchRoute`` and can only execute or plan work.
DispatchRoute = Literal["EXEC", "BRIEFING", "PLAN", "END"]
ActiveDispatchRoute = Literal["EXEC", "PLAN"]
ConversationDispatchRoute = Literal["EXEC", "END"]
RuntimeName = str
OBJECTIVE_IS_STANDALONE_DATA_KEY = "objective_is_standalone"


def _uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


_RESOURCE_TOOL_CODE_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")
_NON_PROVIDER_RESOURCE_SCHEMES = frozenset(
    {"console", "document", "galaris", "memory", "messenger", "resource", "workspace"}
)


def _attachment_uri(tool_code: str, room_locator: str, file_id: UUID) -> str:
    """Build a provider URI without importing a concrete messaging domain."""

    scheme = tool_code.strip()
    room = room_locator.strip()
    if (
        not room
        or not _RESOURCE_TOOL_CODE_RE.fullmatch(scheme)
        or scheme in _NON_PROVIDER_RESOURCE_SCHEMES
    ):
        return ""
    encoded_room = quote(room, safe="!$&'()*+,-.;=@_~:")
    return f"{scheme}://{encoded_room}/{file_id}"


class TaskMessageAttachment(BaseModel):
    """Stable metadata for one file carried by a conversation message."""

    id: UUID
    uri: str = ""
    name: str = ""
    mime: str = ""
    size: int | None = None
    kind: str = "other"

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def read_session_attachment(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        source = cast(dict[str, Any], value)
        return {
            **source,
            "id": source.get("local_id") or source.get("id"),
            "mime": source.get("mime") or source.get("mime_type") or "",
            "size": (
                source.get("size")
                if source.get("size") is not None
                else source.get("size_bytes")
            ),
        }


def _normalize_task_message_files(
    raw_file_ids: object,
    raw_attachments: object,
) -> tuple[list[UUID], list[TaskMessageAttachment | dict[str, Any]]]:
    """Recover only locally identifiable files from historical snapshots."""

    file_id_slots: list[UUID | None] = []
    file_ids: list[UUID] = []
    if isinstance(raw_file_ids, list):
        for value in cast(list[object], raw_file_ids):
            parsed = _uuid(value)
            file_id_slots.append(parsed)
            if parsed is not None and parsed not in file_ids:
                file_ids.append(parsed)

    raw_items = (
        cast(list[object], raw_attachments)
        if isinstance(raw_attachments, list)
        else []
    )
    attachments: list[TaskMessageAttachment | dict[str, Any]] = []
    seen_attachment_ids: set[UUID] = set()
    for index, item in enumerate(raw_items):
        if isinstance(item, TaskMessageAttachment):
            attachment_id = item.id
            normalized: TaskMessageAttachment | dict[str, Any] = item
        elif isinstance(item, dict):
            source = dict(cast(dict[str, Any], item))
            attachment_id = _uuid(source.get("local_id")) or _uuid(source.get("id"))
            if attachment_id is None and index < len(file_id_slots):
                attachment_id = file_id_slots[index]
            if attachment_id is None:
                # A provider identifier cannot form a durable resource URI by itself.
                continue
            source["id"] = attachment_id
            normalized = source
        else:
            continue

        if attachment_id not in file_ids:
            file_ids.append(attachment_id)
        if attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment_id)
        attachments.append(normalized)

    return file_ids, attachments


class TaskMessage(BaseModel):
    """Bounded conversation snapshot passed to an agent runtime."""

    messenger_message_id: UUID | None = None
    external_message_id: str = ""
    platform: str = ""
    tool_id: int | None = None
    tool_code: str = ""
    sender_id: UUID | None = None
    sender_external_id: str = ""
    sender_display_name: str = ""
    sender_agent_id: int | None = None
    sender_is_ai: bool = False
    recipient_id: UUID | None = None
    recipient_external_id: str = ""
    room_id: UUID | None = None
    room_external_id: str = ""
    room_kind: str = "group"
    text: str = ""
    file_ids: list[UUID] = Field(default_factory=list[UUID])
    attachments: list[TaskMessageAttachment] = Field(
        default_factory=list[TaskMessageAttachment]
    )
    reply_to_external_id: str | None = None
    timestamp: int = 0

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def normalize_attachment_references(self) -> Self:
        """Backfill canonical references for historical Task snapshots."""

        ordered_ids = list(
            dict.fromkeys(
                [*self.file_ids, *(item.id for item in self.attachments)]
            )
        )
        self.file_ids = ordered_ids
        by_id = {item.id: item for item in self.attachments}
        normalized: list[TaskMessageAttachment] = []
        for file_id in ordered_ids:
            item = by_id.get(file_id) or TaskMessageAttachment(id=file_id)
            canonical_uri = _attachment_uri(
                self.tool_code,
                self.room_external_id,
                file_id,
            )
            if canonical_uri and item.uri != canonical_uri:
                item = item.model_copy(update={"uri": canonical_uri})
            elif (
                not canonical_uri
                and item.uri.partition("://")[0].casefold() == "messenger"
            ):
                item = item.model_copy(update={"uri": ""})
            normalized.append(item)
        self.attachments = normalized
        return self

    @model_validator(mode="before")
    @classmethod
    def read_legacy_message_json(cls, value: object) -> object:
        """Read historical task JSON without recreating the retired DTO graph."""

        if not isinstance(value, dict):
            return value
        source = cast(dict[str, Any], value)
        file_ids, normalized_attachments = _normalize_task_message_files(
            source.get("file_ids"), source.get("attachments")
        )
        if any(
            key in source
            for key in (
                "messenger_message_id",
                "external_message_id",
                "sender_external_id",
                "sender_display_name",
                "sender_agent_id",
                "sender_is_ai",
                "room_id",
                "room_external_id",
                "file_ids",
                "timestamp",
            )
        ):
            return {
                **source,
                "file_ids": file_ids,
                "attachments": normalized_attachments,
            }
        raw_sender = source.get("sender")
        raw_recipient = source.get("recipient")
        raw_room = source.get("room")
        sender = cast(dict[str, Any], raw_sender) if isinstance(raw_sender, dict) else {}
        recipient = (
            cast(dict[str, Any], raw_recipient)
            if isinstance(raw_recipient, dict)
            else {}
        )
        room = cast(dict[str, Any], raw_room) if isinstance(raw_room, dict) else {}
        return {
            "messenger_message_id": _uuid(source.get("local_id")),
            "external_message_id": str(source.get("id") or ""),
            "platform": str(source.get("platform") or ""),
            "tool_id": source.get("tool_id"),
            "tool_code": str(source.get("tool_code") or ""),
            "sender_id": _uuid(sender.get("local_id")),
            "sender_external_id": str(sender.get("id") or ""),
            "sender_display_name": str(sender.get("display_name") or ""),
            "sender_agent_id": sender.get("agent_id"),
            "sender_is_ai": bool(
                sender.get("is_ai") or sender.get("agent_id") is not None
            ),
            "recipient_id": _uuid(recipient.get("local_id")),
            "recipient_external_id": str(recipient.get("id") or ""),
            "room_id": _uuid(room.get("local_id")),
            "room_external_id": str(room.get("id") or ""),
            "room_kind": str(room.get("kind") or "group"),
            "text": str(source.get("text") or ""),
            "file_ids": file_ids,
            "attachments": normalized_attachments,
            "reply_to_external_id": source.get("reply_to"),
            "timestamp": int(source.get("time") or 0),
        }

    @classmethod
    def from_messenger(cls, message: Any) -> Self:
        """Snapshot a hydrated canonical Messenger row for runtime execution."""

        sender = message.sender
        recipient = message.recipient
        room = message.room
        return cls(
            messenger_message_id=message.id,
            external_message_id=message.remote_message_id,
            platform=message.platform,
            tool_id=message.tool_id,
            tool_code=message.tool_code,
            sender_id=sender.id if sender is not None else None,
            sender_external_id=sender.external_id if sender is not None else "",
            sender_display_name=sender.display_name if sender is not None else "",
            sender_agent_id=sender.agent_id if sender is not None else None,
            sender_is_ai=bool(sender.is_ai) if sender is not None else False,
            recipient_id=recipient.id if recipient is not None else None,
            recipient_external_id=(
                recipient.external_id if recipient is not None else ""
            ),
            room_id=room.id if room is not None else None,
            room_external_id=room.external_id if room is not None else "",
            room_kind=room.kind if room is not None else "group",
            text=message.text,
            file_ids=[file.id for file in message.files],
            attachments=[
                TaskMessageAttachment(
                    id=file.id,
                    uri=_attachment_uri(
                        message.tool_code,
                        room.external_id if room is not None else "",
                        file.id,
                    ),
                    name=file.name,
                    mime=file.mime_type,
                    size=file.size_bytes,
                    kind=file.kind,
                )
                for file in message.files
            ],
            reply_to_external_id=message.reply_to,
            timestamp=int(cast(datetime, message.created_at).timestamp()),
        )

    @property
    def is_ai(self) -> bool:
        return self.sender_is_ai

    @property
    def id(self) -> UUID | None:
        return self.messenger_message_id

    @property
    def time(self) -> int:
        return self.timestamp


class TaskPhase(str, Enum):
    CREATE = "CREATE"
    DISPATCH = "DISPATCH"
    BRIEFING = "BRIEFING"
    EXEC = "EXEC"
    PLAN = "PLAN"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class TaskTransition(str, Enum):
    ROUTE_TO_EXECUTION = "route_to_execution"
    ROUTE_TO_BRIEFING = "route_to_briefing"
    ROUTE_TO_PLAN = "route_to_plan"
    START_EXECUTION = "start_execution"
    BRIEFING_SUCCEEDED = "briefing_succeeded"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"
    PLAN_SUCCEEDED = "plan_succeeded"
    PLAN_FAILED = "plan_failed"
    FAIL = "fail"
    CANCEL = "cancel"
    ACTIVATE_PLAN_STEP = "activate_plan_step"


MCP_GALARIS_TOOL_PREFIXES = (
    "mcp__galaris__",
    "galaris_",
)


def normalize_tool_name(tool_name: Any) -> str:
    """Remove every stacked Galaris technical namespace."""
    name = str(tool_name)
    stripped = True
    while stripped:
        stripped = False
        for prefix in MCP_GALARIS_TOOL_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                stripped = True
                break
    return name


UsageQuality = Literal["exact", "estimated", "partial", "unknown"]


class AgentUsage(BaseModel):
    """Driver-neutral token and cost accounting for one logical agent run."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0.0)
    token_quality: UsageQuality = "unknown"
    cost_quality: UsageQuality = "unknown"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def merged(self, other: "AgentUsage") -> "AgentUsage":
        """Add counters while preserving the least-certain quality marker."""

        quality_rank = {"unknown": 0, "partial": 1, "estimated": 2, "exact": 3}

        def least(left: UsageQuality, right: UsageQuality) -> UsageQuality:
            if left == "unknown" and right != "unknown" and not self.has_measurements:
                return right
            if right == "unknown" and left != "unknown" and not other.has_measurements:
                return left
            return left if quality_rank[left] <= quality_rank[right] else right

        return AgentUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            requests=self.requests + other.requests,
            tool_calls=self.tool_calls + other.tool_calls,
            cost=self.cost + other.cost,
            token_quality=least(self.token_quality, other.token_quality),
            cost_quality=least(self.cost_quality, other.cost_quality),
        )

    @property
    def has_measurements(self) -> bool:
        return bool(
            self.total_tokens
            or self.cache_read_tokens
            or self.cache_write_tokens
            or self.reasoning_tokens
            or self.requests
            or self.tool_calls
            or self.cost
        )


class AIMessage(BaseModel):
    """Normalized trace message shared by all drivers."""

    type: Literal["text", "audio", "image", "video", "tool"] = Field(
        description="Trace message type"
    )
    content: str = Field(description="Message text content")
    tool_name: str | None = Field(
        default=None, description="Tool name (only when type='tool')"
    )
    tool_arguments: dict[str, Any] | None = Field(
        default=None,
        description="Arguments passed to the tool (only when type='tool')",
    )
    tool_result: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Bounded structured outcome fields returned by the tool, when available."
        ),
    )
    tool_call_external_id: str | None = Field(
        default=None,
        max_length=500,
        description="Provider/runtime identifier for this concrete tool invocation.",
    )
    tool_retry_number: int | None = Field(default=None, ge=1)
    tool_retry_limit: int | None = Field(default=None, ge=0)
    execution_time: float = Field(
        description="Execution duration in seconds", default=0.0
    )
    cost: float = Field(description="Total execution cost in dollars", default=0.0)
    success: bool = Field(description="Whether execution succeeded", default=True)
    usage: AgentUsage | None = Field(
        default=None,
        description="Normalized usage carried by this trace block, when reported.",
    )
    stream_id: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Stable identifier used to append ephemeral fragments to one semantic "
            "trace block."
        ),
    )
    stream_mode: Literal["delta", "snapshot"] = Field(
        default="delta",
        description="Append a fragment, or replace the identified block with a cumulative snapshot.",
    )
    stream_complete: bool | None = Field(
        default=None,
        description="Whether an identified text/reasoning block is complete; null for legacy drivers.",
    )

    def has_visible_content(self) -> bool:
        if self.content.strip():
            return True
        return self.type == "tool" and bool(self.tool_arguments)


class AIResult(BaseModel):
    """Normalized result accumulated from events during a run."""

    prompt: str = Field(description="User prompt sent to the driver")
    system_prompt: str = Field(description="System prompt", default="")
    messages: list[AIMessage] = Field(default_factory=list[AIMessage])
    execution_time: float = 0.0
    result: str = ""
    structured_output: JsonValue = None
    cost: float = 0.0
    usage: AgentUsage = Field(default_factory=lambda: AgentUsage())
    tools_used: list[str] = Field(default_factory=list[str])
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
    success: bool = True

    def add_message(self, ai_message: AIMessage) -> None:
        if ai_message.tool_name:
            ai_message.tool_name = normalize_tool_name(ai_message.tool_name)

        existing = next(
            (message for message in self.messages if ai_message.stream_id
             and message.stream_id == ai_message.stream_id),
            None,
        )
        same_tool_call = (
            ai_message.stream_mode == "snapshot"
            and ai_message.tool_call_external_id is not None
            and existing is not None
            and existing.type == ai_message.type == "tool"
            and existing.tool_call_external_id == ai_message.tool_call_external_id
        )
        if existing is not None and (
            existing.type != ai_message.type
            or (existing.tool_name != ai_message.tool_name and not same_tool_call)
        ):
            raise ValueError("A streamed AIMessage cannot change its type or tool.")

        if existing is not None and ai_message.stream_mode == "snapshot":
            if existing.tool_name != ai_message.tool_name and ai_message.tool_name:
                self.tools_used = [ai_message.tool_name if name == existing.tool_name else name
                                   for name in self.tools_used]
            self.cost += ai_message.cost - existing.cost
            self.execution_time += ai_message.execution_time - existing.execution_time
            if ai_message.usage is not None:
                previous_usage = existing.usage or AgentUsage()
                counters = self.usage.merged(ai_message.usage).model_dump()
                for name, value in previous_usage.model_dump().items():
                    if isinstance(value, (int, float)):
                        counters[name] = max(0, counters[name] - value)
                self.usage = AgentUsage.model_validate(counters)
            self.messages[self.messages.index(existing)] = ai_message.model_copy(deep=True)
            if ai_message.type == "text":
                self.result = "".join(m.content for m in self.messages if m.type == "text")
            return

        self.cost += ai_message.cost
        if ai_message.usage is not None:
            self.usage = self.usage.merged(ai_message.usage)
        self.execution_time += ai_message.execution_time
        if ai_message.content and ai_message.type == "text":
            self.result += ai_message.content
        if ai_message.tool_name:
            self.tools_used.append(ai_message.tool_name)

        empty_tool_start = (
            ai_message.type == "tool"
            and ai_message.stream_id is not None
            and ai_message.tool_call_external_id is not None
        )
        if not ai_message.has_visible_content() and existing is None and not empty_tool_start:
            return
        if existing is not None or (
            ai_message.type == "text" and ai_message.stream_id is None
            and self.messages and self.messages[-1].type == "text"
            and self.messages[-1].stream_id is None
        ):
            last = existing if existing is not None else self.messages[-1]
            last.content += ai_message.content
            last.cost += ai_message.cost
            last.execution_time += ai_message.execution_time
            if ai_message.stream_complete is not None:
                last.stream_complete = ai_message.stream_complete
            if not ai_message.success:
                last.success = False
            return
        self.messages.append(ai_message)

    def detach_trailing_text(self) -> tuple[float, float]:
        elapsed = 0.0
        cost = 0.0
        while self.messages and self.messages[-1].type == "text":
            last = self.messages.pop()
            elapsed += last.execution_time
            cost += last.cost
        self.execution_time -= elapsed
        self.cost -= cost
        return elapsed, cost

    def reconcile_terminal_text(self, final_text: str) -> None:
        """Make one runtime-authoritative final answer replace streamed progress text.

        Streaming runtimes can expose assistant prose before tool calls and only reveal
        their authoritative final answer in the terminal event. Preserve that earlier
        prose as semantic ``thinking`` trace blocks while keeping ``result`` and the
        final text block equal to the runtime's terminal answer.
        """

        final = final_text
        if not final.strip():
            self.result = ""
            self.messages = [message for message in self.messages if message.type != "text"]
            return
        self.result = final

        reconciled: list[AIMessage] = []
        final_inserted = False
        for message in reversed(self.messages):
            if message.type != "text":
                reconciled.append(message)
                continue

            content = message.content
            if not content.strip():
                continue
            if not final_inserted and content.endswith(final):
                prefix = content[: -len(final)].strip()
                reconciled.append(
                    message.model_copy(update={"content": final})
                )
                if prefix:
                    reconciled.append(
                        message.model_copy(
                            update={
                                "type": "tool",
                                "tool_name": "thinking",
                                "content": prefix,
                                "stream_id": f"{message.stream_id}:narration" if message.stream_id else None,
                                "execution_time": 0.0,
                                "cost": 0.0,
                                "usage": None,
                            }
                        )
                    )
                final_inserted = True
                continue
            reconciled.append(
                message.model_copy(
                    update={
                        "type": "tool",
                        "tool_name": "thinking",
                        "cost": 0.0,
                        "usage": None,
                    }
                )
            )

        reconciled.reverse()
        if not final_inserted:
            reconciled.append(AIMessage(type="text", content=final, stream_id=uuid4().hex))
        self.messages = reconciled


WorkingResourceState = Literal["active", "superseded", "stale", "failed"]


class WorkingResource(BaseModel):
    """One durable, server-verified resource used by a Task tree."""

    resource_type: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=2_000)
    label: str = Field(default="", max_length=500)
    revision: int | None = Field(default=None, ge=1)
    state: WorkingResourceState = "active"
    producer_task_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def is_delivery_receipt(self) -> bool:
        """Exclude historical shell heuristics without rewriting their audit record."""
        return (
            self.resource_type == "delivery_receipt"
            and self.reference != "console_exec:git_push"
            and self.role != "delivery_receipt:git_push"
            and self.metadata.get("tool") != "console_exec"
        )


class WorkingSet(BaseModel):
    """Versioned resource ledger shared by one complete Task tree."""

    schema_version: Literal["galaris.working-set/v1"] = "galaris.working-set/v1"
    version: int = Field(default=0, ge=0)
    resources: list[WorkingResource] = Field(default_factory=list[WorkingResource])

    def active(self, role: str | None = None) -> list[WorkingResource]:
        return [
            resource
            for resource in self.resources
            if resource.state == "active"
            and (role is None or resource.role == role)
        ]


class HarnessFailure(BaseModel):
    """Portable failure classification. A retry decision never proves an effect absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["configuration", "unavailable", "protocol", "quota", "timeout", "cancelled", "effect_unknown", "runtime"]
    message: str = Field(max_length=4000)
    retry: Literal["never", "safe", "reconcile"] = "never"
    effects: Literal["none", "possible"] = "possible"


class ExecutionResult(AIResult):
    """Normalized terminal result returned by a driver."""

    schema_version: Literal["galaris.execution-result/v1"] = "galaris.execution-result/v1"
    failure: HarnessFailure | None = None


class AgentEvent(BaseModel):
    """Streaming event independent from any concrete runtime."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["message", "result"]
    message: AIMessage | None = None
    result: ExecutionResult | None = None

    @classmethod
    def from_message(cls, message: AIMessage) -> "AgentEvent":
        return cls(kind="message", message=message)

    @classmethod
    def from_result(cls, result: ExecutionResult) -> "AgentEvent":
        return cls(kind="result", result=result)

    @model_validator(mode="after")
    def payload_is_consistent(self) -> Self:
        if self.kind == "message" and (self.message is None or self.result is not None):
            raise ValueError("A message event must contain only a message.")
        if self.kind == "result" and (self.result is None or self.message is not None):
            raise ValueError("A terminal event must contain only a result.")
        return self


class _DispatchDecisionFields(BaseModel):
    effort: ExecutionEffort = Field(
        default="standard",
        description=(
            "Executor effort policy. Drivers may map high to both a stronger model and a "
            "different managed execution strategy. Use standard for a bounded, explicit, "
            "deterministic operation with straightforward checks, including multiple tool "
            "calls, existing artifacts, named recipients, external side effects, or an "
            "authorized destructive action. Operational risk requires safety controls but "
            "does not itself require high. Use high only for material cognitive complexity: "
            "ambiguity, substantial context recovery, competing hypotheses, complex diagnosis "
            "or recovery, many coupled decisions, or challenging creative or technical work."
        ),
    )
    language: str = "en"

    @field_validator("language", mode="before")
    @classmethod
    def supported_language_or_english(cls, value: Any) -> str:
        lang = str(value or "").strip().lower()
        return lang if is_supported(lang) else "en"


class DispatchDecision(_DispatchDecisionFields):
    # Kept on the durable/public result for deterministic policy and failure diagnostics.
    # Inferred output contracts deliberately omit it: routing does not need generated prose.
    reasoning: str = ""
    route: DispatchRoute = Field(description="Agentic routing path.")


class ActiveDispatchDecision(_DispatchDecisionFields):
    """Structured decision emitted by the current Task dispatcher."""

    route: ActiveDispatchRoute = Field(
        description=(
            "Active Task routing path. EXEC high is preferred for one cohesive outcome; "
            "PLAN requires several independently executable units needing durable coordination."
        )
    )


class TaskDispatchDecision(_DispatchDecisionFields):
    """Task routing constrained by the selected harness's available choices."""

    route: ForcedRoute = Field(description="Select one available Task execution path.")


class ConversationDispatchDecision(BaseModel):
    """Reply-gate decision that cannot select planning or elevated execution."""

    route: ConversationDispatchRoute = Field(description="Conversation reply path.")
    effort: Literal["standard"] = "standard"
    language: str = "en"

    @field_validator("language", mode="before")
    @classmethod
    def supported_language_or_english(cls, value: Any) -> str:
        lang = str(value or "").strip().lower()
        return lang if is_supported(lang) else "en"


class DispatchResult(BaseModel):
    decision_inference: dict[str, Any] | None = None
    prompt: str
    system_prompt: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    execution_time: float = 0.0
    cost: float = 0.0
    tools_used: list[str] = Field(default_factory=list[str])
    success: bool = True
    decision: DispatchDecision
    driver_code: str = ""
    allowed_routes: list[DispatchRoute] = Field(default_factory=list[DispatchRoute])
    policy_notes: list[str] = Field(default_factory=list[str])
    pipeline_policy: dict[str, Any] = Field(default_factory=dict[str, Any])
    conversation_route_directive: ForcedRoute | None = None


class BriefingChoice(BaseModel):
    kind: Literal["process", "tool", "other"]
    identifier: str
    label: str = ""
    reason: str = ""
    score: float | None = None


class BriefingResult(BaseModel):
    prompt: str = ""
    system_prompt: str = ""
    result: str = "NO ISSUES"
    choices: list[BriefingChoice] = Field(default_factory=list[BriefingChoice])
    execution_time: float = 0.0
    cost: float = 0.0
    success: bool = True


@dataclass(frozen=True)
class ToolExposureProfile:
    """Galaris capabilities that may be exposed to a driver."""

    voice_calling: bool = False
    file_tools: bool = False
    console_execution: bool = False

    def supports(self, required_capabilities: frozenset[str]) -> bool:
        """Return whether every named, deny-by-default capability is enabled."""

        return all(bool(getattr(self, name, False)) for name in required_capabilities)


class ResolvedExecutionCapabilities(BaseModel):
    """Capabilities verified for one target, separated from lifecycle management."""

    execution: frozenset[str] = Field(default_factory=frozenset[str])
    management: frozenset[str] = Field(default_factory=frozenset[str])
    unavailable: dict[str, str] = Field(default_factory=dict[str, str])

    def supports_execution(self, capability: str) -> bool:
        return capability in self.execution

    def supports_management(self, capability: str) -> bool:
        return capability in self.management


HarnessCapability = Literal[
    "execute", "streaming", "cancellation", "local_interrupt", "remote_cancel_acknowledged",
    "checkpoints", "checkpoint_rebase", "resume", "effect_reconciliation",
    "semantic_events", "structured_tool_events", "normalized_usage", "taskless_runs", "approvals",
    "voice_calling", "file_tools", "console_execution",
    "status", "start", "stop", "restart", "update", "logs", "refresh",
    "skills", "runtime_files", "mcp", "memory",
]

# Observability and recovery evidence are guarantees, never optional switches.
CONFIGURABLE_HARNESS_CAPABILITIES: frozenset[HarnessCapability] = frozenset({
    "execute", "streaming", "cancellation", "taskless_runs", "resume",
    "voice_calling", "file_tools", "console_execution",
    "status", "start", "stop", "restart", "update", "logs", "refresh",
})


class HarnessExecutionPolicy(BaseModel):
    """Common, restrictive operator settings available for every harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    disabled_capabilities: frozenset[HarnessCapability] = frozenset()
    max_parallel_tasks: int | None = Field(default=None, ge=1, le=100)
    stream_close_timeout_seconds: float = Field(default=5.0, gt=0, le=120, allow_inf_nan=False)
    execution_timeout_seconds: float | None = Field(default=None, gt=0, le=86400, allow_inf_nan=False)
    idle_timeout_seconds: float | None = Field(default=None, gt=0, le=3600, allow_inf_nan=False)
    max_message_bytes: int = Field(default=1_000_000, ge=1024, le=4_000_000)
    # Also bounds each replacement progress/checkpoint snapshot individually.
    max_result_bytes: int = Field(default=16_000_000, ge=1024, le=64_000_000)
    # Cumulative emitted message/result events, excluding replacement snapshots.
    max_stream_bytes: int = Field(default=64_000_000, ge=1024, le=256_000_000)

    @model_validator(mode="after")
    def configurable_features_only(self) -> Self:
        if self.disabled_capabilities - CONFIGURABLE_HARNESS_CAPABILITIES:
            raise ValueError("Protocol guarantees and runtime-native features cannot be disabled by the host.")
        return self


class HarnessCancellationReceipt(BaseModel):
    """A cancellation request is distinct from evidence that execution has stopped."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    scope: Literal["local", "remote"]
    state: Literal["requested", "confirmed", "unknown"]


@runtime_checkable
class DriverCancellationControl(Protocol):
    async def request_cancellation(self, run_id: UUID) -> HarnessCancellationReceipt: ...


class HarnessCapabilityDescriptor(BaseModel):
    """Versioned negotiation result shared by execution, configuration and presentation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["galaris.harness-capabilities/v1"] = "galaris.harness-capabilities/v1"
    implemented: frozenset[HarnessCapability]
    configurable: frozenset[HarnessCapability] = frozenset()
    configured: frozenset[HarnessCapability]
    verified: frozenset[HarnessCapability]
    effective: frozenset[HarnessCapability]
    unavailable: dict[str, str] = Field(default_factory=dict[str, str])
    policy: HarnessExecutionPolicy = Field(default_factory=HarnessExecutionPolicy)
    revision: int = 0

    @model_validator(mode="after")
    def consistent_capabilities(self) -> Self:
        if self.effective != self.implemented & self.configured & self.verified:
            raise ValueError("Effective capabilities must be the intersection of all three guarantees.")
        return self


class ResolvedExecutionTarget(BaseModel):
    """Secret-free target snapshot frozen before a driver starts."""

    provider_code: str = Field(min_length=1, max_length=100)
    target_ref: str = Field(min_length=1, max_length=300)
    revision: str = Field(default="", max_length=200)
    transport: str = Field(default="", max_length=100)
    ready: bool = True
    descriptor: HarnessCapabilityDescriptor | None = None
    capabilities: ResolvedExecutionCapabilities = Field(
        default_factory=ResolvedExecutionCapabilities
    )
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict[str, str | int | float | bool | None]
    )


@dataclass(frozen=True)
class ConfiguredHarnessSelection:
    """Provider-neutral selection returned through the injected Harness port."""

    id: UUID
    name: str
    provider_code: str
    driver_code: str
    revision: int
    status: str
    max_parallel_tasks: int | None = 1
    model: str | None = None
    capabilities: frozenset[str] = frozenset()
    metadata: Mapping[str, str | int | float | bool | None] = field(
        default_factory=dict[str, str | int | float | bool | None]
    )
    pipeline_policy: DriverPipelinePolicy | None = None


@dataclass(frozen=True)
class DriverPipelinePolicy:
    """Static pipeline policy declared in code by each driver."""

    use_planner: bool
    use_briefing: bool
    briefing_efforts: frozenset[ExecutionEffort] = frozenset()
    execution_efforts: frozenset[ExecutionEffort] = frozenset({"standard"})
    # True only when execution uses Galaris model routing and its durable LLMCalls.
    # A runtime calling its own provider cannot use the Galaris high model tier.
    uses_llm_calls: bool = False

    def __post_init__(self) -> None:
        efforts = frozenset(self.execution_efforts)
        briefing = frozenset(self.briefing_efforts)
        if "standard" not in efforts or efforts - {"standard", "high"}:
            raise ValueError("A harness must expose standard execution and valid effort levels.")
        if briefing - efforts:
            raise ValueError("Briefing must lead to an execution effort supported by the harness.")
        if not self.uses_llm_calls:
            efforts = efforts - {"high"}
            briefing = briefing - {"high"}
        object.__setattr__(self, "execution_efforts", efforts)
        object.__setattr__(self, "briefing_efforts", briefing)

    def dispatch_choices(self) -> tuple[tuple[ForcedRoute, ExecutionEffort], ...]:
        choices: list[tuple[ForcedRoute, ExecutionEffort]] = [
            ("EXEC", effort) for effort in ("standard", "high")
            if effort in self.execution_efforts
        ]
        choices.extend(
            ("BRIEFING", effort) for effort in ("standard", "high")
            if self.allows_briefing(effort)
        )
        if self.use_planner:
            choices.append(("PLAN", "high"))
        return tuple(choices)

    def allows_briefing(self, effort: ExecutionEffort) -> bool:
        return self.use_briefing and effort in self.briefing_efforts

    def allowed_routes(self, routes: set[str]) -> tuple[set[str], list[str]]:
        allowed = set(routes)
        notes: list[str] = []
        if not self.use_planner and "PLAN" in allowed:
            allowed.discard("PLAN")
            notes.append("PLAN excluded by the driver's static policy")
        if not self.use_briefing or not self.briefing_efforts:
            if "BRIEFING" in allowed:
                allowed.discard("BRIEFING")
                notes.append("BRIEFING excluded by the driver's static policy")
        return allowed, notes


@dataclass(frozen=True)
class AgentDriverSpec:
    """Central descriptor for a concrete driver."""

    code: str
    label_key: str
    factory_path: str
    tool_profile: ToolExposureProfile
    pipeline_policy: DriverPipelinePolicy
    enabled_setting: str | None = None
    required_settings: tuple[str, ...] = ()
    manages_runtime: bool = False
    supports_streaming: bool = True
    supports_cancellation: bool = False
    standard_execution_strategy: str = "direct"
    high_execution_strategy: str = "direct"
    execution_capabilities: frozenset[str] = frozenset()
    management_capabilities: frozenset[str] = frozenset()
    # Applies to every driver, including embedded and third-party contributions.
    stream_close_timeout_seconds: float = 5.0
    max_parallel_tasks: int | None = 1
    transport: str = ""
    checkpoint_policy_path: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.stream_close_timeout_seconds) or self.stream_close_timeout_seconds <= 0:
            raise ValueError("stream_close_timeout_seconds must be finite and positive.")
        if self.max_parallel_tasks is not None and self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be positive or None.")
        # These flags own dispatch. The published capability set must agree with them.
        capabilities = set(self.execution_capabilities) - {"streaming", "cancellation"}
        if self.supports_streaming:
            capabilities.add("streaming")
        if self.supports_cancellation:
            capabilities.add("cancellation")
        object.__setattr__(self, "execution_capabilities", frozenset(capabilities))

    def allowed_routes(self, routes: set[str]) -> tuple[set[str], list[str]]:
        allowed, notes = self.pipeline_policy.allowed_routes(routes)
        if notes:
            notes = [f"{note} ({self.code})" for note in notes]
        return allowed, notes

    def execution_strategy_for(self, effort: ExecutionEffort) -> str:
        """Return the immutable runtime strategy declared for an effort level."""

        return (
            self.high_execution_strategy
            if effort == "high"
            else self.standard_execution_strategy
        )


@dataclass(frozen=True)
class DriverStatus:
    code: str
    declared: bool
    enabled: bool
    configured: bool
    ready: bool
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.declared and self.enabled and self.configured and self.ready


class AgentDriverError(RuntimeError):
    """Driver resolution or execution error."""


class UnknownAgentDriverError(AgentDriverError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Unknown agent driver: {code!r}.")


class DisabledAgentDriverError(AgentDriverError):
    def __init__(self, code: str, reason: str | None = None) -> None:
        self.code = code
        detail = f" ({reason})" if reason else ""
        super().__init__(f"Disabled agent driver: {code!r}{detail}.")


class AgentModelConfigurationError(AgentDriverError):
    """No usable executor model could be resolved."""


class StaleAgentRunError(RuntimeError):
    """Raised when a run tries to persist work for a superseded Task objective."""


class ReasoningDegenerationError(RuntimeError):
    """Raised when generated reasoning is stuck in a repeated pattern."""


@dataclass(frozen=True)
class ResolvedModel:
    id: int
    code: str
    model_name: str
    label: str
    requested_effort: ExecutionEffort
    reasoning_effort: ReasoningEffort | None = None
    fallback_used: bool = False


@dataclass(frozen=True)
class AgentSnapshot:
    id: int
    code: str
    first_name: str
    last_name: str
    driver_code: str
    gender: Literal["M", "F"] = "M"
    llm_id: int | None = None
    personality: str | None = None
    job_description: str | None = None
    job_title: str | None = None
    driver_config: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class AgentRunCheckpoint:
    """Durable runtime state used to observe and resume one driver run."""

    driver_code: str
    runtime_run_id: str
    status: str
    result: ExecutionResult | None = None
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])


class CheckpointAssessment(BaseModel):
    """A driver-owned recovery verdict; payload details never cross into orchestration."""

    state: Literal["safe", "reconcile", "unsafe"]
    reason: str = ""
    execution_strategy: str = "direct"

    @property
    def resumable(self) -> bool:
        return self.state in {"safe", "reconcile"}


@runtime_checkable
class DriverCheckpointPolicy(Protocol):
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment: ...

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None: ...


ToolEffectPolicy = Literal["read", "idempotent", "non_idempotent"]
ToolConcurrencyPolicy = Literal["safe", "exclusive"]


class AgentRunIdentityV1(BaseModel):
    """Stable identifiers that correlate orchestration, runtime, LLM and tools."""

    task_id: UUID | None = None
    attempt_id: UUID | None = None
    run_id: UUID
    runtime_run_id: str | None = Field(default=None, max_length=300)


class AgentRunLimitsV1(BaseModel):
    """Portable execution limits understood without importing Galaris settings."""

    request_limit: int | None = Field(default=None, ge=1)
    tool_call_limit: int | None = Field(default=None, ge=1)
    tool_parallelism: int = Field(default=1, ge=1, le=32)
    context_tokens: int | None = Field(default=None, ge=1)


class AgentRunEnvelopeV1(BaseModel):
    """Bounded, serializable payload suitable for an out-of-process harness.

    Runtime credentials and Python callbacks are deliberately absent. Concrete drivers
    continue to receive ``AgentRunRequest`` locally, but future transports can consume this
    object without depending on ORM models or process-local functions.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["galaris.agent-run/v1"] = "galaris.agent-run/v1"
    identity: AgentRunIdentityV1
    target: ResolvedExecutionTarget
    agent_id: int
    agent_code: str = Field(max_length=200)
    effort: ExecutionEffort
    execution_strategy: str = Field(default="direct", max_length=100)
    objective: str = Field(max_length=200_000)
    label: str = Field(default="", max_length=1_000)
    model_id: int
    model_code: str = Field(max_length=200)
    model_name: str = Field(max_length=500)
    reasoning_effort: ReasoningEffort | None = None
    system_instructions: str = Field(default="", max_length=300_000)
    shared_context: str = Field(default="", max_length=300_000)
    conversation_history: tuple[dict[str, Any], ...] = ()
    messaging_context: dict[str, str] = Field(default_factory=dict[str, str])
    resource_uris: tuple[str, ...] = ()
    tool_catalog_version: str | None = Field(default=None, max_length=200)
    approval_action: Literal["auto", "deny_agent", "ask"] = "ask"
    limits: AgentRunLimitsV1 = Field(default_factory=AgentRunLimitsV1)
    fingerprints: dict[str, str] = Field(default_factory=dict[str, str])
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict[str, str | int | float | bool | None]
    )

    @field_validator("conversation_history")
    @classmethod
    def bounded_history(
        cls, value: tuple[dict[str, Any], ...]
    ) -> tuple[dict[str, Any], ...]:
        if len(value) > 200:
            raise ValueError("conversation_history must contain at most 200 messages")
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > 600_000:
            raise ValueError("conversation_history must not exceed 600000 UTF-8 bytes")
        return value

    @field_validator("resource_uris")
    @classmethod
    def canonical_resource_references(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) > 500:
            raise ValueError("resource_uris must contain at most 500 references")
        if any(len(item) > 2_000 for item in normalized):
            raise ValueError("resource_uris entries must not exceed 2000 characters")
        invalid = [item for item in normalized if "://" not in item]
        if invalid:
            raise ValueError("resource_uris must contain canonical URI references")
        return normalized

    @field_validator("messaging_context")
    @classmethod
    def bounded_messaging_context(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {
            str(key).strip(): str(item).strip()
            for key, item in value.items()
            if str(key).strip() and str(item).strip()
        }
        if len(normalized) > 40:
            raise ValueError("messaging_context must contain at most 40 entries")
        if any(len(key) > 100 or len(item) > 2_000 for key, item in normalized.items()):
            raise ValueError("messaging_context entries exceed their size limit")
        return normalized


AgentRunEventKind = Literal[
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "message.completed",
    "model.completed",
    "tool.completed",
    "tool.failed",
    "process.updated",
    "approval.requested",
    "resource.updated",
    "checkpoint.saved",
    "warning",
]


class AgentRunEventV1(BaseModel):
    """Sequenced semantic event persisted independently from token deltas."""

    schema_version: Literal["galaris.agent-event/v1"] = "galaris.agent-event/v1"
    identity: AgentRunIdentityV1
    sequence: int = Field(ge=1)
    kind: AgentRunEventKind
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    message: AIMessage | None = None
    result: ExecutionResult | None = None
    usage: AgentUsage | None = None
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])

    @model_validator(mode="after")
    def terminal_payload_is_consistent(self) -> Self:
        if self.kind in {"run.completed", "run.failed", "run.cancelled"}:
            if self.result is None:
                raise ValueError("A terminal run event must contain a result")
        elif self.result is not None:
            raise ValueError("Only a terminal run event may contain a result")
        return self

    @property
    def terminal(self) -> bool:
        return self.kind in {"run.completed", "run.failed", "run.cancelled"}


@dataclass(frozen=True)
class AgentRunControl:
    """Process-local control plane kept out of the serializable run envelope."""

    save_progress: Callable[[ExecutionResult], Awaitable[None]] | None = None
    save_checkpoint: Callable[[AgentRunCheckpoint], Awaitable[None]] | None = None
    publish_event: Callable[[AgentRunEventV1], Awaitable[None]] | None = None


@dataclass(frozen=True)
class AgentContextRequest:
    """Driver-neutral input offered to registered context providers."""

    task_id: UUID | None
    agent: AgentSnapshot
    objective: str
    stage: Literal["planning", "execution"] = "execution"
    label: str = ""
    messenger_connection_id: int | None = None
    message_platform: str | None = None
    message_group_id: str | None = None
    topic_id: UUID | None = None
    contact_memory_item_id: UUID | None = None
    task_data: Mapping[str, Any] = field(default_factory=dict[str, Any])
    include_historical_context: bool = True
    fallback_history: tuple[Mapping[str, Any], ...] = ()
    available_history: tuple[Mapping[str, Any], ...] = ()
    frozen_capsule: Mapping[str, Any] | None = None


class AgentContextCandidate(BaseModel):
    """One sourced, bounded fragment eligible for interlocutor continuity."""

    key: str = Field(min_length=1, max_length=500)
    kind: Literal["conversation", "task", "resource", "memory"]
    reference: str = Field(min_length=1, max_length=2_000)
    title: str = Field(default="", max_length=500)
    excerpt: str = Field(default="", max_length=12_000)
    revision: int | None = Field(default=None, ge=1)
    occurred_at: datetime | None = None
    base_score: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])


class AgentContextCapsule(BaseModel):
    """Frozen, contact-scoped continuity manifest shared by one Task tree."""

    version: Literal[1] = 1
    contact_memory_item_id: UUID
    entries: list[AgentContextCandidate] = Field(
        default_factory=list[AgentContextCandidate]
    )
    rendered: str = Field(default="", max_length=16_000)
    truncated: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class AgentContextContribution:
    """One bounded context contribution composed before driver selection."""

    system_instructions: str = ""
    shared_context: str = ""
    memory_context: str = ""
    continuity_context: str = ""
    conversation_history: tuple[Mapping[str, Any], ...] | None = None
    candidates: tuple[AgentContextCandidate, ...] = ()
    messaging_context: Mapping[str, Any] = field(default_factory=dict[str, Any])
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class AgentRunContext:
    """Final context projection consumed identically by every driver."""

    system_instructions: str = ""
    shared_context: str = ""
    memory_context: str = ""
    continuity_context: str = ""
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    context_capsule: AgentContextCapsule | None = None
    messaging_context: Mapping[str, Any] = field(default_factory=dict[str, Any])
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class RealtimeAgentContext:
    """Agent identity and governed context prepared for a live provider session."""

    agent: AgentSnapshot
    instructions: str
    shared_context: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class AgentRunRequest:
    """Immutable request passed to a concrete driver."""

    run_id: UUID
    task_id: UUID | None
    agent: AgentSnapshot
    driver_code: str
    effort: ExecutionEffort
    objective: str
    model: ResolvedModel
    attempt_id: UUID | None = None
    target: ResolvedExecutionTarget | None = None
    execution_strategy: str = "direct"
    label: str = ""
    messenger_connection_id: int | None = None
    message_platform: str | None = None
    message_group_id: str | None = None
    parent_task_id: UUID | None = None
    source_task_id: UUID | None = None
    requester_agent_id: int | None = None
    sender_is_ai: bool = False
    task_data: Mapping[str, Any] = field(default_factory=dict[str, Any])
    dispatch_result: DispatchResult | None = None
    briefing_result: BriefingResult | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    approval_action: Literal["auto", "deny_agent", "ask"] = "ask"
    executor_system_prompt: str = ""
    system_instructions: str = ""
    shared_context: str = ""
    memory_context: str = ""
    continuity_context: str = ""
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    attachments: tuple[Mapping[str, Any], ...] = ()
    messaging_context: Mapping[str, Any] = field(default_factory=dict[str, Any])
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])
    resume_checkpoint: AgentRunCheckpoint | None = None
    limits: AgentRunLimitsV1 = field(default_factory=AgentRunLimitsV1)
    control: AgentRunControl = field(default_factory=AgentRunControl)

    @property
    def id(self) -> UUID:
        return self.task_id or self.run_id

    @property
    def agent_id(self) -> int:
        return self.agent.id

    @property
    def parent_id(self) -> UUID | None:
        return self.parent_task_id

    @property
    def data(self) -> Mapping[str, Any]:
        return self.task_data

    @property
    def messages(self) -> tuple[Mapping[str, Any], ...]:
        return self.conversation_history

    @property
    def model_id(self) -> int:
        return self.model.id

    def get_dispatch_result(self) -> DispatchResult | None:
        return self.dispatch_result

    def get_briefing_result(self) -> BriefingResult | None:
        return self.briefing_result

    @property
    def save_progress(self) -> Callable[[ExecutionResult], Awaitable[None]] | None:
        """Compatibility access to the local control plane."""

        return self.control.save_progress

    @property
    def save_checkpoint(
        self,
    ) -> Callable[[AgentRunCheckpoint], Awaitable[None]] | None:
        """Compatibility access to the local control plane."""

        return self.control.save_checkpoint

    @property
    def publish_event(self) -> Callable[[AgentRunEventV1], Awaitable[None]] | None:
        return self.control.publish_event

    def to_envelope(self) -> AgentRunEnvelopeV1:
        """Project this local request to its secret-free transport contract."""

        target = self.target or ResolvedExecutionTarget(
            provider_code=self.driver_code,
            target_ref=f"driver:{self.driver_code}",
        )
        checkpoint = self.resume_checkpoint
        runtime_run_id = (
            checkpoint.runtime_run_id
            if checkpoint is not None and checkpoint.driver_code == self.driver_code
            else None
        )
        resources: list[str] = []
        working_set = self.task_data.get("working_set")
        if isinstance(working_set, Mapping):
            working_set_data = cast(Mapping[str, object], working_set)
            raw_resources = working_set_data.get("resources")
            if isinstance(raw_resources, Sequence) and not isinstance(
                raw_resources, (str, bytes)
            ):
                for raw_resource in cast(Sequence[object], raw_resources):
                    if not isinstance(raw_resource, Mapping):
                        continue
                    resource_data = cast(Mapping[str, object], raw_resource)
                    reference = str(resource_data.get("reference") or "").strip()
                    if "://" in reference:
                        resources.append(reference)
        for attachment in self.attachments:
            uri = str(attachment.get("uri") or "").strip()
            if "://" in uri:
                resources.append(uri)
        catalog_version = next(
            (
                str(value).strip()
                for value in (
                    self.metadata.get("tool_catalog_version"),
                    self.task_data.get("plan_catalog_version"),
                    self.task_data.get("tool_catalog_version"),
                )
                if value not in (None, "")
            ),
            None,
        )
        fingerprints = {
            key: str(value)
            for key, value in self.metadata.items()
            if key.endswith("_fingerprint") and value not in (None, "")
        }
        messaging_context = {
            str(key): str(value)
            for key, value in self.messaging_context.items()
            if value not in (None, "", False)
        }
        task_context_aliases = {
            "connection_id": self.messenger_connection_id,
            "platform": self.message_platform,
            "room_id": self.message_group_id,
            "room_locator": self.task_data.get("room_locator"),
            "room_label": self.task_data.get("room_label"),
            "message_type": self.task_data.get("message_type"),
            "message_id": self.task_data.get("message_id"),
            "conversation_round_id": self.task_data.get("conversation_round_id"),
            "user_id": (
                self.task_data.get("sender.user_id")
                or self.task_data.get("sender.id")
            ),
            "user_name": (
                self.task_data.get("sender.nickname")
                or self.task_data.get("sender.display_name")
            ),
            "sender_is_ai": self.task_data.get("sender_is_ai"),
            "language": self.task_data.get("language"),
        }
        for key, value in task_context_aliases.items():
            if key not in messaging_context and value not in (None, ""):
                messaging_context[key] = str(value)
        return AgentRunEnvelopeV1(
            identity=AgentRunIdentityV1(
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                run_id=self.run_id,
                runtime_run_id=runtime_run_id,
            ),
            target=target,
            agent_id=self.agent.id,
            agent_code=self.agent.code,
            effort=self.effort,
            execution_strategy=self.execution_strategy,
            objective=self.objective,
            label=self.label,
            model_id=self.model.id,
            model_code=self.model.code,
            model_name=self.model.model_name,
            reasoning_effort=self.model.reasoning_effort,
            system_instructions=(
                self.executor_system_prompt.strip()
                or self.system_instructions.strip()
            ),
            shared_context=self.shared_context,
            conversation_history=tuple(dict(item) for item in self.conversation_history),
            messaging_context=messaging_context,
            resource_uris=tuple(resources),
            tool_catalog_version=catalog_version,
            approval_action=self.approval_action,
            limits=self.limits,
            fingerprints=fingerprints,
            metadata={
                "driver_code": self.driver_code,
                "planner_used": self.parent_task_id is not None,
                "briefing_used": self.briefing_result is not None,
            },
        )


@dataclass(frozen=True)
class AgentTaskDraft:
    """Generic durable creation request sent to ``app.task``."""

    label: str
    objective: str | None = None
    status: TaskPhase = TaskPhase.CREATE
    paused: bool = False
    ai: bool = False
    effort: ExecutionEffort = "standard"
    agent_id: int | None = None
    goal_id: UUID | None = None
    requester_agent_id: int | None = None
    messenger_connection_id: int | None = None
    message_platform: str | None = None
    message_group_id: str | None = None
    data: Mapping[str, Any] | None = None
    messages: tuple[Mapping[str, Any], ...] | None = None
    parent_id: UUID | None = None
    source_task_id: UUID | None = None
    plan: Mapping[str, Any] | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class AgentTaskBlocker:
    """Bounded task identity exposed to Harness configuration workflows."""

    id: UUID
    label: str


@dataclass(frozen=True)
class AgentTaskBlockers:
    """Open root Tasks that currently prevent an agent Harness change."""

    paused_tasks: tuple[AgentTaskBlocker, ...] = ()
    active_count: int = 0
    active_tasks: tuple[AgentTaskBlocker, ...] = ()


class AgentTask(Protocol):
    """Runtime-neutral task view consumed by the agentic domain.

    Persistence adapters may expose richer ORM objects, but drivers, routing and
    planning only depend on this stable surface.
    """

    id: UUID
    label: str
    objective: str | None
    status: TaskPhase
    paused: bool
    ai: bool
    feedback: str | None
    cost: float
    effort: str
    forced_route: str | None
    forced_effort: str | None
    reasoning_effort_override: ReasoningEffort | None
    auto_approve: bool
    agent_id: int | None
    goal_id: UUID | None
    topic_id: UUID | None
    contact_memory_item_id: UUID | None
    requester_agent_id: int | None
    messenger_connection_id: int | None
    message_platform: str | None
    message_group_id: str | None
    data: dict[str, Any] | None
    messages: Sequence[object] | None
    parent_id: UUID | None
    source_task_id: UUID | None
    plan: dict[str, Any] | None
    consecutive_failures: int
    last_error: str | None
    agent: Any | None

    def get_dispatch_result(self) -> DispatchResult | None: ...
    def get_briefing_result(self) -> BriefingResult | None: ...
    def get_execution_result(self) -> ExecutionResult | None: ...
    def set_dispatch_result(self, result: DispatchResult) -> None: ...
    def set_briefing_result(self, result: BriefingResult) -> None: ...
    def set_execution_result(self, result: ExecutionResult) -> None: ...


class AgentDriver(Protocol):
    @property
    def spec(self) -> AgentDriverSpec: ...

    async def run(self, request: AgentRunRequest) -> ExecutionResult: ...

    def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, run_id: UUID) -> None: ...


@runtime_checkable
class DriverConfigurationProvider(Protocol):
    """Optional capability for drivers that own persisted configuration."""

    async def execution_configuration(self, agent: Any) -> dict[str, Any]: ...


@runtime_checkable
class DriverTargetProvider(Protocol):
    def execution_target(
        self, agent_id: int, configuration: Mapping[str, Any],
    ) -> ResolvedExecutionTarget: ...
