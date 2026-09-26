"""Exercise the pinned Hermes worker and stop handlers without a model or real tools.

Run in the Hermes image, with no network or installation credentials. Only the agent
work and authentication boundary are synthetic; the runtime lifecycle is unchanged.
"""

import asyncio
from contextlib import AbstractContextManager, nullcontext, suppress
import importlib
import json
from threading import Event
from types import SimpleNamespace
from typing import Any


async def qualify() -> None:
    # These modules exist only inside the pinned external runtime image.
    api_server = importlib.import_module("gateway.platforms.api_server")
    runs = importlib.import_module("gateway.platforms.api_server_runs")

    for mode in ("cooperative", "task_cancelled", "natural"):
        started, release, interrupted = Event(), Event(), Event()

        class SyntheticAgent:
            def run_conversation(self, **kwargs: object) -> dict[str, object]:
                started.set()
                if not release.wait(10):
                    raise TimeoutError("The qualification did not release its synthetic worker")
                return {"interrupted": interrupted.is_set(), "final_response": "synthetic result"}

            def hard_interrupt(self, message: str | None = None) -> None:
                interrupted.set()

        def profile_scope(_profile: object) -> AbstractContextManager[None]:
            return nullcontext()

        def create_agent(**_kwargs: object) -> SyntheticAgent:
            return SyntheticAgent()

        def ignore(*_args: object, **_kwargs: object) -> None:
            pass

        def owns_run(*_args: object) -> bool:
            return True

        host = api_server.APIServerAdapter.__new__(api_server.APIServerAdapter)
        runs._initialize_run_state(host, store_factory=SimpleNamespace)
        host._profile_scope = profile_scope
        host._create_agent = create_agent
        host._bind_api_server_session = ignore
        host._check_run_auth = ignore
        host._request_owns_run = owns_run
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


if __name__ == "__main__":
    asyncio.run(qualify())
