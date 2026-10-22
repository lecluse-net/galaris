"""Exercise the pinned Hermes worker and stop handlers without a model or real tools.

Run in the Hermes image, with no network or installation credentials. Only the agent
work and authentication boundary are synthetic; the runtime lifecycle is unchanged.
"""

import asyncio
from contextlib import AbstractContextManager, nullcontext, suppress
from dataclasses import dataclass
import importlib
import json
from threading import Event
from types import SimpleNamespace
from typing import Any


@dataclass
class SyntheticAgent:
    started: Event
    release: Event
    interrupted: Event

    def run_conversation(self, **kwargs: object) -> dict[str, object]:
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("The qualification did not release its synthetic worker")
        return {"interrupted": self.interrupted.is_set(), "final_response": "synthetic result"}

    def hard_interrupt(self, message: str | None = None) -> None:
        self.interrupted.set()


async def qualify() -> None:
    # These modules exist only inside the pinned external runtime image.
    api_server = importlib.import_module("gateway.platforms.api_server")
    runs = importlib.import_module("gateway.platforms.api_server_runs")

    for mode in ("cooperative", "task_cancelled", "natural"):
        started, release, interrupted = Event(), Event(), Event()

        def profile_scope(_profile: object) -> AbstractContextManager[None]:
            return nullcontext()

        def create_agent(
            *, _started: Event = started, _release: Event = release,
            _interrupted: Event = interrupted, **_kwargs: object,
        ) -> SyntheticAgent:
            return SyntheticAgent(_started, _release, _interrupted)

        def ignore(*_args: object, **_kwargs: object) -> None:
            pass

        def owns_run(*_args: object) -> bool:
            return True

        host = api_server.APIServerAdapter(api_server.PlatformConfig(enabled=True))
        host._profile_scope = profile_scope
        host._create_agent = create_agent
        host._bind_api_server_session = ignore
        host._check_run_auth = ignore
        host._check_auth = ignore
        host._request_owns_run = owns_run
        host._memory_sessions = SimpleNamespace(checkin=ignore)
        capability_route = next(handler for method, path, handler in runs._http_routes(host)
            if method == "GET" and path == "/v1/galaris/capabilities")
        capability = json.loads((await capability_route(SimpleNamespace())).body)
        assert capability == {"authorization_protocol": "galaris.runtime-authorization/v1", "resumable_runs": True}
        run_id = f"synthetic-{mode}"
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        host._run_streams[run_id] = queue
        launch = runs._RunLaunch(
            owner=host, run_id=run_id, queue=queue, session_id=run_id,
            gateway_session_key=None, declared_selected=False, user_message="synthetic work",
            conversation_history=[], session_history_delivery=False,
            agent_kwargs={"room_dispatch": None}, request_profile=None,
            browser_control_principal=None, browser_control_transport_family=None,
        )
        worker: asyncio.Task[None] = asyncio.create_task(runs._execute_run(host, launch, _api_server=api_server))
        host._active_run_tasks[run_id] = worker
        request = SimpleNamespace(match_info={"run_id": run_id})
        try:
            assert await asyncio.to_thread(started.wait, 5), "Hermes did not start the worker"
            if mode != "natural":
                response = await host._handle_stop_run(request)
                assert json.loads(response.body)["status"] == "stopping"
                assert interrupted.is_set()
            if mode == "task_cancelled":
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
                assert host._run_statuses[run_id]["status"] == "cancelled"
            response = await host._handle_get_run(request)
            assert json.loads(response.body).get("execution_stopped") is not True
            release.set()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(worker, 5)
            async with asyncio.timeout(5):
                while host._run_statuses[run_id].get("execution_stopped") is not True:
                    await asyncio.sleep(0.01)
            response = await host._handle_get_run(request)
            status = json.loads(response.body)
            assert status["execution_stopped"] is True
            assert status["status"] == ("completed" if mode == "natural" else "cancelled")
            events: list[dict[str, Any]] = []
            while not queue.empty():
                event = queue.get_nowait()
                if event and event.get("event") in {"run.completed", "run.cancelled"}:
                    events.append(event)
            assert len(events) == 1
            # An early asyncio terminal must retain its uncertainty in the SSE history.
            assert events[0]["execution_stopped"] is (mode != "task_cancelled")
        finally:
            release.set()
            with suppress(asyncio.CancelledError):
                await worker
        print(f"PASS Hermes {mode}: stop evidence follows worker exit")


