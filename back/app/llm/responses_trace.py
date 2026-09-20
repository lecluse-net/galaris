"""Trace normalization for the native OpenAI Responses protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.util import as_dict, as_list

from .trace import content_to_text, parse_arguments


def request_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a Responses request onto the canonical persisted message trace."""

    messages: list[dict[str, Any]] = []
    instructions = content_to_text(body.get("instructions"))
    if instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = body.get("input")
    if isinstance(raw_input, str):
        return [*messages, {"role": "user", "content": raw_input}]

    for raw in as_list(raw_input):
        if isinstance(raw, str):
            messages.append({"role": "user", "content": raw})
            continue
        if not isinstance(raw, dict):
            continue
        item = as_dict(raw)
        item_type = str(item.get("type") or "")
        role = str(item.get("role") or "")
        if item_type == "message" or role in {"user", "assistant", "developer", "system"}:
            messages.append({
                "role": role or "user",
                "content": item.get("content"),
            })
            continue
        if item_type in {"function_call", "custom_tool_call", "mcp_call"}:
            name = str(item.get("name") or item.get("tool_name") or "unknown")
            arguments = item.get("arguments", item.get("input", {}))
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": str(item.get("call_id") or item.get("id") or "call"),
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }],
            })
            continue
        if item_type in {"function_call_output", "custom_tool_call_output", "mcp_call_output"}:
            messages.append({
                "role": "tool",
                "tool_call_id": str(item.get("call_id") or item.get("id") or "call"),
                "content": item.get("output"),
            })
    return messages


def _item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for raw in as_list(item.get("content")):
        if isinstance(raw, str):
            parts.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        part = as_dict(raw)
        if str(part.get("type") or "") in {"output_text", "text"}:
            text = part.get("text")
            if text is not None:
                parts.append(str(text))
    return "".join(parts)


def _reasoning_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("summary", "content"):
        for raw in as_list(item.get(key)):
            if isinstance(raw, str):
                parts.append(raw)
            elif isinstance(raw, dict):
                text = as_dict(raw).get("text")
                if text is not None:
                    parts.append(str(text))
    return "\n\n".join(part for part in parts if part)


def response_trace(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one complete Responses result for ``LLMCall`` persistence."""

    visible: list[str] = []
    reasoning: list[str] = []
    tools: list[dict[str, Any]] = []
    for raw in as_list(payload.get("output")):
        if not isinstance(raw, dict):
            continue
        item = as_dict(raw)
        item_type = str(item.get("type") or "")
        if item_type == "message":
            text = _item_text(item)
            phase = str(item.get("phase") or "").lower()
            (reasoning if phase in {"analysis", "commentary"} else visible).append(text)
        elif item_type == "reasoning":
            if text := _reasoning_text(item):
                reasoning.append(text)
        elif item_type in {"function_call", "custom_tool_call", "mcp_call"}:
            tools.append({
                "id": str(item.get("call_id") or item.get("id") or f"call-{len(tools)}"),
                "type": "function",
                "name": str(item.get("name") or item.get("tool_name") or "unknown"),
                "arguments": parse_arguments(item.get("arguments", item.get("input"))),
                "status": "requested",
            })

    status = str(payload.get("status") or "completed").lower()
    finish_reason = (
        "tool_calls"
        if tools
        else "length" if status == "incomplete" else "stop" if status == "completed" else status
    )
    return {
        "response_text": "".join(visible),
        "reasoning": "\n\n".join(part for part in reasoning if part),
        "tool_calls": tools,
        "finish_reason": finish_reason,
        "usage": as_dict(payload.get("usage")),
        "upstream_request_id": str(payload.get("id")) if payload.get("id") else None,
    }


@dataclass
class ResponsesStreamTrace:
    """Incrementally observe Responses SSE while retaining its terminal response."""

    response_parts: list[str] = field(default_factory=lambda: [])
    reasoning_parts: list[str] = field(default_factory=lambda: [])
    tool_arguments: dict[int, str] = field(default_factory=lambda: {})
    tool_items: dict[int, dict[str, Any]] = field(default_factory=lambda: {})
    phases: dict[int, str] = field(default_factory=lambda: {})
    completed_output_items: dict[int, dict[str, Any]] = field(default_factory=lambda: {})
    terminal_response: dict[str, Any] | None = None
    error: str | None = None

    @property
    def terminal(self) -> bool:
        return self.terminal_response is not None or self.error is not None

    def add_event(self, event: dict[str, Any]) -> bool:
        """Record an event and return whether visible trace content changed."""

        event_type = str(event.get("type") or "")
        before = (
            len(self.response_parts),
            len(self.reasoning_parts),
            sum(len(value) for value in self.tool_arguments.values()),
        )
        output_index = event.get("output_index")
        index = output_index if isinstance(output_index, int) else 0
        if event_type == "response.output_item.added":
            item = as_dict(event.get("item"))
            self.phases[index] = str(item.get("phase") or "").lower()
            if str(item.get("type") or "") in {"function_call", "custom_tool_call", "mcp_call"}:
                self.tool_items[index] = item
        elif event_type == "response.output_item.done":
            # Keep native items intact: tool call IDs, rich content and reasoning
            # identity cannot be recovered from the flattened diagnostic trace.
            self.completed_output_items[index] = dict(as_dict(event.get("item")))
        elif event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if self.phases.get(index) in {"analysis", "commentary"}:
                self.reasoning_parts.append(delta)
            else:
                self.response_parts.append(delta)
        elif event_type == "response.reasoning_summary_text.delta":
            self.reasoning_parts.append(str(event.get("delta") or ""))
        elif event_type == "response.function_call_arguments.delta":
            self.tool_arguments[index] = (
                self.tool_arguments.get(index, "") + str(event.get("delta") or "")
            )
        elif event_type in {"response.completed", "response.incomplete"}:
            self.terminal_response = dict(as_dict(event.get("response")))
            # Codex may omit output from its terminal envelope after emitting each
            # completed item separately. Never promote unfinished deltas to output.
            if not self.terminal_response.get("output") and self.completed_output_items:
                self.terminal_response["output"] = [
                    item for _, item in sorted(self.completed_output_items.items())
                ]
        elif event_type in {"response.failed", "error"}:
            response = as_dict(event.get("response"))
            error = as_dict(event.get("error") or response.get("error"))
            self.error = str(error.get("message") or response.get("status") or "Responses request failed")
            self.terminal_response = response or None
        after = (
            len(self.response_parts),
            len(self.reasoning_parts),
            sum(len(value) for value in self.tool_arguments.values()),
        )
        return after != before

    def result(self) -> dict[str, Any]:
        terminal = response_trace(self.terminal_response or {})
        if not terminal["response_text"]:
            terminal["response_text"] = "".join(self.response_parts)
        if not terminal["reasoning"]:
            terminal["reasoning"] = "".join(self.reasoning_parts)
        if not terminal["tool_calls"] and self.tool_items:
            terminal["tool_calls"] = [
                {
                    "id": str(item.get("call_id") or item.get("id") or f"call-{index}"),
                    "type": "function",
                    "name": str(item.get("name") or item.get("tool_name") or "unknown"),
                    "arguments": parse_arguments(
                        self.tool_arguments.get(index) or item.get("arguments")
                    ),
                    "status": "requested",
                }
                for index, item in sorted(self.tool_items.items())
            ]
            terminal["finish_reason"] = "tool_calls"
        return terminal


__all__ = [
    "ResponsesStreamTrace",
    "request_messages",
    "response_trace",
]
