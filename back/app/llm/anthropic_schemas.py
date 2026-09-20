"""Pydantic shapes and SSE serialization for the Anthropic-compatible API.

The request models are deliberately tolerant: Claude Code (and other Anthropic
clients) sends fields we ignore (`anthropic_beta`, `thinking`, `resume`,
`cache_control` blocks, …) and we must never reject a request for them. Unknown
fields are dropped; content types accept both string and block forms.

The serialization helpers emit the exact Anthropic SSE grammar the CLI
enforces: `event:`/`data:` pairs, `message_start` → block events →
`message_delta` → `message_stop`, and an `error` event as the only legal
alternative ending.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict


def json_dumps(data: Any) -> str:
    """Serialize an event payload compactly but without escaping non-ASCII."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Frame one Anthropic SSE event."""
    return f"event: {event}\ndata: {json_dumps(data)}\n\n"


class SourceBlock(BaseModel):
    """Base64 image source carried by an image content block."""

    model_config = ConfigDict(extra="ignore")

    type: str = "base64"
    media_type: str = ""
    data: str = ""


class ContentBlock(BaseModel):
    """One content block (`text`, `tool_use`, `tool_result`, `image`, …).

    Unknown block types are preserved raw-ish: every optional field defaults so
    a block we do not understand simply carries no translatable payload.
    """

    model_config = ConfigDict(extra="ignore")

    type: str = ""
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = {}
    tool_use_id: str = ""
    content: Any = None
    is_error: bool = False
    source: SourceBlock | None = None
    # Tolerant catch-all for fields we do not model (server_tool_use, …).
    extra_fields: dict[str, Any] = {}


class Message(BaseModel):
    """One message: `content` is a string or a list of `ContentBlock`."""

    model_config = ConfigDict(extra="ignore")

    role: str
    content: Any = None


class ToolDef(BaseModel):
    """Anthropic tool declaration (`input_schema` is JSON Schema)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}


class MessageRequest(BaseModel):
    """Anthropic `POST /v1/messages` body, validated loosely.

    `max_tokens` is required by Anthropic but defaulted here so tolerant
    clients (or hand-written callers) never crash the gateway.
    """

    model_config = ConfigDict(extra="ignore")

    model: str = ""
    messages: list[Message] = []
    max_tokens: int = 4096
    system: Any = None
    tools: list[ToolDef] = []
    tool_choice: Any = None
    stream: bool = False
    stop_sequences: list[str] = []
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None


class CountTokensRequest(BaseModel):
    """Anthropic `POST /v1/messages/count_tokens` body."""

    model_config = ConfigDict(extra="ignore")

    model: str = ""
    messages: list[Message] = []
    system: Any = None
    tools: list[ToolDef] = []
    tool_choice: Any = None


# ────────────────────────── SSE event builders ──────────────────────────


def message_start_event(
    message_id: str,
    model: str,
    input_tokens: int,
) -> str:
    """`message_start` announces the message identity and billable input."""
    return sse_event("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 1,
            },
        },
    })


def content_block_start_event(index: int, block: dict[str, Any]) -> str:
    """`content_block_start` opens a text or tool_use block."""
    return sse_event("content_block_start", {
        "type": "content_block_start",
        "index": index,
        "content_block": block,
    })


def content_block_delta_event(index: int, delta: dict[str, Any]) -> str:
    """`content_block_delta`: `text_delta` or `input_json_delta`."""
    return sse_event("content_block_delta", {
        "type": "content_block_delta",
        "index": index,
        "delta": delta,
    })


def content_block_stop_event(index: int) -> str:
    return sse_event("content_block_stop", {
        "type": "content_block_stop",
        "index": index,
    })


def message_delta_event(
    message_id: str,
    stop_reason: str | None,
    output_tokens: int,
) -> str:
    return sse_event("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None,
        },
        "usage": {"output_tokens": output_tokens},
    })


def message_stop_event(message_id: str) -> str:
    return sse_event("message_stop", {"type": "message_stop"})


def ping_event() -> str:
    """Keep-alive frame; Claude Code ignores it, nginx timeouts do not fire."""
    return sse_event("ping", {"type": "ping"})


def error_event(message: str, error_type: str = "api_error") -> str:
    """In-stream `error` event (the only legal non-success ending)."""
    return sse_event("error", {
        "type": "error",
        "error": {"type": error_type, "message": message},
    })


# ──────────────────────── non-streamed responses ────────────────────────


def message_response(
    message_id: str,
    model: str,
    content: list[dict[str, Any]],
    stop_reason: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    """Anthropic-shaped non-streamed message result."""
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": output_tokens,
        },
    }


def error_envelope(message: str, error_type: str) -> dict[str, Any]:
    """Anthropic error body returned with a non-2xx status."""
    return {
        "type": "error",
        "error": {"type": error_type, "message": message},
    }
