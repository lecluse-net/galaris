# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false
"""Keep the SDK stdout router live while an exact approval waits for a human."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import MethodType
from typing import Any

from runtime_support import file_precondition  # pyright: ignore[reportMissingImports]


def install_permissions(client: Any, actor: Any, workspace: Path) -> ThreadPoolExecutor:
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="galaris-approval")
    slots = threading.BoundedSemaphore(8)
    items: dict[str, dict[str, Any]] = {}
    callbacks: dict[str, str] = {}
    lock = threading.RLock()

    def answer(message: dict[str, Any]) -> None:
        try:
            method, parameters = message.get("method"), message.get("params") or {}
            decision: dict[str, Any] = {"decision": "decline"}
            if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
                item_id = str(parameters.get("itemId") or "")
                with lock:
                    item = dict(items.get(item_id) or {})
                if method == "item/commandExecution/requestApproval":
                    valid = bool(parameters.get("command") or item.get("command"))
                else:
                    valid = bool(item.get("changes"))
                if valid and actor.approvals is not None:
                    callback = str(message["id"])
                    arguments = {"request": parameters, "item": item}
                    def precondition() -> dict[str, Any]:
                        snapshots = [file_precondition({"path": change["path"]}, workspace)
                            for change in item.get("changes", []) if isinstance(change, dict) and change.get("path")]
                        return {"workspace": str(workspace.resolve()), "files": snapshots}
                    if actor.approvals.authorize(callback, str(method), arguments, precondition=precondition):
                        with lock:
                            callbacks[item_id] = callback
                        decision = {"decision": "accept"}
            elif method == "item/permissions/requestApproval":
                decision = {"permissions": {}, "scope": "turn"}
            client._write_message({"id": message["id"], "result": decision})
        except BaseException:
            try:
                client._write_message({"id": message["id"], "result": {"decision": "decline"}})
            except BaseException:
                pass
        finally:
            slots.release()

    def reader(self: Any) -> None:
        try:
            while True:
                message = self._read_message()
                method = message.get("method")
                if method is not None and "id" in message:
                    if slots.acquire(blocking=False):
                        pool.submit(answer, message)
                    else:
                        self._write_message({"id": message["id"], "result": {"decision": "decline"}})
                    continue
                if method is not None:
                    parameters = message.get("params") or {}
                    item = parameters.get("item") or {}
                    if method in {"item/started", "item/fileChange/patchUpdated"} and item.get("id"):
                        with lock:
                            items[str(item["id"])] = item
                    if method == "item/completed" and item.get("id"):
                        with lock:
                            callback = callbacks.pop(str(item["id"]), None)
                        if callback and actor.approvals:
                            pool.submit(actor.approvals.finish, callback,
                                outcome="outcome_unknown" if item.get("status") == "failed" else "completed", receipt=item)
                    if isinstance(method, str):
                        self._router.route_notification(self._coerce_notification(method, message.get("params")))
                    continue
                self._router.route_response(message)
        except BaseException as error:
            self._router.fail_all(error)
    client._reader_loop = MethodType(reader, client)
    return pool
