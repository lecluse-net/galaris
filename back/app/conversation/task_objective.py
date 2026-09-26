"""Build complete Task labels and objectives from one conversation round."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from core.params import Params, params_service, prompt_default
from core.i18n import t
from core.util import convert_to_html, normalize_html

from app.agent import (
    AgentContextRequest,
    AgentModelConfigurationError,
    AgentSnapshot,
    build_agent_run_context,
    current_message_data,
    get_agent_record,
    linked_work_context,
    message_prompt,
)
from app.llm import (
    LLMCallPurpose,
    StructuredOutputRetry,
    llm_service,
    model_usages,
    run_structured,
)

from .contracts import ConversationTurn

_REFERENCE_RE = re.compile(
    r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\[\]{}\"']+"
)
_REFERENCE_TRAILING = ".,;:!?)]}"


def built_in_task_objective_system_prompt() -> str:
    """Read the repository default without accessing runtime state."""

    value = str(
        prompt_default(Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT) or ""
    ).strip()
    if not value:
        raise RuntimeError("Missing built-in Task objective system prompt.")
    return value


async def task_objective_system_prompt() -> str:
    """Resolve the editable production prompt used during Task admission."""

    value = str(
        await params_service.get_or_default(
            Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT
        )
        or ""
    ).strip()
    return value or built_in_task_objective_system_prompt()


class _GeneratedTaskFields(BaseModel):
    """Model-owned label and context; admission preserves the request separately."""

    label: str = Field(min_length=1, max_length=400)
    objective: str = Field(
        min_length=1, max_length=200_000,
        description=(
            "HTML context supplement for executing this Task without conversation history. "
            "Resolve references, retain prior applicable constraints and define the assigned scope. "
            "The server preserves the source request separately; do not rewrite or replace it."
        ),
    )

    @field_validator("label")
    @classmethod
    def compact_label(cls, value: str) -> str:
        compact = " ".join(value.split())
        if not compact:
            raise ValueError("Task label cannot be empty.")
        return compact

    @field_validator("objective")
    @classmethod
    def clean_objective(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Task objective cannot be empty.")
        # Reject invalid editorial HTML while structured output can still retry,
        # before Task admission invokes the same content contract.
        normalize_html(clean)
        return clean


def _connection_id(turn: ConversationTurn) -> int | None:
    raw = turn.messaging_context.get("connection_id")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw))
    except ValueError:
        return None
    return value if value > 0 else None


def _latest_task_data(turn: ConversationTurn) -> dict[str, Any]:
    latest: dict[str, Any] = (
        current_message_data(turn.messages[-1], language=turn.language)
        if turn.messages
        else {"language": turn.language}
    )
    room_id = str(turn.messaging_context.get("room_id") or "")
    participant_id = str(
        turn.messaging_context.get("participant_id")
        or latest.get("sender.id")
        or ""
    )
    latest.update(
        {
            "connection_id": _connection_id(turn),
            "messenger_connection_id": _connection_id(turn),
            "platform": str(
                turn.messaging_context.get("platform") or "conversation"
            ),
            "group_id": room_id,
            "room_id": room_id,
            "room_locator": turn.messaging_context.get("room_locator"),
            "room_label": turn.messaging_context.get("room_label"),
            "message_type": str(
                turn.messaging_context.get("room_kind")
                or ("voice" if turn.origin == "voice" else "conversation")
            ),
            "user_id": participant_id,
            "sender.user_id": participant_id,
            "sender.nickname": latest.get("sender.display_name"),
            "sender.agent_id": latest.get("sender_agent_id"),
            "sender_is_ai": turn.sender_is_ai,
            "origin": (
                "voice_conversation" if turn.origin == "voice" else "conversation"
            ),
        }
    )
    return latest


def _render_messages(messages: Sequence[Mapping[str, Any]]) -> str:
    rendered = [message_prompt(message) for message in messages]
    return "\n\n".join(item for item in rendered if item.strip())


def _message_identity(message: Mapping[str, object]) -> str:
    return str(
        message.get("external_message_id")
        or message.get("id")
        or message.get("messenger_message_id")
        or ""
    ).strip()


def _conversation_chronology(
    context_history: Sequence[Mapping[str, Any]],
    turn_history: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, Any], ...]:
    """Keep provider history while guaranteeing that this admitted turn is present."""

    merged: list[Mapping[str, Any]] = [dict(message) for message in context_history]
    known_ids = {
        identity for message in merged if (identity := _message_identity(message))
    }
    for message in turn_history:
        identity = _message_identity(message)
        if identity and identity in known_ids:
            continue
        merged.append(dict(message))
        if identity:
            known_ids.add(identity)
    return tuple(merged)


def _section(title: str, content: str) -> str:
    clean = content.strip()
    return f"## {title}\n\n{clean}" if clean else ""


def source_request_html(turn: ConversationTurn) -> str:
    """Quote admitted input as text, including literal markup and file references."""

    source = turn.source_request if turn.source_request is not None else turn.objective
    return convert_to_html(source, "text/plain")


def compose_task_objective(turn: ConversationTurn, context: str) -> str:
    """Keep the source outside model control in the objective all runtimes receive."""

    source_heading = escape(t("conversation.task_source_request", lang=turn.language))
    context_heading = escape(t("conversation.task_execution_context", lang=turn.language))
    return normalize_html(
        f"<h2>{source_heading}</h2><blockquote>{source_request_html(turn)}</blockquote>"
        f"<h2>{context_heading}</h2>{normalize_html(context)}"
    )


def _references(text: str) -> frozenset[str]:
    return frozenset(
        match.group(0).rstrip(_REFERENCE_TRAILING)
        for match in _REFERENCE_RE.finditer(text)
    )


def _objective_linked_work(turn: ConversationTurn) -> tuple[Mapping[str, object], ...]:
    """Project reusable resources without promoting transport probes into new work."""

    requested = _references(turn.objective + "\n" + _render_messages(turn.messages))
    result: list[Mapping[str, object]] = []
    for item in turn.linked_work:
        projected = dict(item)
        raw_resources = item.get("working_set")
        if not isinstance(raw_resources, list):
            result.append(projected)
            continue
        resources: list[Mapping[str, object]] = []
        for raw in cast(list[object], raw_resources):
            if not isinstance(raw, Mapping):
                continue
            resource = cast(Mapping[str, object], raw)
            reference = str(resource.get("reference") or "")
            metadata_raw = resource.get("metadata")
            metadata: Mapping[str, object] = (
                cast(Mapping[str, object], metadata_raw) if isinstance(metadata_raw, Mapping) else {}
            )
            operation = str(metadata.get("last_operation") or "")
            web_reference = reference.startswith(("https://", "http://"))
            try:
                robots_probe = urlsplit(reference).path.casefold() == "/robots.txt"
            except ValueError:
                robots_probe = False
            probe = web_reference and operation in {"file_info", "file_read"} and (
                operation == "file_info" or robots_probe
            )
            if reference not in requested and (
                resource.get("state", "active") != "active"
                or resource.get("resource_type") in {"delivery_receipt", "messenger_destination"}
                or (probe and metadata.get("produced") is not True)
            ):
                continue
            resources.append(resource)
        projected["working_set"] = resources
        result.append(projected)
    return tuple(result)


async def generate_task_fields(
    turn: ConversationTurn,
    *,
    label_hint: str,
    objective_hint: str,
) -> tuple[str, str, float]:
    """Generate a label and supplementary context for the server-owned request."""

    agent = await get_agent_record(turn.agent_id)
    if agent is None:
        raise LookupError(f"Agent {turn.agent_id} not found.")
    llm = await llm_service.get_profile_llm(model_usages.EXECUTOR, agent=agent)
    if llm is None:
        raise AgentModelConfigurationError(
            "No standard model is configured to construct the Task objective."
        )
    system_prompt = await task_objective_system_prompt()

    title = getattr(agent, "title", None)
    snapshot = AgentSnapshot(
        id=int(agent.id),
        code=str(agent.code),
        first_name=str(agent.first_name),
        last_name=str(agent.last_name),
        driver_code=str(getattr(agent, "agent_driver", "internal") or "internal"),
        gender="F" if getattr(title, "gender", None) == "F" else "M",
        llm_id=int(llm.id),
        personality=getattr(agent, "personality", None),
        job_description=getattr(agent, "job_description", None),
        job_title=getattr(agent, "job_title", None),
    )
    context = await build_agent_run_context(
        AgentContextRequest(
            task_id=None,
            agent=snapshot,
            objective=turn.objective,
            stage="planning",
            label=label_hint,
            messenger_connection_id=_connection_id(turn),
            message_platform=str(
                turn.messaging_context.get("platform") or "conversation"
            ),
            message_group_id=str(turn.messaging_context.get("room_id") or ""),
            topic_id=turn.topic_id,
            contact_memory_item_id=turn.contact_memory_item_id,
            task_data=_latest_task_data(turn),
            fallback_history=tuple(dict(message) for message in turn.messages),
        )
    )
    history = _render_messages(
        _conversation_chronology(context.conversation_history, turn.messages)
    )
    continuity = context.continuity_context
    memory = context.memory_context
    if not memory and not continuity:
        continuity = context.shared_context
    linked = linked_work_context(_objective_linked_work(turn))
    hint = json.dumps(
        {
            "label_hint": label_hint,
            "objective_hint": objective_hint,
        },
        ensure_ascii=False,
        indent=2,
    )
    prompt = "\n\n".join(
        section
        for section in (
            "# Task creation input",
            "The server will quote the source request unchanged in the Task objective. "
            "Your objective field supplies complementary execution context, not a replacement. "
            "The executor has no conversation history: preserve applicable earlier requirements "
            "and corrections, resolve references, and identify this Task's assigned scope. "
            "Do not weaken a requirement or silently substitute a different deliverable.",
            _section("Source request preserved by the server", turn.source_request
                     if turn.source_request is not None else turn.objective),
            "Linked resources are context, not additional requirements. Reuse relevant documents "
            "and sources; do not turn past diagnostics or delivery receipts into work unless requested.",
            _section("Current admitted request", turn.objective),
            _section("Task submission hint", hint),
            _section("Canonical conversation chronology", history),
            _section("Long-term memory", memory),
            _section("Continuity context", continuity),
            _section("Linked work", linked),
        )
        if section
    )
    allowed_references = _references(prompt)

    def validate_references(output: _GeneratedTaskFields) -> _GeneratedTaskFields:
        unknown = sorted(_references(output.objective) - allowed_references)
        if unknown:
            raise StructuredOutputRetry(
                "The objective contains references absent from the supplied context: "
                + ", ".join(unknown[:10])
                + ". Remove them or copy the exact supplied references."
            )
        return output

    inference = await run_structured(
        llm=llm,
        output_type=_GeneratedTaskFields,
        prompt=prompt,
        system_prompt=system_prompt,
        task_id=None,
        agent_id=turn.agent_id,
        temperature=0.0,
        request_limit=3,
        output_retries=2,
        output_validator=validate_references,
        agent_run_id=turn.round_id,
        conversation_round_id=turn.round_id,
        purpose=LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE,
        model_field=model_usages.EXECUTOR,
        reasoning_effort_override=turn.reasoning_effort_override,
    )
    return inference.output.label, inference.output.objective, inference.cost


__all__ = ["compose_task_objective", "generate_task_fields", "source_request_html"]
