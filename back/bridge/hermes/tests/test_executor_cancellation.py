from types import SimpleNamespace
from typing import cast
from uuid import uuid4

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
async def test_cancellation_of_an_unknown_local_run_is_explicit() -> None:
    with pytest.raises(RuntimeError, match="No active Hermes runtime run"):
        await executor.cancel(uuid4())
