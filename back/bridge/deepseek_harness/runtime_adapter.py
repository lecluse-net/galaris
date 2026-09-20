"""Small OpenAI-compatible facade around the DeepSeek Harness subprocess SDK.

This file is copied into the managed runtime image. It intentionally uses only the
standard library so the image needs no web framework in addition to the DSH SDK.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import logging
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from typing import Any, Callable, Protocol, cast
from uuid import uuid4


_MAX_REQUEST_BYTES = 2_000_000
_RUN_SLOT = threading.BoundedSemaphore(1)
_LOG = logging.getLogger("galaris.deepseek_harness")


class _RunResult(Protocol):
    final_response: str
    finish_reason: str | None


class _Harness(Protocol):
    def __enter__(self) -> "_Harness": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def run(
        self,
        input: str,
        *,
        session_id: str,
        on_notification: Callable[[object], None] | None = None,
    ) -> _RunResult: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class AdapterConfig:
    api_token: str
    model: str
    workspace: Path
    session_root: Path
    cordis: Path
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "AdapterConfig":
        token = os.environ.get("HARNESS_API_TOKEN", "").strip()
        model = os.environ.get("HARNESS_MODEL", "").strip()
        if not token:
            raise RuntimeError("HARNESS_API_TOKEN is required.")
        if not model:
            raise RuntimeError("HARNESS_MODEL is required.")
        return cls(
            api_token=token,
            model=model,
            workspace=Path(os.environ.get("DSH_CWD", "/workspace")).resolve(),
            session_root=Path(os.environ.get("DSH_SESSION_ROOT", "/sessions")).resolve(),
            cordis=Path(
                os.environ.get("DSH_CORDIS_CONFIG", "/opt/galaris/cordis.yml")
            ).resolve(),
            request_timeout_seconds=float(
                os.environ.get("DSH_REQUEST_TIMEOUT_SECONDS", "900")
            ),
        )


@dataclass(frozen=True)
class Completion:
    id: str
    model: str
    content: str
    finish_reason: str


@dataclass(frozen=True)
class StreamEmission:
    kind: str
    payload: dict[str, object]


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ""
    parts: list[str] = []
    for raw in cast(Sequence[object], value):
        block = _mapping(raw)
        if block.get("type") in {"text", "reasoning"}:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


class DeepSeekStreamAdapter:
    """Translate official SDK notifications into live Galaris/OpenAI events."""

    def __init__(self) -> None:
        self._reasoning: dict[int, str] = {}
        self._tool_calls: dict[str, tuple[str, dict[str, object]]] = {}
        self.streamed_text = ""
        self.usage: dict[str, object] = {
            "token_quality": "unknown",
            "cost_quality": "unknown",
        }

    @staticmethod
    def _thinking(content: str) -> StreamEmission:
        return StreamEmission(
            kind="semantic",
            payload={
                "type": "tool",
                "tool_name": "thinking",
                "content": content,
                "success": True,
            },
        )

    @staticmethod
    def _bounded(value: Mapping[str, object], limit: int = 8_000) -> dict[str, object]:
        payload = dict(value)
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) <= limit:
            return payload
        return {"summary": encoded[: limit - 40] + "…[truncated]"}

    @staticmethod
    def _arguments(value: object) -> dict[str, object]:
        if isinstance(value, Mapping):
            raw = cast(Mapping[object, object], value)
            payload = {
                key: item for key, item in raw.items() if isinstance(key, str)
            }
            return DeepSeekStreamAdapter._bounded(payload)
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            decoded = cast(object, json.loads(value))
        except json.JSONDecodeError:
            return {"raw": value[:8_000]}
        payload = dict(_mapping(decoded))
        return DeepSeekStreamAdapter._bounded(payload) if payload else {
            "raw": value[:8_000]
        }

    def _record_usage(self, value: object) -> None:
        usage = _mapping(value)
        if not usage:
            return

        def counter(*names: str) -> int:
            raw = next((usage.get(name) for name in names if name in usage), 0)
            return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0

        prior_requests = self.usage.get("requests")
        requests = (
            prior_requests
            if isinstance(prior_requests, int) and not isinstance(prior_requests, bool)
            else 1
        )

        self.usage = {
            "input_tokens": counter("inputTokens", "input_tokens", "prompt_tokens"),
            "output_tokens": counter(
                "outputTokens", "output_tokens", "completion_tokens"
            ),
            "cache_read_tokens": counter("cacheReadTokens", "cache_read_tokens"),
            "cache_write_tokens": counter("cacheWriteTokens", "cache_write_tokens"),
            "reasoning_tokens": counter("reasoningTokens", "reasoning_tokens"),
            "requests": max(1, requests),
            "tool_calls": len(self._tool_calls),
            "token_quality": "partial",
            "cost_quality": "unknown",
        }

    def consume(self, notification: object) -> list[StreamEmission]:
        if str(getattr(notification, "method", "")) != "session.event":
            return []
        payload = _mapping(getattr(notification, "payload", None))
        event = _mapping(payload.get("event"))
        event_type = event.get("type")
        data = _mapping(event.get("data"))

        if event_type == "assistant/chunk":
            chunk = _mapping(data.get("chunk"))
            chunk_type = chunk.get("type")
            index = chunk.get("index")
            if chunk_type == "text-delta":
                text = chunk.get("text")
                if isinstance(text, str) and text:
                    self.streamed_text += text
                    return [StreamEmission("text", {"content": text})]
            elif chunk_type == "reasoning-delta" and isinstance(index, int):
                text = chunk.get("text")
                if isinstance(text, str) and text:
                    self._reasoning[index] = self._reasoning.get(index, "") + text
            elif chunk_type == "block-end":
                block = _mapping(chunk.get("block"))
                if block.get("type") == "reasoning":
                    buffered = self._reasoning.pop(index, "") if isinstance(index, int) else ""
                    content = str(block.get("text") or buffered).strip()
                    if content:
                        return [self._thinking(content)]
            elif chunk_type == "usage":
                self._record_usage(chunk.get("usage") or chunk)
            return []

        if event_type == "assistant/message":
            self._record_usage(data.get("usage"))
            return []

        if event_type == "tool/call":
            call_id = str(data.get("callId") or "")
            name = str(data.get("name") or "tool")
            if call_id:
                self._tool_calls[call_id] = (
                    name,
                    self._arguments(data.get("arguments")),
                )
            return []

        if event_type != "tool/result":
            return []
        message = _mapping(data.get("message"))
        call_id = str(
            message.get("toolCallId")
            or message.get("tool_call_id")
            or data.get("callId")
            or ""
        )
        name, arguments = self._tool_calls.get(call_id, ("tool", {}))
        content = _content_text(message.get("content")) or "Tool completed"
        error = _mapping(data.get("error"))
        success = not bool(error) and message.get("isError") is not True
        return [
            StreamEmission(
                "semantic",
                {
                    "type": "tool",
                    "tool_name": name,
                    "tool_arguments": arguments,
                    "tool_result": self._bounded(message),
                    "content": content[:4_000],
                    "success": success,
                },
            )
        ]

    def finish(self) -> list[StreamEmission]:
        emissions = [
            self._thinking(content.strip())
            for _, content in sorted(self._reasoning.items())
            if content.strip()
        ]
        self._reasoning.clear()
        return emissions


def _messages(body: Mapping[str, object]) -> list[dict[str, str]]:
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(
        raw_messages, (str, bytes)
    ):
        raise ValueError("messages must be an array.")
    raw_sequence = cast(Sequence[object], raw_messages)
    if len(raw_sequence) > 200:
        raise ValueError("messages must contain at most 200 entries.")
    messages: list[dict[str, str]] = []
    for raw in raw_sequence:
        if not isinstance(raw, Mapping):
            raise ValueError("every message must be an object.")
        item = cast(Mapping[str, object], raw)
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(
            content, str
        ):
            raise ValueError("messages accept only text system, user, and assistant roles.")
        messages.append({"role": role, "content": content})
    if not messages:
        raise ValueError("messages must not be empty.")
    return messages


def render_prompt(
    messages: Sequence[Mapping[str, str]],
    runtime_context: Mapping[str, str] | None = None,
) -> str:
    """Render the ordered Chat Completions history as unambiguous task context."""

    payload = json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))
    context = ""
    if runtime_context:
        context_payload = json.dumps(
            dict(runtime_context), ensure_ascii=False, separators=(",", ":")
        )
        context = (
            "\n\nThe following values are trusted Galaris runtime controls. Do not "
            "change the identifiers, and obey the approval and execution limits:\n"
            f"<galaris_runtime_context>{context_payload}</galaris_runtime_context>"
        )
    return (
        "Execute the Galaris task described by the ordered message transcript below. "
        "System-role entries are governing instructions. Earlier user and assistant entries "
        "are context; the final user entry is the current objective. Use Galaris MCP tools "
        "for durable memory, files, messages, and external effects. A claim in your final "
        "answer is not proof of an effect.\n\n"
        f"<galaris_messages_json>{payload}</galaris_messages_json>{context}"
    )


def _harness_factory() -> Any:
    module = importlib.import_module("deepseek_harness")
    factory = getattr(module, "DeepSeekHarness", None)
    if factory is None:
        raise RuntimeError("The DeepSeek Harness SDK is not installed.")
    return factory


def run_completion(
    body: Mapping[str, object],
    config: AdapterConfig,
    *,
    active: "ActiveRun | None" = None,
    on_notification: Callable[[object], None] | None = None,
) -> Completion:
    model = str(body.get("model") or "").strip()
    if not model:
        raise ValueError("model must be a non-empty string.")
    messages = _messages(body)
    runtime_context = {
        key: value
        for key, value in {
            "task_id": body.get("galaris_task_id"),
            "run_id": body.get("galaris_run_id"),
            "approval_action": body.get("galaris_approval_action"),
            "request_limit": body.get("galaris_request_limit"),
            "tool_call_limit": body.get("galaris_tool_call_limit"),
        }.items()
        if isinstance(value, str) and value
    }
    completion_id = f"chatcmpl-dsh-{uuid4().hex}"
    run_root = config.session_root / completion_id
    run_root.mkdir(parents=True, exist_ok=False)
    config.workspace.mkdir(parents=True, exist_ok=True)
    factory = _harness_factory()
    requested_effort = str(
        body.get("galaris_reasoning_effort") or ""
    ).strip().lower()
    reasoning_effort = {
        "none": "low",
        "minimal": "low",
        "low": "low",
        "medium": "high",
        "high": "high",
        "xhigh": "max",
        "max": "max",
    }.get(requested_effort)
    harness = cast(
        _Harness,
        factory(
            provider="deepseek-official",
            model=model,
            cwd=str(config.workspace),
            runtime_cwd=str(config.workspace),
            dsh_home=str(run_root),
            profile="sdk",
            patches=(str(config.cordis),),
            request_timeout_seconds=config.request_timeout_seconds,
            shutdown_timeout_seconds=2.0,
            env={"DSH_SESSION_ROOT": str(run_root / "sessions"), **(
                {"DSH_REASONING_EFFORT": reasoning_effort} if reasoning_effort is not None else {}
            )},
        ),
    )
    if active is not None:
        active.bind(harness)
    try:
        with harness:
            rendered_prompt = render_prompt(messages, runtime_context)
            result = (
                harness.run(
                    rendered_prompt,
                    session_id=completion_id,
                    on_notification=on_notification,
                )
                if on_notification is not None
                else harness.run(rendered_prompt, session_id=completion_id)
            )
    finally:
        if active is not None:
            active.unbind(harness)
    content = result.final_response.strip()
    if not content:
        raise RuntimeError("DeepSeek Harness completed without a final assistant response.")
    reason = result.finish_reason or "stop"
    if reason == "completed":
        reason = "stop"
    return Completion(
        id=completion_id,
        model=model,
        content=content,
        finish_reason=reason[:100],
    )


class ActiveRun:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._harness: _Harness | None = None
        self._cancelled = False

    def bind(self, harness: _Harness) -> None:
        with self._lock:
            if self._cancelled:
                harness.close()
                return
            self._harness = harness

    def unbind(self, harness: _Harness) -> None:
        with self._lock:
            if self._harness is harness:
                self._harness = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            harness = self._harness
        if harness is not None:
            harness.close()


def _completion_payload(completion: Completion) -> dict[str, object]:
    return {
        "id": completion.id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": completion.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": completion.content},
                "finish_reason": completion.finish_reason,
            }
        ],
    }


class HarnessRequestHandler(BaseHTTPRequestHandler):
    server_version = "GalarisDeepSeekHarness/1"

    @property
    def config(self) -> AdapterConfig:
        return cast("HarnessHTTPServer", self.server).config

    def log_message(self, format: str, *args: object) -> None:
        _LOG.info("%s - %s", self.address_string(), format % args)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        expected = f"Bearer {self.config.api_token}"
        supplied = self.headers.get("Authorization", "")
        return secrets.compare_digest(supplied, expected)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/v1/models":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.config.model,
                            "object": "model",
                            "owned_by": "galaris",
                        }
                    ],
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request_too_large"})
            return
        try:
            raw_body = cast(object, json.loads(self.rfile.read(length)))
            if not isinstance(raw_body, Mapping):
                raise ValueError("request body must be an object.")
            parsed_body = dict(cast(Mapping[str, object], raw_body))
            header_context = {
                "galaris_task_id": "X-Galaris-Task-Id",
                "galaris_run_id": "X-Galaris-Agent-Run-Id",
                "galaris_effort": "X-Galaris-Effort",
                "galaris_reasoning_effort": "X-Galaris-Reasoning-Effort",
                "galaris_approval_action": "X-Galaris-Approval-Action",
                "galaris_request_limit": "X-Galaris-Request-Limit",
                "galaris_tool_call_limit": "X-Galaris-Tool-Call-Limit",
            }
            for body_key, header_name in header_context.items():
                value = self.headers.get(header_name, "").strip()
                if value:
                    parsed_body[body_key] = value
            body: Mapping[str, object] = parsed_body
        except (json.JSONDecodeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if not _RUN_SLOT.acquire(blocking=False):
            self._json(HTTPStatus.CONFLICT, {"error": "harness_busy"})
            return
        try:
            if body.get("stream") is True:
                self._stream_completion(body)
            else:
                completion = run_completion(body, self.config)
                self._json(HTTPStatus.OK, _completion_payload(completion))
        except ValueError as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception:
            _LOG.exception("DeepSeek Harness run failed")
            self._json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "error": "deepseek_harness_failed",
                    "detail": "DeepSeek Harness execution failed.",
                },
            )
        finally:
            _RUN_SLOT.release()

    def _stream_completion(self, body: Mapping[str, object]) -> None:
        active = ActiveRun()
        outcome: queue.Queue[Completion | BaseException] = queue.Queue(maxsize=1)
        notifications: queue.Queue[object] = queue.Queue()
        adapter = DeepSeekStreamAdapter()

        def worker() -> None:
            try:
                outcome.put(
                    run_completion(
                        body,
                        self.config,
                        active=active,
                        on_notification=notifications.put,
                    )
                )
            except BaseException as exc:
                outcome.put(exc)

        thread = threading.Thread(target=worker, name="dsh-run", daemon=True)
        thread.start()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def write_sse(event_name: str | None, payload: object) -> None:
            prefix = f"event: {event_name}\n" if event_name else ""
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"{prefix}data: {data}\n\n".encode())
            self.wfile.flush()

        def write_emission(emission: StreamEmission) -> None:
            if emission.kind == "semantic":
                write_sse("galaris.agent-message/v1", emission.payload)
                return
            write_sse(
                None,
                {
                    "id": "chatcmpl-dsh-live",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": str(body.get("model") or self.config.model),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": emission.payload.get("content", "")
                            },
                            "finish_reason": None,
                        }
                    ],
                },
            )

        try:
            while thread.is_alive():
                try:
                    notification = notifications.get(timeout=1.0)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                else:
                    for emission in adapter.consume(notification):
                        write_emission(emission)
            while not notifications.empty():
                for emission in adapter.consume(notifications.get_nowait()):
                    write_emission(emission)
            for emission in adapter.finish():
                write_emission(emission)
            result = outcome.get_nowait()
            if isinstance(result, BaseException):
                raise result
            if not adapter.streamed_text.endswith(result.content):
                write_emission(StreamEmission("text", {"content": result.content}))
            write_sse(
                "galaris.agent-result/v1",
                {
                    "success": True,
                    "result": result.content,
                    "usage": adapter.usage,
                    "metadata": {"runtime_run_id": result.id},
                },
            )
            final: dict[str, object] = {
                "id": result.id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": result.model,
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": result.finish_reason}
                ],
            }
            write_sse(None, final)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            active.cancel()
        except BaseException:
            _LOG.exception("DeepSeek Harness streaming run failed")
            error = json.dumps(
                {
                    "error": "deepseek_harness_failed",
                    "detail": "DeepSeek Harness execution failed.",
                },
                ensure_ascii=False,
            )
            try:
                self.wfile.write(f"data: {error}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                active.cancel()


class HarnessHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: AdapterConfig) -> None:
        self.config = config
        super().__init__(address, HarnessRequestHandler)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = AdapterConfig.from_environment()
    config.session_root.mkdir(parents=True, exist_ok=True)
    config.workspace.mkdir(parents=True, exist_ok=True)
    server = HarnessHTTPServer(("0.0.0.0", 8080), config)
    _LOG.info("DeepSeek Harness adapter ready on port 8080 model=%s", config.model)
    server.serve_forever()


if __name__ == "__main__":
    main()


__all__ = ["AdapterConfig", "Completion", "render_prompt", "run_completion"]
