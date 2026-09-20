"""Anthropic-compatible protocol translation over the OpenAI proxy seam.

The gateway serves Claude Code (and other Anthropic clients) by translating
the Messages protocol into the OpenAI Chat Completions contract that
`proxy_chat_completion` already resolves, forwards, traces and prices. Every
request passes through the exact same authentication, model resolution and
costing path as `/api/llm/openai`.

Design invariants, driven by the Claude Code client contract:

- tool call IDs generated here are `toolu_`-prefixed and stable within a
  response; the client echoes them in `tool_result`, and the request
  translation passes them through verbatim, so upstream assistant/tool
  messages always match inside a single (stateless) upstream request;
- `usage.input_tokens` and `count_tokens` both derive from the same estimator
  over the same translated body, so the numbers can never diverge;
- the stream is never ended without `message_stop` or an `error` event —
  the two legal endings; a silence of `_PING_SECONDS` emits a `ping` frame so
  idling upstreams do not trip reverse-proxy read timeouts.

Note: no keep-alive events can be emitted for upstreams that buffer their
entire completion (e.g. some reasoning transports); that remains a documented
limitation of passthrough streaming.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, AsyncIterator, cast
from uuid import uuid4

from fastapi.responses import JSONResponse, StreamingResponse

from core.i18n import tr

from .anthropic_schemas import (
    ContentBlock,
    MessageRequest,
    content_block_delta_event,
    content_block_start_event,
    content_block_stop_event,
    error_event,
    json_dumps,
    message_delta_event,
    message_response,
    message_start_event,
    message_stop_event,
    ping_event,
)
from .protocol_inference import proxy_chat_completion
from .provider_facade import ReasoningEffort


_PING_SECONDS = 15.0
_IMAGE_ESTIMATE_TOKENS = 300
_OPENAI_ERROR_STATUS_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
}
_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def _as_dict(value: Any) -> dict[str, Any]:
    """Re-type a decoded JSON object; empty dict for non-objects."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Re-type a decoded JSON array; empty list for non-arrays."""
    return cast(list[Any], value) if isinstance(value, list) else []


# ───────────────────────── token estimation (shared) ─────────────────────────


def _is_cjk(char: str) -> bool:
    cp = ord(char)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x3040 <= cp <= 0x30FF
        or 0xAC00 <= cp <= 0xD7AF
    )


def estimate_text_tokens(text: str) -> int:
    """Lightweight cl100k-style estimate: ~4 ASCII chars per token, 1 per CJK char."""
    if not text:
        return 0
    weighted = sum(1.0 if _is_cjk(char) else 0.25 for char in text)
    return max(1, math.ceil(weighted))


def _content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return estimate_text_tokens(content)
    if not isinstance(content, list):
        return 0
    total = 0
    for item in _as_list(content):
        if not isinstance(item, dict):
            total += estimate_text_tokens(str(item))
            continue
        entry = _as_dict(item)
        kind = entry.get("type")
        if kind == "text":
            total += estimate_text_tokens(str(entry.get("text") or ""))
        elif kind == "image_url":
            total += _IMAGE_ESTIMATE_TOKENS
        elif kind == "tool_calls":
            continue
        else:
            total += estimate_text_tokens(json_dumps(entry))
    return total


def estimate_openai_body_tokens(body: dict[str, Any]) -> int:
    """Estimate the prompt size of a translated (OpenAI-shaped) body.

    Shared by `/v1/messages` (`message_start.usage.input_tokens`) and
    `/v1/messages/count_tokens`, so both stay coherent by construction.
    """
    total = 3
    for message in _as_list(body.get("messages")):
        if not isinstance(message, dict):
            continue
        entry = _as_dict(message)
        total += 4 + _content_tokens(entry.get("content"))
        for call in _as_list(entry.get("tool_calls")):
            if not isinstance(call, dict):
                continue
            function = _as_dict(call).get("function")
            fn = _as_dict(function)
            total += 5 + estimate_text_tokens(
                str(fn.get("name") or "")
                + str(fn.get("arguments") or "")
            )
    for tool in _as_list(body.get("tools")):
        if not isinstance(tool, dict):
            continue
        fn = _as_dict(_as_dict(tool).get("function"))
        total += estimate_text_tokens(
            str(fn.get("name") or "")
            + str(fn.get("description") or "")
            + json_dumps(fn.get("parameters") or {})
        )
    return max(1, total)


