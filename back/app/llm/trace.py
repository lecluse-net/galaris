"""Detailed trace extraction from LLM responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from core.util import as_dict as _as_dict, as_list as _as_list


# Task correlation lives inside the prompt's JSON message context and is forwarded unchanged to
# the provider. Legacy text-line and HTML-marker formats remain supported for active sessions.
TASK_URI_JSON_RE = re.compile(
    r'"task_uri"\s*:\s*"galaris://task/([0-9a-fA-F-]{36})"'
)
TASK_ID_JSON_RE = re.compile(r'"task_id"\s*:\s*"([0-9a-fA-F-]{36})"')
AGENT_RUN_ID_JSON_RE = re.compile(r'"run_id"\s*:\s*"([0-9a-fA-F-]{36})"')
LLM_ID_JSON_RE = re.compile(r'"llm_id"\s*:\s*"?(\d+)"?')
TASK_ID_LINE_RE = re.compile(r"Task id\s*:\s*`?([0-9a-fA-F-]{36})`?")
TASK_MARKER_RE = re.compile(r"<!--\s*galaris-task-id:([0-9a-fA-F-]{36})\s*-->")
PROCESS_CONTEXT_PREFIX = "galaris_process_context:"
MCP_GALARIS_TOOL_PREFIX = "mcp__galaris__"


def extract_process_context(body: dict[str, Any]) -> None:
    """Remove the technical n8n message and expose its identifiers in the body."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    filtered: list[Any] = []
    for raw_message in _as_list(messages):
        if not isinstance(raw_message, dict):
            filtered.append(raw_message)
            continue
        message = _as_dict(raw_message)
        role = message.get("role")
        content = message.get("content")
        if (
            role != "system"
            or not isinstance(content, str)
            or not content.startswith(PROCESS_CONTEXT_PREFIX)
        ):
            filtered.append(raw_message)
            continue
        try:
            raw_context: Any = json.loads(
                content.removeprefix(PROCESS_CONTEXT_PREFIX)
            )
        except json.JSONDecodeError:
            filtered.append(raw_message)
            continue
        if not isinstance(raw_context, dict):
            filtered.append(raw_message)
            continue
        context = _as_dict(raw_context)
        mappings = {
            "process_run_id": "galaris_process_run_id",
            "correlation_id": "galaris_correlation_id",
            "workflow_id": "galaris_workflow_id",
            "run_id": "galaris_engine_run_id",
        }
        for source, target in mappings.items():
            if value := context.get(source):
                body.setdefault(target, str(value))
    body["messages"] = filtered


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in _as_list(content):
            if isinstance(item, dict):
                d = _as_dict(item)
                value = d.get("text") or d.get("content")
                if value:
                    parts.append(str(value))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    return "" if content is None else str(content)


def _contains_image_content(value: Any) -> bool:
    """Return whether an OpenAI-style request value contains an image input."""
    if isinstance(value, dict):
        item = _as_dict(value)
        if str(item.get("type") or "") in {"image", "image_url", "input_image"}:
            return True
        return any(_contains_image_content(child) for child in item.values())
    if isinstance(value, list):
        return any(_contains_image_content(child) for child in _as_list(value))
    return False


def infer_call_type(messages: Any, system_prompt: str = "") -> str:
    """Classify an LLM call for supervision without relying on provider model names."""
    if _contains_image_content(messages):
        return "vision"

    normalized = system_prompt.casefold()
    markers = (
        ("you maintain the durable markdown tracking", "goal_tracking"),
        ("you maintain the durable html tracking", "goal_tracking"),
        ("you are the main dispatcher", "dispatch"),
        ("you are the planner", "planning"),
        ("you prepare a concise execution briefing", "briefing"),
        ("you synthesize the overall result", "synthesis"),
    )
    for marker, call_type in markers:
        if marker in normalized:
            return call_type
    return "chat"


def infer_call_purpose(messages: Any, system_prompt: str = "") -> str | None:
    """Recover a semantic purpose for traces created before it was persisted explicitly."""

    normalized_system = system_prompt.casefold()
    message_text = "\n".join(
        content_to_text(_as_dict(message).get("content"))
        for message in _as_list(messages)
        if isinstance(message, dict)
    ).casefold()
    combined = f"{normalized_system}\n{message_text}"

    system_markers = (
        ("same_topic_probability", "dream.topic_continuity"),
        ("high-precision durable-memory detector", "dream.memory_extraction"),
        ("produce cautious, reusable lessons", "dream.task_outcome_reflection"),
        ("you are the main dispatcher", "agent.dispatch"),
        ("you are the planner", "agent.planning"),
        ("you prepare a concise execution briefing", "agent.briefing"),
        ("you synthesize the overall result", "agent.synthesis"),
        ("you maintain the durable markdown tracking", "goal.tracking"),
    )
    for marker, purpose in system_markers:
        if marker in normalized_system:
            return purpose

    if "reuse stage:" in combined and "topic_id" in combined:
        return "dream.topic_reuse"
    if "creation stage:" in combined and "topic" in combined:
        return "dream.topic_creation"
    return None


