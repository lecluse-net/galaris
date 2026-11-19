"""Backend side of the authenticated Process Python runner protocol."""

import asyncio
from hashlib import sha256
import json
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import logfire

from core.settings import settings

from .engine import ProcessEngineError
from .isolated_code import CodeInvocation, CodeObservation

MAX_MESSAGE_BYTES = 2_000_000


class RemotePythonRunner:
    def __init__(self, url: str, token: str) -> None:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("The Process Python runner requires a dedicated HTTPS origin")
        if len(token) < 32 or any(not char.isascii() or not char.isprintable() or char.isspace() for char in token):
            raise ValueError("The Process Python runner requires a dedicated service credential")
        self._url = url.rstrip("/")
        self._token = token
        self.identity = sha256(self._url.encode()).hexdigest()

    async def submit(self, invocation: CodeInvocation) -> CodeObservation:
        content = json.dumps({
            "phase": invocation.phase,
            "source": invocation.source,
            "values": invocation.values,
            "handles": invocation.handles,
        }, ensure_ascii=False, allow_nan=False).encode()
        if len(content) > MAX_MESSAGE_BYTES or len(invocation.source) > 200_000:
            raise ProcessEngineError("isolated_code_failed", "Python input exceeds the message limit")
        return await self._request("PUT", invocation.id, content=content)

    async def observe(self, invocation_id: UUID) -> CodeObservation:
        return await self._request("GET", invocation_id)

    async def cancel(self, invocation_id: UUID) -> CodeObservation:
        return await self._request("DELETE", invocation_id)

    async def reply(self, invocation_id: UUID, call_id: UUID, result: dict[str, Any]) -> CodeObservation:
        content = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        return await self._request("PUT", invocation_id, suffix=f"/calls/{call_id}", content=content)

    async def _request(self, method: str, invocation_id: UUID, *, suffix: str = "", content: bytes | None = None) -> CodeObservation:
        headers = {"Authorization": f"Bearer {self._token}", "Accept-Encoding": "identity"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        try:
            with logfire.suppress_instrumentation():
                async with asyncio.timeout(4), httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                    async with client.stream(method, f"{self._url}/v1/invocations/{invocation_id}{suffix}",
                                             headers=headers, content=content) as response:
                        response.raise_for_status()
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise ValueError("The runner must return uncompressed JSON")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > MAX_MESSAGE_BYTES:
                                raise ValueError("The runner response exceeds the message limit")
                            body.extend(chunk)
            decoded: object = json.loads(body)
            if not isinstance(decoded, dict):
                raise ValueError("The runner response must be an object")
            value = cast(dict[str, Any], decoded)
            if value.pop("invocation_id", None) != str(invocation_id):
                raise ValueError("The runner response has the wrong invocation")
            received = CodeObservation.model_validate(value)
            if received.stopped and received.status not in {"success", "error", "cancelled"}:
                raise ValueError("Physical stop requires a terminal receipt")
            if received.capability_call is not None and (received.status != "running" or received.stopped):
                raise ValueError("Only running invocations may request a capability")
            # Runner diagnostics are untrusted and may contain user input or data.
            return received.model_copy(update={"diagnostic": ""})
        except (httpx.TransportError, TimeoutError) as error:
            raise ProcessEngineError("remote_python_unreachable", "The isolated Python runner is unreachable",
                                     retryable=True) from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {429, 502, 503, 504}:
                raise ProcessEngineError("remote_python_unreachable", "The isolated Python runner is unavailable",
                                         retryable=True) from error
            raise ProcessEngineError("remote_python_protocol", "The isolated Python runner rejected the operation") from error
        except (ValueError, RecursionError) as error:
            raise ProcessEngineError("remote_python_protocol", "Invalid receipt from the isolated Python runner") from error


def configured_python_runner() -> RemotePythonRunner | None:
    if not settings.PROCESS_PYTHON_RUNNER_URL or not settings.PROCESS_PYTHON_RUNNER_TOKEN.get_secret_value():
        return None
    try:
        return RemotePythonRunner(settings.PROCESS_PYTHON_RUNNER_URL, settings.PROCESS_PYTHON_RUNNER_TOKEN.get_secret_value())
    except ValueError:
        return None