def qualify_gateway(origin: str, gate: dict[str, Any]) -> None:
    """Exercise the assembled gateway, including its native session authority."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    home = Path("/tmp/hermes-gateway-qualification")
    home.mkdir()
    (home / "config.yaml").write_text(json.dumps({
        "model": {"default": "qualification", "provider": "custom", "base_url": origin + "/v1",
                  "api_key": "qualification-token", "api_mode": "chat_completions"},
        "agent": {"max_turns": 3},
        "terminal": {"cwd": "/workspace", "env": "local"},
        "platform_toolsets": {"api_server": ["file"]},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
    }))
    token = "synthetic-gateway-qualification-key"
    # This qualification has no host data mounts and writes only to disposable tmpfs.
    # Its cap-drop ALL container cannot use the official entrypoint's setuid step.
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_ALLOW_ROOT_GATEWAY": "1", "API_SERVER_KEY": token,
           "API_SERVER_HOST": "127.0.0.1", "API_SERVER_PORT": "18642",
           "TERMINAL_CWD": "/workspace", "TERMINAL_ENV": "local", "HERMES_WRITE_SAFE_ROOT": "/workspace"}

    def request(path: str, body: dict[str, Any] | None = None, *, key: str = token,
                idempotency: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        req = Request("http://127.0.0.1:18642" + path, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    log_path = Path("/tmp/hermes-gateway-qualification.log")
    with log_path.open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "hermes_cli.main", "gateway", "run"],
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while True:
                assert process.poll() is None, log_path.read_text()[-12000:]
                try:
                    request("/health")
                    break
                except (URLError, OSError):
                    assert time.monotonic() < deadline, log_path.read_text()[-12000:]
                    time.sleep(0.1)
            try:
                request("/v1/runs", {"input": "synthetic"}, key="invalid")
                raise AssertionError("The gateway accepted an unauthenticated run")
            except HTTPError as exc:
                assert exc.code == 401
            for decision in ("deny", "allow", "stop"):
                allowed = decision == "allow"
                gate.clear()
                target = Path(f"/workspace/hermes-gateway-{decision}.txt")
                gate.update(path=str(target), requests=[], receipts=[])
                session = f"galaris_gateway_qualification_{decision}"
                request("/api/sessions", {"id": session})
                body = {"input": "Perform the synthetic write, then reply qualification-ok",
                        "session_id": session, "galaris_run_context": f"synthetic-context-{decision}"}
                result = request("/v1/runs", body, idempotency=session)
                run_id = result["run_id"]
                assert request("/v1/runs", body, idempotency=session)["run_id"] == run_id
                deadline = time.monotonic() + 30
                while not gate["requests"]:
                    status = request(f"/v1/runs/{run_id}")
                    assert status["status"] not in {"completed", "failed", "cancelled"}, (status, log_path.read_text()[-12000:])
                    assert time.monotonic() < deadline, log_path.read_text()[-12000:]
                    time.sleep(0.05)
                assert not target.exists(), "The assembled gateway executed before agreement"
                if decision == "stop":
                    assert request(f"/v1/runs/{run_id}/stop", {})["status"] == "stopping"
                    assert request(f"/v1/runs/{run_id}").get("execution_stopped") is not True
                gate["decision"] = "executing" if allowed else "denied"
                while True:
                    status = request(f"/v1/runs/{run_id}")
                    if status["status"] in {"completed", "failed", "cancelled"}:
                        break
                    assert time.monotonic() < deadline, log_path.read_text()[-12000:]
                    time.sleep(0.05)
                expected_status = "cancelled" if decision == "stop" else "completed"
                assert status["status"] == expected_status, (status, log_path.read_text()[-12000:])
                assert status.get("execution_stopped") is True, status
                assert target.exists() is allowed
                assert len(gate["receipts"]) == int(allowed)
                assert request(f"/v1/runs/{run_id}/stop", {})["status"] == expected_status
                print(f"PASS Hermes assembled gateway: {decision}, exact retry, worker exit")
            gate.clear()
            native = request("/v1/runs", {"input": "Reply qualification-ok"})
            deadline = time.monotonic() + 30
            while True:
                status = request(f"/v1/runs/{native['run_id']}")
                if status["status"] in {"completed", "failed", "cancelled"}:
                    break
                assert time.monotonic() < deadline, log_path.read_text()[-12000:]
                time.sleep(0.05)
            assert status["status"] == "completed", (status, log_path.read_text()[-12000:])
            assert "qualification-ok" in status.get("output", ""), status
            print("PASS Hermes assembled gateway: native session execution")
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    asyncio.run(qualify())
