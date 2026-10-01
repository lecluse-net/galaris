"""Standalone control support copied into isolated managed runtime images.

This module deliberately uses the standard library only. Human waiting belongs to
the runtime actor, outside its HTTP response and outside the Galaris Task lease.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PROTOCOL = "galaris.runtime-authorization/v1"


def _object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


class ActionApprovals:
    def __init__(self, *, mcp_url: str, token: str, run_context: str,
                 session: str, on_pending: Callable[[str], None], on_running: Callable[[], None] | None = None) -> None:
        self.url = mcp_url.split("/mcp/", 1)[0] + "/tools/runtime-authorizations"
        if "/mcp/" not in mcp_url:
            raise PermissionError("The managed MCP endpoint is required")
        self.token, self.run_context, self.session = token, run_context, session
        self.on_pending = on_pending
        self.on_running = on_running
        self.mcp_url = mcp_url
        self.cancelled = threading.Event()
        self.permits: dict[str, str] = {}
        self.waiting: set[str] = set()
        self._waiting_lock = threading.RLock()

    def _pending(self, identifier: str) -> None:
        with self._waiting_lock:
            self.waiting.add(identifier)
            self.on_pending(identifier)

    def _running(self, identifier: str | None = None) -> None:
        with self._waiting_lock:
            if identifier is not None:
                self.waiting.discard(identifier)
            if self.on_running:
                self.on_running()

    def _post(self, suffix: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.token or not self.run_context:
            raise PermissionError("A server-issued runtime context is required")
        request = Request(self.url + suffix, data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                "X-Galaris-Run-Context": self.run_context}, method="POST")
        with urlopen(request, timeout=15) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise PermissionError("The authorization response exceeded its limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise PermissionError("Invalid authorization response")
        return cast(dict[str, Any], result)

    def validate(self, *, configuration: dict[str, Any] | None = None) -> None:
        request = Request(self.url + "/context", headers={"Authorization": f"Bearer {self.token}",
            "X-Galaris-Run-Context": self.run_context})
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read(4096))
            if result.get("active") is not True:
                raise PermissionError("The managed run context is unavailable")
            if configuration is not None and result.get("configuration") != configuration:
                raise PermissionError("The runtime configuration does not match the issued context")

    def authorize(self, callback: str, name: str, arguments: dict[str, Any], *,
                  precondition: Callable[[], dict[str, Any]] | None = None) -> bool:
        """Consume exactly one agreement immediately before returning to the SDK."""
        deadline = time.monotonic() + 24 * 60 * 60
        while not self.cancelled.is_set() and time.monotonic() < deadline:
            snapshot = {**arguments, **({"precondition": precondition()} if precondition else {})}
            try:
                result = self._post("", {"callback_key": callback, "name": name,
                    "session": self.session, "arguments": snapshot})
            except HTTPError as error:
                if error.code in (401, 403, 404, 409, 422):
                    return False
                # No agreement is assumed after a transport failure, including a lost claim.
                if self.cancelled.wait(2):
                    return False
                continue
            except (OSError, ValueError):
                if self.cancelled.wait(2):
                    return False
                continue
            status = result.get("status")
            if status == "executing" and result.get("claimed") is True:
                self.permits[callback] = str(result["request_id"])
                self._running(str(result.get("request_id") or ""))
                return True
            if status != "pending":
                self._running(str(result.get("request_id") or ""))
                return False
            self._pending(str(result["request_id"]))
            if self.cancelled.wait(2):
                return False
        return False

    def mcp(self, body: dict[str, Any]) -> tuple[int, bytes]:
        """Hold the SDK call while Galaris releases its orchestrator lease."""
        parameters = _object(body.get("params"))
        while not self.cancelled.is_set():
            request = Request(self.mcp_url, data=json.dumps(body).encode(), method="POST", headers={
                "Authorization": f"Bearer {self.token}", "X-Galaris-Run-Context": self.run_context,
                "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            with urlopen(request, timeout=120) as response:
                raw = response.read(16_000_001)
                status = response.status
                content_type = response.headers.get("Content-Type", "")
            if len(raw) > 16_000_000:
                raise PermissionError("The MCP response exceeded its bounded transport limit")
            if not raw:
                return status, raw
            if "text/event-stream" in content_type:
                messages = [json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith("data:")]
                result = next((message for message in messages if message.get("id") == body.get("id")), None)
                if result is None:
                    raise PermissionError("MCP returned no matching response")
            else:
                result = json.loads(raw)
            payload = _object(result.get("result") or _object(result.get("error")).get("data"))
            meta = _object(payload.get("_meta") or payload.get("meta") or payload)
            authorization = _object(meta.get("galaris.authorization/v1"))
            if authorization.get("disposition") != "authorization_required":
                self._running()
                return status, json.dumps(result, ensure_ascii=False).encode()
            identifier = str(authorization["request_id"])
            self._pending(identifier)
            while not self.cancelled.wait(1):
                check = Request(self.url + "/" + identifier, headers={"Authorization": f"Bearer {self.token}",
                    "X-Galaris-Run-Context": self.run_context})
                with urlopen(check, timeout=15) as decision:
                    current = json.loads(decision.read(4096)).get("status")
                if current != "pending":
                    break
            if self.cancelled.is_set():
                break
            self._running(identifier)
            metadata = dict(_object(parameters.get("_meta")))
            metadata["galaris.authorization/v1"] = {"continuation": authorization["continuation"]}
            if proof := meta.get("galaris.execution/v1"):
                metadata["galaris.execution/v1"] = proof
            parameters = {**parameters, "_meta": metadata}
            body = {**body, "params": parameters}
        raise PermissionError("The managed MCP call was cancelled")

    def finish(self, callback: str, *, outcome: str, receipt: dict[str, Any]) -> None:
        identifier = self.permits.pop(callback, None)
        if identifier is None:
            return
        try:
            self._post("/receipt", {"request_id": identifier, "outcome": outcome, "receipt": receipt})
        except (OSError, ValueError):
            # Missing delivery evidence remains executing, then outcome_unknown server-side.
            pass


def file_precondition(arguments: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Bind explicit file targets to their current content without exporting those bytes."""
    result: dict[str, Any] = {"workspace": str(workspace.resolve())}
    for key in ("file_path", "path", "filePath"):
        value = arguments.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = workspace / path
        path = path.resolve()
        if not path.is_relative_to(workspace.resolve()):
            raise PermissionError("The local file target is outside the runtime workspace")
        if path.is_file():
            if path.stat().st_size > 50 * 1024 * 1024:
                raise PermissionError("The local target exceeds the approval snapshot limit")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            result[key] = {"path": str(path), "sha256": digest}
        else:
            result[key] = {"path": str(path), "exists": path.exists()}
    return result