def anthropic_input_tokens(request: MessageRequest) -> int:
    """Billable input token count used for both /v1/messages and count_tokens."""
    return estimate_openai_body_tokens(translate_to_openai(request))


# ─────────────────────────── request translation ───────────────────────────


def _block_text(blocks: list[dict[str, Any]]) -> str:
    """Concatenate the text of text/image blocks, ignoring thinking/signatures."""
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _block_images(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect base64 image blocks as OpenAI `image_url` entries."""
    images: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("type") != "image":
            continue
        source = _as_dict(block.get("source"))
        media_type = str(source.get("media_type") or "image/png")
        data = str(source.get("data") or "")
        if data:
            images.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            )
    return images


def _blocks_to_content(blocks: list[ContentBlock]) -> Any:
    """Reduce user-facing content blocks to str | None | OpenAI vision list."""
    raw = [block.model_dump() for block in blocks]
    text = _block_text(raw)
    images = _block_images(raw)
    if not images:
        return text or None
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    parts.extend(images)
    return parts


def _tool_result_content(block: ContentBlock) -> Any:
    """Serialize one tool_result as an OpenAI tool message content.

    An error result is marked in-band (`[tool_error]`) since the OpenAI
    contract has no error flag; upstream models read the marker naturally.
    """
    content_value: Any = block.content
    if isinstance(content_value, str):
        text = content_value
        images: list[dict[str, Any]] = []
    elif isinstance(content_value, list):
        entries = cast(list[Any], content_value)
        raw = [
            _as_dict(item)
            if isinstance(item, dict)
            else {"type": "text", "text": str(item)}
            for item in entries
        ]
        text = _block_text(raw)
        images = _block_images(raw)
    else:
        text = ""
        images = []
    if block.is_error and text:
        text = f"[tool_error] {text}"
    if not images:
        return text or None
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    parts.extend(images)
    return parts


def _translate_tool_choice(tool_choice: Any) -> Any:
    """Map Anthropic tool_choice onto the OpenAI contract."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return {
            "auto": "auto",
            "none": "none",
            "required": "required",
            "any": "required",
        }.get(tool_choice, "auto")
    if isinstance(tool_choice, dict):
        choice = _as_dict(tool_choice)
        choice_type = choice.get("type")
        if choice_type == "tool" and choice.get("name"):
            return {
                "type": "function",
                "function": {"name": str(choice["name"])},
            }
        if choice_type in ("auto", "none", "any"):
            return _translate_tool_choice(choice_type)
    return "auto"


def translate_to_openai(request: MessageRequest) -> dict[str, Any]:
    """Translate an Anthropic Messages request into a Chat Completions body.

    The `model` field is passed through untouched: `proxy_chat_completion`
    resolves Galaris LLM codes (and legacy `llm-<id>` identifiers).
    """
    messages: list[dict[str, Any]] = []

    system_value: Any = request.system
    if isinstance(system_value, str) and system_value:
        messages.append({"role": "system", "content": system_value})
    elif isinstance(system_value, list):
        system_blocks = cast(list[Any], system_value)
        system_text = _block_text(
            [
                _as_dict(item)
                if isinstance(item, dict)
                else {"type": "text", "text": str(item)}
                for item in system_blocks
            ]
        )
        if system_text:
            messages.append({"role": "system", "content": system_text})

    for message in request.messages:
        blocks = _as_blocks(message.content)
        if message.role == "assistant":
            tool_calls: list[dict[str, Any]] = []
            for block in blocks:
                if block.type != "tool_use":
                    continue
                tool_calls.append({
                    "id": block.id or f"toolu_{uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json_dumps(block.input),
                    },
                })
            entry: dict[str, Any] = {"role": "assistant"}
            text = _blocks_to_content(blocks)
            if tool_calls:
                entry["content"] = text
                entry["tool_calls"] = tool_calls
            else:
                entry["content"] = text
            messages.append(entry)
            continue

        tool_results = [block for block in blocks if block.type == "tool_result"]
        regular = [block for block in blocks if block.type != "tool_result"]
        if regular or not tool_results:
            messages.append({"role": "user", "content": _blocks_to_content(regular)})
        for block in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": block.tool_use_id,
                "content": _tool_result_content(block),
            })

    tools: list[dict[str, Any]] | None = None
    if request.tools:
        tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema or {},
            },
        } for tool in request.tools]

    body: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": request.max_tokens,
    }
    if request.stream:
        body["stream"] = True
        # Ask the upstream for final usage; ignored by providers that do not
        # support it, in which case the estimator fallback applies.
        body["stream_options"] = {"include_usage": True}
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if request.stop_sequences:
        body["stop"] = (
            request.stop_sequences[0]
            if len(request.stop_sequences) == 1
            else request.stop_sequences
        )
    if tools:
        body["tools"] = tools
        body["tool_choice"] = _translate_tool_choice(request.tool_choice)
    return body


