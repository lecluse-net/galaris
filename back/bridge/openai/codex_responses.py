"""Translate between Galaris' Chat Completions contract and Codex Responses."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from core.util import as_dict, as_list


DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for raw in as_list(content):
        if isinstance(raw, str):
            parts.append(raw)
            continue
        if not isinstance(raw, dict):
            continue
        item = as_dict(raw)
        value = item.get("text") or item.get("content")
        if isinstance(value, str):
            parts.append(value)
    return "".join(parts)


def _responses_content_parts(content: Any, *, role: str) -> list[dict[str, Any]]:
    """Convert Chat multimodal parts to their Responses equivalents."""
    if not isinstance(content, list):
        return []
    text_type = "output_text" if role == "assistant" else "input_text"
    converted: list[dict[str, Any]] = []
    for raw in as_list(content):
        if isinstance(raw, str):
            if raw:
                converted.append({"type": text_type, "text": raw})
            continue
        if not isinstance(raw, dict):
            continue
        part = as_dict(raw)
        part_type = str(part.get("type") or "").lower()
        if part_type in {"text", "input_text", "output_text"}:
            text = part.get("text")
            if isinstance(text, str) and text:
                converted.append({"type": text_type, "text": text})
            continue
        if role == "user" and part_type in {"image_url", "input_image"}:
            image = part.get("image_url")
            detail = part.get("detail")
            if isinstance(image, dict):
                image_dict = as_dict(image)
                url = image_dict.get("url")
                detail = image_dict.get("detail") or detail
            else:
                url = image
            if isinstance(url, str) and url:
                mapped: dict[str, Any] = {"type": "input_image", "image_url": url}
                if isinstance(detail, str) and detail:
                    mapped["detail"] = detail
                converted.append(mapped)
            continue
        if role == "user" and part_type in {"file", "input_file"}:
            mapped_file: dict[str, Any] = {"type": "input_file"}
            for key in ("file_id", "file_url", "filename", "file_data"):
                if value := part.get(key):
                    mapped_file[key] = value
            if len(mapped_file) > 1:
                converted.append(mapped_file)
    return converted


def _tool_call_id(tool_call: dict[str, Any], index: int) -> str:
    raw = tool_call.get("call_id") or tool_call.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().split("|", 1)[0]
    function = as_dict(tool_call.get("function"))
    seed = f"{function.get('name')}:{function.get('arguments')}:{index}"
    return f"call_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _responses_input(messages: Any) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for raw in as_list(messages):
        if not isinstance(raw, dict):
            continue
        message = as_dict(raw)
        role = str(message.get("role") or "")
        content = message.get("content")
        if role in {"system", "developer"}:
            if text := _content_text(content).strip():
                instructions.append(text)
            continue
        if role in {"user", "assistant"}:
            content_parts = _responses_content_parts(content, role=role)
            content_value: Any = content_parts if content_parts else _content_text(content)
            if content_parts or content_value:
                items.append({"role": role, "content": content_value})
            if role == "assistant":
                for index, raw_call in enumerate(as_list(message.get("tool_calls"))):
                    if not isinstance(raw_call, dict):
                        continue
                    call = as_dict(raw_call)
                    function = as_dict(call.get("function"))
                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    arguments = function.get("arguments")
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    if not isinstance(arguments, str):
                        arguments = "{}"
                    items.append({
                        "type": "function_call",
                        "call_id": _tool_call_id(call, index),
                        "name": name,
                        "arguments": arguments or "{}",
                    })
            continue
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id.strip():
                continue
            output: Any
            if isinstance(content, list):
                output = _responses_content_parts(content, role="user")
            else:
                output = "" if content is None else str(content)
            items.append({
                "type": "function_call_output",
                "call_id": call_id.strip().split("|", 1)[0],
                "output": output,
            })
    return "\n\n".join(instructions).strip(), items


def _responses_tools(raw_tools: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for raw in as_list(raw_tools):
        if not isinstance(raw, dict):
            continue
        item = as_dict(raw)
        function = as_dict(item.get("function")) if item.get("type") == "function" else item
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        raw_parameters = function.get("parameters")
        parameters: dict[str, Any]
        if isinstance(raw_parameters, dict):
            parameters = as_dict(raw_parameters)
        else:
            parameters = {"type": "object", "properties": dict[str, Any]()}
        tools.append({
            "type": "function",
            "name": name.strip(),
            "description": str(function.get("description") or ""),
            "parameters": parameters,
            "strict": bool(function.get("strict", False)),
        })
    return tools


def _responses_tool_choice(choice: Any) -> Any:
    if isinstance(choice, str):
        return choice
    if isinstance(choice, dict):
        choice_dict = as_dict(choice)
        function = as_dict(choice_dict.get("function"))
        name = function.get("name") or choice_dict.get("name")
        if isinstance(name, str) and name:
            return {"type": "function", "name": name}
    return None


def _responses_text_format(response_format: Any) -> Optional[dict[str, Any]]:
    if not isinstance(response_format, dict):
        return None
    format_dict = as_dict(response_format)
    format_type = format_dict.get("type")
    if format_type == "json_object":
        return {"format": {"type": "json_object"}}
    if format_type != "json_schema":
        return None
    schema = as_dict(format_dict.get("json_schema"))
    if not schema:
        return None
    mapped: dict[str, Any] = {
        "type": "json_schema",
        "name": str(schema.get("name") or "response"),
        "schema": as_dict(schema.get("schema")),
        "strict": bool(schema.get("strict", True)),
    }
    if description := schema.get("description"):
        mapped["description"] = str(description)
    return {"format": mapped}


def chat_completions_to_responses(body: dict[str, Any]) -> dict[str, Any]:
    """Build a Codex Responses request from an OpenAI Chat request."""
    instructions, input_items = _responses_input(body.get("messages"))
    tools = _responses_tools(body.get("tools"))
    request: dict[str, Any] = {
        "model": str(body.get("model") or ""),
        "instructions": instructions or DEFAULT_INSTRUCTIONS,
        "input": input_items,
        "store": False,
        "stream": bool(body.get("stream", False)),
    }
    if tools:
        request["tools"] = tools
        request["tool_choice"] = _responses_tool_choice(body.get("tool_choice")) or "auto"
        request["parallel_tool_calls"] = bool(body.get("parallel_tool_calls", True))

    effort = body.get("reasoning_effort")
    if isinstance(effort, str) and effort:
        request["reasoning"] = {
            "effort": "low" if effort == "minimal" else effort,
            "summary": "auto",
        }
    else:
        request["reasoning"] = {"effort": "medium", "summary": "auto"}

    if text_format := _responses_text_format(body.get("response_format")):
        request["text"] = text_format
    if service_tier := body.get("service_tier"):
        request["service_tier"] = service_tier

    # Keep cache routing stable across recurring runs with the same system instructions and tools.
    static_prefix = json.dumps(
        {"instructions": request["instructions"], "tools": tools},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    request["prompt_cache_key"] = f"galaris_{hashlib.sha256(static_prefix.encode()).hexdigest()[:24]}"
    return request


def _item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for raw in as_list(item.get("content")):
        if not isinstance(raw, dict):
            continue
        part = as_dict(raw)
        if part.get("type") in {"output_text", "text"} and part.get("text") is not None:
            parts.append(str(part["text"]))
    return "".join(parts)


def _reasoning_parts(item: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("summary", "content"):
        for raw in as_list(item.get(key)):
            if isinstance(raw, dict):
                value = as_dict(raw).get("text")
                if value is not None:
                    parts.append(str(value))
            elif isinstance(raw, str):
                parts.append(raw)
    return [part for part in parts if part]


def _reasoning_text(item: dict[str, Any]) -> str:
    """Keep distinct reasoning summaries readable instead of gluing them together."""
    return "\n\n".join(_reasoning_parts(item))


def _chat_usage(raw_usage: Any) -> dict[str, Any]:
    usage = as_dict(raw_usage)
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    input_details = as_dict(usage.get("input_tokens_details") or usage.get("prompt_tokens_details"))
    output_details = as_dict(usage.get("output_tokens_details") or usage.get("completion_tokens_details"))
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        "prompt_tokens_details": {
            "cached_tokens": int(input_details.get("cached_tokens") or 0),
        },
        "completion_tokens_details": {
            "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        },
    }


def _codex_error(payload: dict[str, Any]) -> dict[str, Any]:
    error = as_dict(payload.get("error"))
    message = error.get("message") or payload.get("status") or "Codex request failed"
    return {
        "error": {
            "message": str(message),
            "type": str(error.get("type") or "codex_error"),
            "code": error.get("code"),
        }
    }


def responses_to_chat_completion(
    payload: dict[str, Any],
    *,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Normalize a complete Codex response to Chat Completions."""
    if payload.get("error") or str(payload.get("status") or "").lower() == "failed":
        return _codex_error(payload)

    visible: list[str] = []
    reasoning: list[str] = []
    tool_calls: list[dict[str, Any]] = []
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
        elif item_type in {"function_call", "custom_tool_call"}:
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            arguments = item.get("arguments") or item.get("input") or "{}"
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            tool_calls.append({
                "id": str(item.get("call_id") or item.get("id") or f"call_{len(tool_calls)}"),
                "type": "function",
                "function": {"name": name, "arguments": str(arguments)},
            })

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(visible) if visible else None,
    }
    if reasoning:
        message["reasoning_content"] = "\n\n".join(reasoning)
    if tool_calls:
        message["tool_calls"] = tool_calls

    status = str(payload.get("status") or "completed").lower()
    finish_reason = "tool_calls" if tool_calls else ("length" if status == "incomplete" else "stop")
    created_at = payload.get("created_at")
    created = int(created_at) if isinstance(created_at, (int, float)) else int(time.time())
    result: dict[str, Any] = {
        "id": str(payload.get("id") or "codex-response"),
        "object": "chat.completion",
        "created": created,
        "model": str(model or payload.get("model") or "codex"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _chat_usage(payload.get("usage")),
    }
    if payload.get("service_tier") is not None:
        result["service_tier"] = payload["service_tier"]
    return result


class CodexStreamError(RuntimeError):
    """A failure emitted after the Responses SSE stream has started."""


@dataclass
class _ToolState:
    index: int
    call_id: str
    item_id: str
    name: str = ""
    arguments: str = ""
    announced: bool = False


class CodexSSEAdapter:
    """Stateful Responses SSE to Chat Completions SSE converter."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.response_id = "codex-response"
        self.created = int(time.time())
        self.terminal = False
        self._role_emitted = False
        self._phases: dict[int, str] = {}
        self._message_text: dict[tuple[int, str], str] = {}
        self._reasoning_emitted: dict[tuple[int, int], str] = {}
        self._reasoning_segments: set[tuple[str, int, int]] = set()
        self._reasoning_started = False
        self._tools_by_item: dict[str, _ToolState] = {}
        self._tools_by_output: dict[int, _ToolState] = {}

    def _chunk(
        self,
        delta: Optional[dict[str, Any]] = None,
        *,
        finish_reason: Optional[str] = None,
        usage: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.response_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta or {},
                "finish_reason": finish_reason,
            }],
        }
        if usage is not None:
            result["usage"] = usage
        return result

    def _with_role(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if chunks and not self._role_emitted:
            self._role_emitted = True
            return [self._chunk({"role": "assistant"}), *chunks]
        return chunks

    @staticmethod
    def _remaining(full: str, emitted: str) -> str:
        if not emitted:
            return full
        if full.startswith(emitted):
            return full[len(emitted):]
        if emitted.endswith(full):
            return ""
        # Some Codex streams revise a cutoff summary in the terminal event. Preserve the
        # corrected step as a separate paragraph instead of silently dropping it.
        return f"\n\n{full}"

    def _reasoning_delta(
        self,
        segment: tuple[str, int, int],
        text: str,
    ) -> str:
        """Prefix every distinct reasoning item/summary with a visible boundary."""
        if not text:
            return ""
        if segment in self._reasoning_segments:
            return text
        self._reasoning_segments.add(segment)
        prefix = "\n\n" if self._reasoning_started else ""
        self._reasoning_started = True
        return f"{prefix}{text}"

    def _tool_for(self, event: dict[str, Any], item: Optional[dict[str, Any]] = None) -> _ToolState:
        item = item or {}
        output_index_raw = event.get("output_index")
        output_index = int(output_index_raw) if isinstance(output_index_raw, int) else 0
        item_id = str(event.get("item_id") or item.get("id") or f"item-{output_index}")
        existing = self._tools_by_item.get(item_id) or self._tools_by_output.get(output_index)
        if existing is not None:
            return existing
        call_id = str(item.get("call_id") or item.get("id") or f"call_{len(self._tools_by_item)}")
        state = _ToolState(
            index=len(self._tools_by_item),
            call_id=call_id,
            item_id=item_id,
            name=str(item.get("name") or ""),
        )
        self._tools_by_item[item_id] = state
        self._tools_by_output[output_index] = state
        return state

    def _announce_tool(self, state: _ToolState) -> list[dict[str, Any]]:
        if state.announced:
            return []
        state.announced = True
        return [self._chunk({
            "tool_calls": [{
                "index": state.index,
                "id": state.call_id,
                "type": "function",
                "function": {"name": state.name, "arguments": ""},
            }]
        })]

    def _emit_done_item(self, item: dict[str, Any], output_index: int) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        item_type = str(item.get("type") or "")
        if item_type == "message":
            phase = str(item.get("phase") or self._phases.get(output_index) or "").lower()
            self._phases[output_index] = phase
            channel = "reasoning_content" if phase in {"analysis", "commentary"} else "content"
            full = _item_text(item)
            key = (output_index, channel)
            emitted = self._message_text.get(key, "")
            if remainder := self._remaining(full, emitted):
                self._message_text[key] = emitted + remainder
                if channel == "reasoning_content":
                    remainder = self._reasoning_delta(
                        ("message", output_index, 0), remainder
                    )
                chunks.append(self._chunk({channel: remainder}))
        elif item_type == "reasoning":
            for summary_index, full in enumerate(_reasoning_parts(item)):
                key = (output_index, summary_index)
                emitted = self._reasoning_emitted.get(key, "")
                if remainder := self._remaining(full, emitted):
                    self._reasoning_emitted[key] = emitted + remainder
                    chunks.append(self._chunk({
                        "reasoning_content": self._reasoning_delta(
                            ("reasoning", output_index, summary_index), remainder
                        )
                    }))
        elif item_type in {"function_call", "custom_tool_call"}:
            state = self._tool_for({"output_index": output_index}, item)
            if not state.name:
                state.name = str(item.get("name") or "")
            chunks.extend(self._announce_tool(state))
            full = item.get("arguments") or item.get("input") or ""
            if isinstance(full, dict):
                full = json.dumps(full, ensure_ascii=False)
            full = str(full)
            if remainder := self._remaining(full, state.arguments):
                state.arguments += remainder
                chunks.append(self._chunk({
                    "tool_calls": [{
                        "index": state.index,
                        "function": {"arguments": remainder},
                    }]
                }))
        return chunks

    def convert(self, raw_event: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert one Responses event into zero or more Chat chunks."""
        event = as_dict(raw_event)
        event_type = str(event.get("type") or "")
        response = as_dict(event.get("response"))
        if response:
            if response.get("id"):
                self.response_id = str(response["id"])
            if response.get("model"):
                self.model = str(response["model"])
            if isinstance(response.get("created_at"), (int, float)):
                self.created = int(response["created_at"])

        if event_type in {"response.created", "response.in_progress"}:
            if not self._role_emitted:
                self._role_emitted = True
                return [self._chunk({"role": "assistant"})]
            return []
        if event_type in {"error", "response.failed"}:
            error = as_dict(event.get("error") or response.get("error"))
            message = error.get("message") or error.get("code") or "Codex stream failed"
            raise CodexStreamError(str(message))

        output_index_raw = event.get("output_index")
        output_index = int(output_index_raw) if isinstance(output_index_raw, int) else 0

        if event_type == "response.output_item.added":
            item = as_dict(event.get("item"))
            item_type = str(item.get("type") or "")
            if item_type == "message":
                self._phases[output_index] = str(item.get("phase") or "").lower()
                return []
            if item_type in {"function_call", "custom_tool_call"}:
                return self._with_role(self._announce_tool(self._tool_for(event, item)))
            return []

        if "output_text.delta" in event_type:
            delta = event.get("delta")
            if not isinstance(delta, str) or not delta:
                return []
            phase = self._phases.get(output_index, "")
            channel = "reasoning_content" if phase in {"analysis", "commentary"} else "content"
            key = (output_index, channel)
            self._message_text[key] = self._message_text.get(key, "") + delta
            if channel == "reasoning_content":
                delta = self._reasoning_delta(("message", output_index, 0), delta)
            return self._with_role([self._chunk({channel: delta})])

        if "reasoning" in event_type and "delta" in event_type:
            delta = event.get("delta")
            if not isinstance(delta, str) or not delta:
                return []
            summary_index_raw = event.get("summary_index")
            summary_index = summary_index_raw if isinstance(summary_index_raw, int) else 0
            key = (output_index, summary_index)
            self._reasoning_emitted[key] = self._reasoning_emitted.get(key, "") + delta
            delta = self._reasoning_delta(
                ("reasoning", output_index, summary_index), delta
            )
            return self._with_role([self._chunk({"reasoning_content": delta})])

        if "reasoning" in event_type and event_type.endswith(".done"):
            full = event.get("text")
            if not isinstance(full, str) or not full:
                return []
            summary_index_raw = event.get("summary_index")
            summary_index = summary_index_raw if isinstance(summary_index_raw, int) else 0
            key = (output_index, summary_index)
            emitted = self._reasoning_emitted.get(key, "")
            remainder = self._remaining(full, emitted)
            if not remainder:
                return []
            self._reasoning_emitted[key] = emitted + remainder
            remainder = self._reasoning_delta(
                ("reasoning", output_index, summary_index), remainder
            )
            return self._with_role([
                self._chunk({"reasoning_content": remainder})
            ])

        if "function_call_arguments.delta" in event_type:
            delta = event.get("delta")
            if not isinstance(delta, str) or not delta:
                return []
            state = self._tool_for(event)
            state.arguments += delta
            chunks = self._announce_tool(state)
            chunks.append(self._chunk({
                "tool_calls": [{
                    "index": state.index,
                    "function": {"arguments": delta},
                }]
            }))
            return self._with_role(chunks)

        if "function_call_arguments.done" in event_type:
            state = self._tool_for(event)
            full = str(event.get("arguments") or "")
            chunks = self._announce_tool(state)
            if remainder := self._remaining(full, state.arguments):
                state.arguments += remainder
                chunks.append(self._chunk({
                    "tool_calls": [{
                        "index": state.index,
                        "function": {"arguments": remainder},
                    }]
                }))
            return self._with_role(chunks)

        if event_type == "response.output_item.done":
            return self._with_role(self._emit_done_item(as_dict(event.get("item")), output_index))

        if event_type in {"response.completed", "response.incomplete"}:
            chunks: list[dict[str, Any]] = []
            for index, raw in enumerate(as_list(response.get("output"))):
                if isinstance(raw, dict):
                    chunks.extend(self._emit_done_item(as_dict(raw), index))
            finish_reason = (
                "tool_calls"
                if self._tools_by_item
                else ("length" if event_type == "response.incomplete" else "stop")
            )
            chunks.append(self._chunk(
                {},
                finish_reason=finish_reason,
                usage=_chat_usage(response.get("usage")),
            ))
            self.terminal = True
            return self._with_role(chunks)
        return []