class RuntimeActor:
    def __init__(self, identifier: str, path: Path, fingerprint: str) -> None:
        self.identifier, self.path, self.fingerprint = identifier, path, fingerprint
        self.lock = threading.RLock()
        self.approvals: ActionApprovals | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task[Any] | None = None
        self.state: dict[str, Any] = {"runtime_run_id": identifier, "status": "running",
            "messages": [], "result": "", "authorization_requests": []}
        self.persist()

    def persist(self) -> None:
        with self.lock:
            encoded = json.dumps({"fingerprint": self.fingerprint, "state": self.state}, ensure_ascii=False, default=str)
            if len(encoded.encode()) > 4_000_000:
                raise RuntimeError("Runtime control state exceeded its bounded journal")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".pending")
            with temporary.open("w", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)

    def pending(self, identifier: str) -> None:
        with self.lock:
            self.state["status"] = "waiting_for_authorization"
            self.state["authorization_requests"] = sorted(self.approvals.waiting) if self.approvals else [identifier]
            self.persist()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))

    def running(self) -> None:
        with self.lock:
            if self.approvals and self.approvals.waiting:
                self.state["authorization_requests"] = sorted(self.approvals.waiting)
                self.state["status"] = "waiting_for_authorization"
                self.persist()
                return
            self.state["status"] = "running"
            self.state["authorization_requests"] = []
            self.persist()

    async def consume(self, events: AsyncIterator[tuple[str, dict[str, Any]]]) -> None:
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        try:
            async for kind, payload in events:
                with self.lock:
                    self.state["status"] = "running"
                    self.state["authorization_requests"] = []
                    if kind == "result":
                        self.state.update(payload)
                        self.state["status"] = "completed" if payload.get("success") is not False else "failed"
                        self.persist()
                    elif kind == "tool":
                        self.state["messages"].append(payload)
                    elif kind == "text":
                        self.state["result"] += str(payload.get("content") or "")
            with self.lock:
                if self.state["status"] == "running":
                    self.state["status"] = "failed"
                    self.state["success"] = False
                self.persist()
        except BaseException:
            with self.lock:
                self.state.update(status="outcome_unknown", success=False,
                    result="The runtime stopped without a confirmed outcome; no action was replayed.")
                self.persist()
        finally:
            if self.approvals:
                for callback in list(self.approvals.permits):
                    self.approvals.finish(callback, outcome="outcome_unknown", receipt={})
            with self.lock:
                self.state["stopped"] = True
                self.persist()