def reasoning_to_text(message: dict[str, Any]) -> str:
    """Return the richest reasoning representation exposed by a provider.

    OpenAI-compatible providers commonly expose the same reasoning through a short
    ``reasoning_content`` alias and a more complete ``reasoning_details`` list.  Using an
    ``or`` chain silently discarded the detailed steps as soon as the short alias existed.
    """
    candidates = [
        content_to_text(message.get(key))
        for key in (
            "reasoning_details",
            "reasoning_content",
            "reasoning",
            "thinking",
        )
    ]
    # Keep whitespace inside streaming fragments: a trailing space may be the boundary
    # between two consecutive deltas.
    populated = [candidate for candidate in candidates if candidate.strip()]
    return max(populated, key=len, default="")


def task_id_from_messages(messages: Any) -> UUID | None:
    """Extract the current task from the latest prompt message context.

    Search backwards because every user turn carries its own task ID. Legacy text-line and HTML
    marker formats are fallback options.
    """
    if not isinstance(messages, list):
        return None
    for message in reversed(_as_list(messages)):
        if not isinstance(message, dict):
            continue
        text = content_to_text(_as_dict(message).get("content"))
        match = (
            TASK_URI_JSON_RE.search(text)
            or TASK_ID_JSON_RE.search(text)
            or TASK_ID_LINE_RE.search(text)
            or TASK_MARKER_RE.search(text)
        )
        if match:
            return UUID(match.group(1))
    return None


def agent_run_id_from_messages(messages: Any) -> UUID | None:
    """Extract the immutable agent run correlation from the latest message context."""

    if not isinstance(messages, list):
        return None
    for message in reversed(_as_list(messages)):
        if not isinstance(message, dict):
            continue
        match = AGENT_RUN_ID_JSON_RE.search(
            content_to_text(_as_dict(message).get("content"))
        )
        if match:
            return UUID(match.group(1))
    return None


def llm_id_from_messages(messages: Any) -> int | None:
    """Extract the model frozen by the latest driver request."""
    if not isinstance(messages, list):
        return None
    for message in reversed(_as_list(messages)):
        if not isinstance(message, dict):
            continue
        match = LLM_ID_JSON_RE.search(content_to_text(_as_dict(message).get("content")))
        if match:
            return int(match.group(1))
    return None


def extract_prompts(messages: list[dict[str, Any]]) -> tuple[str, str]:
    systems = [content_to_text(m.get("content")) for m in messages if m.get("role") == "system"]
    users = [content_to_text(m.get("content")) for m in messages if m.get("role") == "user"]
    return (users[-1] if users else "", "\n\n".join(text for text in systems if text))


def parse_arguments(value: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"_raw": value}


def normalize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_calls, list):
        return []
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_as_list(raw_calls)):
        if not isinstance(raw, dict):
            continue
        raw_dict = _as_dict(raw)
        function = _as_dict(raw_dict.get("function"))
        result.append({
            "id": str(raw_dict.get("id") or f"tool-{index}"),
            "type": str(raw_dict.get("type") or "function"),
            "name": str(function.get("name") or raw_dict.get("name") or "unknown"),
            "arguments": parse_arguments(function.get("arguments", raw_dict.get("arguments"))),
            "status": "requested",
        })
    return result


