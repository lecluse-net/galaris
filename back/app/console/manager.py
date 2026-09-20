"""Typed client for the embedded executor's private Unix control socket."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast
from uuid import uuid4


class EmbeddedExecutorManager:
    def __init__(self, socket_path: str | None = None, timeout_s: float = 15.0) -> None:
        self._socket_path = socket_path or os.getenv(
            "GALARIS_EXECUTOR_CONTROL_SOCKET",
            "/data/ssh-executor/run/control.sock",
        )
        self._timeout_s = timeout_s

    async def request(self, operation: str, **payload: Any) -> dict[str, Any]:
        request = {
            "id": str(uuid4()),
            "operation": operation,
            "payload": payload,
        }
        try:
            async with asyncio.timeout(self._timeout_s):
                reader, writer = await asyncio.open_unix_connection(self._socket_path)
                try:
                    writer.write(
                        json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
                    )
                    await writer.drain()
                    raw = await reader.readline()
                finally:
                    writer.close()
                    await writer.wait_closed()
        except (OSError, TimeoutError) as exc:
            raise RuntimeError(f"Embedded executor manager unavailable: {exc}") from exc
        if not raw:
            raise RuntimeError("Embedded executor manager returned an empty response")
        decoded = json.loads(raw)
        response = cast(dict[str, Any], decoded)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "Executor manager request failed"))
        result = response.get("result")
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}


embedded_executor_manager = EmbeddedExecutorManager()