class RuntimeRuns:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.RLock()
        self.actors: dict[str, RuntimeActor] = {}

    def start(self, run_context: str, body: dict[str, Any],
              factory: Callable[[RuntimeActor], AsyncIterator[tuple[str, dict[str, Any]]]]) -> str:
        if not run_context:
            raise PermissionError("A server-issued run context is required")
        identifier = hashlib.sha256(run_context.encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        with self.lock:
            existing = self.actors.get(identifier)
            path = self.root / f"{identifier}.json"
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise PermissionError("The runtime context is already bound to different input")
                return identifier
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if data["fingerprint"] != fingerprint:
                    raise PermissionError("The durable runtime input changed")
                # Process-local SDK continuations cannot be invented after a runtime crash.
                return identifier
            if len(self.actors) >= 200:
                for key, actor in list(self.actors.items()):
                    if actor.snapshot()["status"] in ("completed", "failed", "outcome_unknown"):
                        self.actors.pop(key)
                if len(self.actors) >= 200:
                    raise RuntimeError("Runtime control capacity exceeded")
            actor = RuntimeActor(identifier, path, fingerprint)
            self.actors[identifier] = actor
            async def events() -> AsyncIterator[tuple[str, dict[str, Any]]]:
                async for event in factory(actor):
                    yield event
            threading.Thread(target=lambda: asyncio.run(actor.consume(events())), daemon=True).start()
        return identifier

    def get(self, identifier: str) -> dict[str, Any]:
        if len(identifier) != 64 or any(char not in "0123456789abcdef" for char in identifier):
            raise LookupError("Runtime run not found")
        with self.lock:
            actor = self.actors.get(identifier)
            if actor is not None:
                return actor.snapshot()
            path = self.root / f"{identifier}.json"
            if not path.exists():
                raise LookupError("Runtime run not found")
            state = json.loads(path.read_text(encoding="utf-8"))["state"]
            if state["status"] in ("running", "waiting_for_authorization"):
                state.update(status="outcome_unknown", success=False,
                    result="The runtime restarted; its unfinished operation was not replayed.")
            return state

    def cancel(self, identifier: str) -> None:
        with self.lock:
            actor = self.actors.get(identifier)
            if actor is None:
                raise LookupError("Runtime run not found")
            if actor.approvals is not None:
                actor.approvals.cancelled.set()
            if actor.loop is not None and actor.task is not None and not actor.task.done():
                actor.loop.call_soon_threadsafe(actor.task.cancel)
