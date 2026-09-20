from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import AgentManagementScope
from bridge.hermes import router as hermes_router
from bridge.hermes import harness_supervisor


@pytest.mark.asyncio
async def test_supervisor_reports_runtime_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(agent_driver="hermes")
    controller = SimpleNamespace(get_status=AsyncMock(return_value="stopped"))
    model_probe = AsyncMock(
        side_effect=AssertionError("model probes must not drive lifecycle state")
    )

    hydrate = AsyncMock()
    monkeypatch.setattr(harness_supervisor.config_service, "hydrate_agent", hydrate)
    monkeypatch.setattr(
        harness_supervisor.manager,
        "get_agent",
        MagicMock(return_value=controller),
    )
    monkeypatch.setattr(
        harness_supervisor.manager,
        "check_model_available",
        model_probe,
    )

    result = await harness_supervisor.supervisor.status(agent)  # type: ignore[arg-type]

    assert result == "stopped"
    hydrate.assert_awaited_once_with(agent)
    controller.get_status.assert_awaited_once_with()
    model_probe.assert_not_awaited()


def test_supervisor_advertises_per_agent_management_capabilities() -> None:
    agent = SimpleNamespace(agent_driver="hermes")
    assert harness_supervisor.supervisor.capabilities(agent) == frozenset({  # type: ignore[arg-type]
        "status",
        "start",
        "stop",
        "restart",
        "update",
        "logs",
        "refresh",
    })


@pytest.mark.asyncio
async def test_configuration_list_uses_bridge_owned_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(id=7, agent_driver="hermes")
    projected = SimpleNamespace(id=7)
    monkeypatch.setattr(
        hermes_router,
        "list_agent_records",
        AsyncMock(return_value=(agent,)),
    )
    monkeypatch.setattr(
        hermes_router,
        "current_management_scope",
        AsyncMock(return_value=AgentManagementScope(7, frozenset({7}))),
    )
    public_configuration = AsyncMock(return_value=projected)
    monkeypatch.setattr(
        hermes_router.config_service,
        "public_configuration",
        public_configuration,
    )

    result = await hermes_router.list_hermes_configurations()

    assert result == [projected]
    public_configuration.assert_awaited_once_with(agent)
