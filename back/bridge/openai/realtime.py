"""OpenAI Realtime WebSocket adapter."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from websockets.asyncio.client import ClientConnection, connect

from app.llm.provider_facade import (
    ProviderConnection,
    RealtimeConversationEvent,
    RealtimeConversationSession,
    RealtimeToolDefinition,
)
from core.util import as_dict, as_list


def _websocket_url(base_url: str, model: str) -> str:
    parsed = urlsplit(base_url.rstrip("/"))
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise RuntimeError("the Realtime provider has no valid WebSocket endpoint")
    path = f"{parsed.path.rstrip('/')}/realtime"
    return urlunsplit(
        (scheme, parsed.netloc, path, f"model={quote(model, safe='')}", "")
    )


def _decode_payload(raw: str | bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("the Realtime provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("the Realtime provider returned an invalid event")
    return as_dict(payload)


def _response_identifier(payload: dict[str, Any]) -> str:
    response = as_dict(payload.get("response"))
    return str(payload.get("response_id") or response.get("id") or "")


def _raise_provider_error(payload: dict[str, Any], fallback: str) -> None:
    if payload.get("type") != "error":
        raise RuntimeError(fallback)
    error = as_dict(payload.get("error"))
    code = str(error.get("code") or error.get("type") or "").strip()
    message = str(error.get("message") or "").strip()
    detail = ": ".join(value for value in (code, message) if value)
    raise RuntimeError(
        f"OpenAI Realtime error: {detail}" if detail else fallback
    )


def _function_calls(payload: dict[str, Any]) -> list[RealtimeConversationEvent]:
    response = as_dict(payload.get("response"))
    calls: list[RealtimeConversationEvent] = []
    for raw in as_list(response.get("output")):
        item = as_dict(raw)
        if item.get("type") != "function_call":
            continue
        calls.append(
            RealtimeConversationEvent(
                kind="function_call",
                response_id=str(response.get("id") or ""),
                item_id=str(item.get("id") or ""),
                call_id=str(item.get("call_id") or ""),
                tool_name=str(item.get("name") or ""),
                arguments=str(item.get("arguments") or "{}"),
            )
        )
    return calls


class OpenAIRealtimeSession:
    sample_rate = 24_000
    channels = 1

    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection
        self._pending: asyncio.Queue[RealtimeConversationEvent] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def open(
        cls,
        connection: ProviderConnection,
        *,
        model: str,
        voice: str | None,
        instructions: str,
        tools: tuple[RealtimeToolDefinition, ...],
        output_audio: bool,
    ) -> RealtimeConversationSession:
        api_key = (connection.api_key or "").strip()
        if not api_key:
            raise ValueError(f"provider {connection.name} requires an API key")
        socket: ClientConnection | None = None
        try:
            socket = await connect(
                _websocket_url(connection.base_url, model),
                additional_headers={"Authorization": f"Bearer {api_key}"},
                open_timeout=10,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=20,
                max_queue=128,
            )
            session = cls(socket)
            created = _decode_payload(await asyncio.wait_for(socket.recv(), timeout=10))
            if created.get("type") != "session.created":
                _raise_provider_error(
                    created,
                    "the Realtime provider did not create a session",
                )
            audio: dict[str, Any] = {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24_000},
                    "turn_detection": {
                        "type": "semantic_vad",
                        "create_response": True,
                        "interrupt_response": True,
                    },
                }
            }
            if output_audio:
                audio["output"] = {
                    "format": {"type": "audio/pcm", "rate": 24_000},
                    "voice": (voice or "").removeprefix("voice:"),
                }
            await socket.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "type": "realtime",
                            "model": model,
                            "output_modalities": [
                                "audio" if output_audio else "text"
                            ],
                            "audio": audio,
                            "instructions": instructions,
                            "tools": [
                                {
                                    "type": "function",
                                    "name": tool.name,
                                    "description": tool.description,
                                    "parameters": tool.parameters,
                                }
                                for tool in tools
                            ],
                            "tool_choice": "auto",
                        },
                    }
                )
            )
            updated = _decode_payload(
                await asyncio.wait_for(socket.recv(), timeout=10)
            )
            if updated.get("type") != "session.updated":
                _raise_provider_error(
                    updated,
                    "the Realtime provider did not apply session settings",
                )
            return session
        except asyncio.CancelledError:
            if socket is not None:
                await asyncio.shield(socket.close())
            raise
        except Exception:
            if socket is not None:
                await socket.close()
            raise

    async def send_audio(self, pcm: bytes) -> None:
        if pcm:
            await self._send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm).decode("ascii"),
                }
            )

    async def receive(self) -> RealtimeConversationEvent:
        if not self._pending.empty():
            return self._pending.get_nowait()
        while True:
            payload = _decode_payload(await self._connection.recv())
            event_type = str(payload.get("type") or "")
            if event_type == "session.updated":
                return RealtimeConversationEvent(kind="session_ready")
            if event_type == "input_audio_buffer.speech_started":
                return RealtimeConversationEvent(kind="speech_started")
            if event_type == "input_audio_buffer.committed":
                return RealtimeConversationEvent(
                    kind="input_committed",
                    item_id=str(payload.get("item_id") or ""),
                )
            if event_type == "response.created":
                return RealtimeConversationEvent(
                    kind="response_started",
                    response_id=_response_identifier(payload),
                )
            if event_type == "response.output_item.added":
                item = as_dict(payload.get("item"))
                return RealtimeConversationEvent(
                    kind="output_item",
                    response_id=_response_identifier(payload),
                    item_id=str(item.get("id") or ""),
                )
            if event_type == "response.output_audio.delta":
                encoded = str(payload.get("delta") or "")
                try:
                    audio = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise RuntimeError(
                        "the Realtime provider returned invalid audio"
                    ) from exc
                return RealtimeConversationEvent(
                    kind="audio_delta",
                    audio=audio,
                    response_id=_response_identifier(payload),
                    item_id=str(payload.get("item_id") or ""),
                )
            if event_type == "response.output_text.delta":
                return RealtimeConversationEvent(
                    kind="text_delta",
                    text=str(payload.get("delta") or ""),
                    response_id=_response_identifier(payload),
                    item_id=str(payload.get("item_id") or ""),
                )
            if event_type == "response.output_audio_transcript.delta":
                return RealtimeConversationEvent(
                    kind="audio_transcript_delta",
                    text=str(payload.get("delta") or ""),
                    response_id=_response_identifier(payload),
                    item_id=str(payload.get("item_id") or ""),
                )
            if event_type == "response.done":
                calls = _function_calls(payload)
                response_id = _response_identifier(payload)
                status = str(as_dict(payload.get("response")).get("status") or "")
                terminal_kind = (
                    "response_cancelled"
                    if status in {"cancelled", "incomplete"}
                    else "response_done"
                )
                terminal = RealtimeConversationEvent(
                    kind=terminal_kind,
                    response_id=response_id,
                )
                if calls:
                    for call in calls[1:]:
                        self._pending.put_nowait(call)
                    self._pending.put_nowait(terminal)
                    return calls[0]
                return terminal
            if event_type == "response.cancelled":
                return RealtimeConversationEvent(
                    kind="response_cancelled",
                    response_id=_response_identifier(payload),
                )
            if event_type == "error":
                error = as_dict(payload.get("error"))
                return RealtimeConversationEvent(
                    kind="error",
                    error=str(error.get("message") or "Realtime provider error"),
                )

    async def send_function_output(self, call_id: str, output: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )

    async def request_response(self, instructions: str | None = None) -> None:
        response = (
            {"instructions": instructions.strip()}
            if instructions and instructions.strip()
            else None
        )
        payload: dict[str, Any] = {"type": "response.create"}
        if response is not None:
            payload["response"] = response
        await self._send(payload)

    async def cancel_response(self) -> None:
        await self._send({"type": "response.cancel"})

    async def truncate(self, item_id: str, audio_end_ms: int) -> None:
        if item_id:
            await self._send(
                {
                    "type": "conversation.item.truncate",
                    "item_id": item_id,
                    "content_index": 0,
                    "audio_end_ms": max(0, audio_end_ms),
                }
            )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._connection.close()

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("the Realtime provider session is closed")
        await self._connection.send(json.dumps(payload))


class OpenAIRealtime:
    async def create_realtime_session(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        voice: str | None,
        instructions: str,
        tools: tuple[RealtimeToolDefinition, ...],
        output_audio: bool,
    ) -> RealtimeConversationSession:
        return await OpenAIRealtimeSession.open(
            connection,
            model=model,
            voice=voice,
            instructions=instructions,
            tools=tools,
            output_audio=output_audio,
        )


__all__ = ["OpenAIRealtime", "OpenAIRealtimeSession"]