def _as_blocks(content: Any) -> list[ContentBlock]:
    """Normalize message content (string or block list) into block models."""
    if isinstance(content, str):
        return [ContentBlock(type="text", text=content)]
    if content is None:
        return []
    if not isinstance(content, list):
        return [ContentBlock(type="text", text=str(content))]
    blocks: list[ContentBlock] = []
    for item in _as_list(content):
        if isinstance(item, ContentBlock):
            blocks.append(item)
        elif isinstance(item, dict):
            blocks.append(ContentBlock.model_validate(_as_dict(item)))
        else:
            blocks.append(ContentBlock(type="text", text=str(item)))
    return blocks


# ─────────────────────────── response translation ───────────────────────────

StopReason = str


def _stop_reason(finish_reason: Any, *, has_tools: bool) -> str:
    mapped = _STOP_REASONS.get(str(finish_reason) if finish_reason else "")
    if mapped is not None:
        return mapped
    return "tool_use" if has_tools else "end_turn"


def _parse_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            return _as_dict(json.loads(arguments))
        except json.JSONDecodeError:
            return {}
    if isinstance(arguments, dict):
        return _as_dict(arguments)
    return {}


def translate_completion(
    payload: dict[str, Any],
    *,
    model: str,
    input_tokens: int,
) -> dict[str, Any]:
    """Translate a non-streamed Chat Completions payload into an Anthropic message."""
    choices = _as_list(payload.get("choices"))
    choice = _as_dict(choices[0]) if choices else {}
    message = _as_dict(choice.get("message"))
    content: list[dict[str, Any]] = []
    if message.get("content"):
        content.append({"type": "text", "text": str(message["content"])})

    emitted_text = str(message.get("content") or "")
    for call in _as_list(message.get("tool_calls")):
        if not isinstance(call, dict):
            continue
        call_entry = _as_dict(call)
        function = _as_dict(call_entry.get("function"))
        call_id = str(call_entry.get("id") or f"toolu_{uuid4().hex[:24]}")
        if not call_id.startswith("toolu_"):
            call_id = f"toolu_{uuid4().hex[:24]}"
        arguments = _parse_arguments(function.get("arguments"))
        content.append({
            "type": "tool_use",
            "id": call_id,
            "name": str(function.get("name") or "unknown"),
            "input": arguments,
        })
        emitted_text += json_dumps(arguments)

    usage = _as_dict(payload.get("usage"))
    output_tokens = 0
    if usage:
        output_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )
    if not output_tokens:
        output_tokens = max(1, estimate_text_tokens(emitted_text))

    finish_reason = choice.get("finish_reason")
    return message_response(
        f"msg_{uuid4().hex[:24]}",
        model,
        content,
        _stop_reason(finish_reason, has_tools=bool(content and content[-1]["type"] == "tool_use")),
        input_tokens,
        output_tokens,
    )


