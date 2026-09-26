from types import SimpleNamespace
from typing import cast
from uuid import uuid4
from unittest.mock import AsyncMock
from functools import partial

import httpx

import pytest

# pyright: reportPrivateUsage=false

from app.agent.contracts import AgentRunRequest
from bridge.hermes import executor
from bridge.hermes.client import HermesTarget
from bridge.hermes.driver import HermesAgentDriver


@pytest.mark.asyncio
async def test_driver_cancellation_stops_the_registered_direct_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = cast(
        AgentRunRequest,
        SimpleNamespace(run_id=uuid4(), id=uuid4()),
    )
    target = HermesTarget(
        url="http://alice-agent:8642/v1",
        api_key="secret",
        model="hermes-agent",
    )
    stopped: list[tuple[HermesTarget, str]] = []

    async def stop_run(selected: HermesTarget, runtime_run_id: str) -> dict[str, object]:
        stopped.append((selected, runtime_run_id))
        return {"status": "stopping"}

    monkeypatch.setattr(executor.client, "stop_run", stop_run)
    await executor._register_active_run(request, target, "hermes-run-42")
    try:
        await HermesAgentDriver().cancel(request.id)
    finally:
        await executor._unregister_active_run(request)

    assert stopped == [(target, "hermes-run-42")]
    assert HermesAgentDriver.spec.supports_cancellation is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["lost_reply", "refused", "missing", "wrong_run"])
async def test_remote_control_failures_never_confirm_stop(monkeypatch, failure):
    from app.agent import facade

    request = SimpleNamespace(run_id=uuid4(), id=uuid4())
    target = HermesTarget("http://synthetic-hermes/v1", "synthetic-key", "test-model")

    def handle(http_request):
        if failure == "missing":
            return httpx.Response(404)
        if http_request.method == "GET":
            return httpx.Response(200, json={"run_id": "other-run" if failure == "wrong_run" else "remote-run",
                "status": "running", "execution_stopped": False})
        if failure == "lost_reply":
            raise httpx.ReadError("Synthetic lost response")
        return httpx.Response(403)

    monkeypatch.setattr(executor.client.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handle)))
    await executor._register_active_run(request, target, "remote-run")
    try:
        receipt = await facade.cancel("hermes", request.run_id)
        assert receipt.state == "unknown"
    finally:
        await executor._unregister_active_run(request)

@pytest.mark.asyncio
async def test_cancellation_of_an_unknown_local_run_is_explicit() -> None:
    with pytest.raises(RuntimeError, match="No active Hermes runtime run"):
        await executor.cancel(uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "proof", "expected"), [
    ("running", False, "requested"), ("stopping", False, "requested"),
    ("cancelled", False, "requested"), ("cancelled", None, "requested"),
    ("cancelled", "true", "requested"), ("running", True, "requested"),
    ("cancelled", True, "confirmed"), ("completed", True, "confirmed"),
    ("failed", True, "confirmed"),
])
async def test_cancellation_requires_remote_worker_proof(monkeypatch, status, proof, expected):
    request = SimpleNamespace(run_id=uuid4(), id=uuid4())
    target = HermesTarget("http://synthetic-hermes/v1", "synthetic-key", "test-model")
    poll = AsyncMock(return_value={"run_id": "remote-run", "status": status, "execution_stopped": proof})
    stop = AsyncMock(return_value={"run_id": "remote-run", "status": "stopping"})
    monkeypatch.setattr(executor.client, "get_run_status", poll)
    monkeypatch.setattr(executor.client, "stop_run", stop)
    await executor._register_active_run(request, target, "remote-run")
    try:
        receipt = await HermesAgentDriver().request_cancellation(request.run_id)
        assert receipt.state == expected
        assert receipt.run_id == request.run_id and receipt.scope == "remote"
        assert stop.await_count == (expected != "confirmed")
    finally:
        await executor._unregister_active_run(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["run", "driver", "legacy"])
async def test_recovery_never_controls_a_different_or_unidentified_run(monkeypatch, mismatch):
    from app.agent import facade
    from app.agent.task_port import task_port

    run_id = uuid4()
    target = HermesTarget("http://synthetic-hermes/v1", "synthetic-key", "test-model")
    payload = {
        "request_run_id": str(uuid4() if mismatch == "run" else run_id),
        "driver_code": "other" if mismatch == "driver" else "hermes",
        "runtime_run_id": "remote-run", "status": "running",
        "data": {} if mismatch == "legacy" else {
            "execution_strategy": "direct", "cancellation_target": executor._cancellation_target(target),
        },
    }
    monkeypatch.setattr(task_port, "get_by_id", AsyncMock(return_value=SimpleNamespace(
        data={"_agent_run_checkpoint": payload},
    )))
    poll, stop = AsyncMock(), AsyncMock()
    monkeypatch.setattr(executor.client, "get_run_status", poll)
    monkeypatch.setattr(executor.client, "stop_run", stop)
    assert (await facade.cancel("hermes", run_id, task_id=uuid4())).state == "unknown"
    poll.assert_not_awaited()
    stop.assert_not_awaited()