def normalize_deferred_tool_calls(
    raw_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose Hermes ``tool_call`` bridge entries as their underlying tools."""

    normalized: list[dict[str, Any]] = []
    for raw_tool in raw_calls:
        tool = dict(raw_tool)
        if str(tool.get("name") or "") != "tool_call":
            normalized.append(tool)
            continue

        bridge_arguments = parse_arguments(tool.get("arguments"))
        if not isinstance(bridge_arguments, dict):
            normalized.append(tool)
            continue
        arguments = _as_dict(bridge_arguments)
        underlying_name = str(arguments.get("name") or "").strip()
        if not underlying_name:
            normalized.append(tool)
            continue

        while underlying_name.startswith(MCP_GALARIS_TOOL_PREFIX):
            underlying_name = underlying_name.removeprefix(MCP_GALARIS_TOOL_PREFIX)
        underlying_arguments = parse_arguments(arguments.get("arguments"))
        tool["name"] = underlying_name
        tool["arguments"] = (
            _as_dict(underlying_arguments)
            if isinstance(underlying_arguments, dict)
            else {"value": underlying_arguments}
        )
        normalized.append(tool)
    return normalized


def extract_usage(usage: Any) -> dict[str, Any]:
    return _as_dict(usage)


def usage_counters(usage: dict[str, Any]) -> dict[str, int]:
    prompt_details = _as_dict(usage.get("prompt_tokens_details") or usage.get("input_tokens_details"))
    completion_details = _as_dict(usage.get("completion_tokens_details") or usage.get("output_tokens_details"))
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        "cache_read_tokens": int(prompt_details.get("cached_tokens") or usage.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(prompt_details.get("cache_write_tokens") or usage.get("cache_write_tokens") or 0),
        "reasoning_tokens": int(completion_details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0),
    }


def response_trace(
    payload: dict[str, Any],
    *,
    unwrap_deferred_tools: bool = False,
) -> dict[str, Any]:
    choices = _as_list(payload.get("choices"))
    choice = _as_dict(choices[0]) if choices else {}
    message = _as_dict(choice.get("message"))
    tool_calls = normalize_tool_calls(message.get("tool_calls"))
    if unwrap_deferred_tools:
        tool_calls = normalize_deferred_tool_calls(tool_calls)
    return {
        "response_text": content_to_text(message.get("content")),
        "reasoning": reasoning_to_text(message),
        "tool_calls": tool_calls,
        "finish_reason": choice.get("finish_reason"),
        "usage": extract_usage(payload.get("usage")),
        "upstream_request_id": str(payload.get("id")) if payload.get("id") else None,
    }


@dataclass
class StreamTrace:
    response_parts: list[str] = field(default_factory=lambda: [])
    reasoning_parts: list[str] = field(default_factory=lambda: [])
    tools: dict[int, dict[str, Any]] = field(default_factory=lambda: {})
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=lambda: {})
    response_id: str | None = None
    raw_payloads: list[dict[str, Any]] = field(default_factory=lambda: [])

    def add_payload(self, payload: dict[str, Any]) -> None:
        self.raw_payloads.append(payload)
        if payload.get("id"):
            self.response_id = str(payload["id"])
        if isinstance(payload.get("usage"), dict):
            self.usage = _as_dict(payload["usage"])
        choices = _as_list(payload.get("choices"))
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            choice_dict = _as_dict(choice)
            if choice_dict.get("finish_reason"):
                self.finish_reason = str(choice_dict["finish_reason"])
            delta = _as_dict(choice_dict.get("delta"))
            text = content_to_text(delta.get("content"))
            if text:
                self.response_parts.append(text)
            reasoning = reasoning_to_text(delta)
            if reasoning:
                self.reasoning_parts.append(reasoning)
            for raw in _as_list(delta.get("tool_calls")):
                if not isinstance(raw, dict):
                    continue
                raw_dict = _as_dict(raw)
                index = int(raw_dict.get("index") or 0)
                tool = self.tools.setdefault(index, {"id": "", "type": "function", "name": "", "arguments_raw": ""})
                if raw_dict.get("id"):
                    tool["id"] = str(raw_dict["id"])
                if raw_dict.get("type"):
                    tool["type"] = str(raw_dict["type"])
                function = _as_dict(raw_dict.get("function"))
                if function.get("name"):
                    tool["name"] += str(function["name"])
                if function.get("arguments"):
                    tool["arguments_raw"] += str(function["arguments"])

    def result(self, *, unwrap_deferred_tools: bool = False) -> dict[str, Any]:
        tools = [
            {
                "id": tool["id"] or f"tool-{index}",
                "type": tool["type"],
                "name": tool["name"] or "unknown",
                "arguments": parse_arguments(tool["arguments_raw"]),
                "status": "requested",
            }
            for index, tool in sorted(self.tools.items())
        ]
        if unwrap_deferred_tools:
            tools = normalize_deferred_tool_calls(tools)
        return {
            "response_text": "".join(self.response_parts),
            "reasoning": "".join(self.reasoning_parts),
            "tool_calls": tools,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "upstream_request_id": self.response_id,
        }