class AnthropicStreamTranslator:
    """Turns normalized OpenAI streaming chunks into Anthropic SSE events.

    Block indexes follow the Anthropic ordering rule: the text block (if any)
    is closed before the first tool block opens, and blocks only ever append.
    Upstream tools keep their OpenAI provider index until a wildcard slot is
    implied, so interleavings and unnamed leads stay unambiguous.
    """

    def __init__(self, model: str, input_tokens: int) -> None:
        self.message_id = f"msg_{uuid4().hex[:24]}"
        self.model = model
        self.input_tokens = input_tokens
        self.stop_reason: str | None = None
        self.output_tokens: int | None = None
        self._next_index = 0
        self._text_open = False
        self._text_index = 0
        self._text_emitted = ""
        self._tools: list[dict[str, Any]] = []  # {openai_index, index, id, name, args, open}
        self._unnamed: dict[int | str, list[str]] = {}  # tool slot -> buffered args
        self._finished = False

    def start(self) -> str:
        return message_start_event(self.message_id, self.model, self.input_tokens)

    def feed(self, chunk: dict[str, Any]) -> list[str]:
        if self._finished:
            return []
        events: list[str] = []
        delta: dict[str, Any] = {}
        finish_reason: Any = None
        choices = _as_list(chunk.get("choices"))
        if choices:
            first = _as_dict(choices[0])
            delta = _as_dict(first.get("delta"))
            finish_reason = first.get("finish_reason")

        content = delta.get("content")
        if content:
            self._open_text(events)
            self._text_emitted += str(content)
            events.append(content_block_delta_event(
                self._text_index,
                {"type": "text_delta", "text": str(content)},
            ))

        for call in _as_list(delta.get("tool_calls")):
            if not isinstance(call, dict):
                continue
            call_entry = _as_dict(call)
            function = _as_dict(call_entry.get("function"))
            name = str(function.get("name") or "")
            fragment = str(function.get("arguments") or "")
            raw_index = call_entry.get("index")
            if isinstance(raw_index, int):
                slot: int | str = raw_index
            elif isinstance(raw_index, str) and raw_index.isdigit():
                slot = raw_index
            else:
                slot = self._free_tool_slot()
            tool = self._tool_by_openai_index(slot)
            if tool is None and name:
                tool = self._new_tool(slot, name)
            if tool is None:
                self._unnamed.setdefault(slot, []).append(fragment)
                continue
            if not tool["open"]:
                if name:
                    tool["name"] = name
                self._start_tool(tool, events)
            tool["args"] += fragment
            events.append(content_block_delta_event(
                tool["index"],
                {"type": "input_json_delta", "partial_json": fragment},
            ))

        if finish_reason is not None:
            self.stop_reason = _stop_reason(
                finish_reason,
                has_tools=bool(self._tools or self._unnamed),
            )

        usage = _as_dict(chunk.get("usage"))
        if usage:
            completion = usage.get("completion_tokens")
            if completion is not None:
                self.output_tokens = int(completion)
        return events

    def _open_text(self, events: list[str]) -> None:
        if self._text_open:
            return
        self._text_index = self._next_index
        self._next_index += 1
        self._text_open = True
        events.append(content_block_start_event(
            self._text_index,
            {"type": "text", "text": ""},
        ))

    def _close_text(self, events: list[str]) -> None:
        if not self._text_open:
            return
        events.append(content_block_stop_event(self._text_index))
        self._text_open = False

    def _free_tool_slot(self) -> int:
        """Smallest upstream tool index not yet bound to a known tool."""
        used = {str(tool["openai_index"]) for tool in self._tools}
        candidate = 0
        while str(candidate) in used:
            candidate += 1
        return candidate

    def _tool_by_openai_index(self, index: int | str) -> dict[str, Any] | None:
        for tool in self._tools:
            if str(tool["openai_index"]) == str(index):
                return tool
        return None

    def _new_tool(self, openai_index: int | str, name: str) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "openai_index": openai_index,
            "index": self._next_index,
            "id": f"toolu_{uuid4().hex[:24]}",
            "name": name,
            "args": "",
            "open": False,
        }
        self._next_index += 1
        self._tools.append(tool)
        return tool

    def _start_tool(self, tool: dict[str, Any], events: list[str]) -> None:
        """Open a tool block, flushing any unnamed fragments buffered for it."""
        self._close_text(events)
        tool["open"] = True
        events.append(content_block_start_event(tool["index"], {
            "type": "tool_use",
            "id": tool["id"],
            "name": tool["name"] or "unknown",
            "input": {},
        }))
        for fragment in self._unnamed.pop(tool["openai_index"], []):
            tool["args"] += fragment
            events.append(content_block_delta_event(
                tool["index"],
                {"type": "input_json_delta", "partial_json": fragment},
            ))

    def finish(self) -> list[str]:
        """Emit the closing events; call exactly once, after the stream ends."""
        if self._finished:
            return []
        self._finished = True
        events: list[str] = []
        self._close_text(events)
        for tool in self._tools:
            if not tool["open"]:
                # The stream ended between tool fragments: normalize the block.
                self._start_tool(tool, events)
            events.append(content_block_stop_event(tool["index"]))
        output_tokens = self.output_tokens
        if output_tokens is None:
            emitted = self._text_emitted + "".join(tool["args"] for tool in self._tools)
            output_tokens = max(1, estimate_text_tokens(emitted))
        events.append(message_delta_event(
            self.message_id,
            self.stop_reason or ("tool_use" if self._tools else "end_turn"),
            max(output_tokens, 0),
        ))
        events.append(message_stop_event(self.message_id))
        return events


def _parse_openai_sse_chunks(text: str) -> list[dict[str, Any]]:
    """Extract Chat Completions payloads from relayed SSE lines."""
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            payloads.append(_as_dict(decoded))
    return payloads


async def translate_proxy_stream(
    stream_response: StreamingResponse,
    translator: AnthropicStreamTranslator,
) -> AsyncIterator[str]:
    """Relay a proxy stream as Anthropic SSE, adding keep-alive pings.

    The upstream consumer runs as a separate task so a silence timeout never
    cancels the proxy's `relay()` mid-read (which would poison its trace
    finalization); the queue simply stays empty and we ping instead.
    """
    upstream = stream_response.body_iterator
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def consume() -> None:
        async for item in upstream:
            await queue.put(_chunk_bytes(item))
        await queue.put(None)

    consumer = asyncio.create_task(consume())
    try:
        yield translator.start()
        while True:
            if consumer.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_PING_SECONDS)
            except asyncio.TimeoutError:
                yield ping_event()
                continue
            if item is None:
                break
            chunks = _parse_openai_sse_chunks(item.decode("utf-8", errors="replace"))
            for chunk in chunks:
                for event in translator.feed(chunk):
                    yield event
        if consumer.done():
            consumer.result()  # propagate upstream errors after the queue drained
        else:
            await consumer
        for event in translator.finish():
            yield event
    except asyncio.CancelledError:
        # Client disconnected: let the proxy's relay finalize its trace, then
        # propagate the cancellation as required by ASGI.
        if not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
        raise
    except Exception:
        # Upstream failed mid-generation: emit the only legal non-success
        # ending and end the stream gracefully (no message_stop after error).
        yield error_event(await tr("anthropic_api.errors.stream_interrupted"))
        return
    finally:
        if not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)


def _chunk_bytes(chunk: Any) -> bytes:
    """Coerce a relayed stream item to bytes (relays yield bytes in practice)."""
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, str):
        return chunk.encode("utf-8")
    return bytes(chunk)


def error_status_type(status_code: int) -> str:
    return _OPENAI_ERROR_STATUS_TYPES.get(status_code, "api_error")


async def call_proxy(
    body: dict[str, Any],
    *,
    task_id: Any = None,
    agent_run_id: Any = None,
    conversation_round_id: Any = None,
    process_run_id: Any = None,
    agent_id: int | None = None,
    reasoning_effort: ReasoningEffort | None = None,
    force_reasoning_effort: bool = False,
) -> JSONResponse | StreamingResponse:
    """Delegate the translated body to the shared proxy seam."""
    return await proxy_chat_completion(
        body,
        task_id=task_id,
        agent_run_id=agent_run_id,
        conversation_round_id=conversation_round_id,
        process_run_id=process_run_id,
        agent_id=agent_id,
        unwrap_deferred_tools=agent_id is not None,
        managed_runtime_request=agent_id is not None,
        reasoning_effort=reasoning_effort,
        force_reasoning_effort=force_reasoning_effort,
    )
