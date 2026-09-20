from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.harnesses import router
from app.harnesses.schemas import HarnessRuntimeState


@pytest.fixture(autouse=True)
def default_configuration(monkeypatch):
    async def configured(code):
        return router.get_provider(code).capabilities()
    monkeypatch.setattr(router, "configured_provider_capabilities", configured)


@pytest.mark.parametrize("lifecycle,status,expected", [
    ("absent", "absent", ["restart", "update"]),
    ("error", "error", ["restart", "update"]),
    ("ready", "running", ["stop", "restart", "update"]),
    ("ready", "stopped", ["start", "restart", "update"]),
    ("ready", "absent", ["restart", "update"]),
    ("ready", "unknown", ["restart", "update"]),
    ("provisioning", "provisioning", []),
    ("deprovisioning", "deprovisioning", []),
    ("internal", "internal", []),
])
def test_state_serializes_coherent_actions(lifecycle, status, expected):
    state = HarnessRuntimeState(
        lifecycle_status=lifecycle, status=status,
        capabilities=["status", "start", "stop", "restart", "update"],
    )
    assert state.model_dump()["available_actions"] == expected


def test_actions_never_invent_provider_capabilities():
    state = HarnessRuntimeState(
        lifecycle_status="absent", status="absent", capabilities=["status", "logs"],
    )
    assert state.available_actions == []
    state.capabilities = ["restart"]
    assert state.available_actions == ["restart"]
    state.managed = False
    assert state.available_actions == []


@pytest.mark.asyncio
async def test_absent_status_exposes_creation_without_querying_missing_runtime(monkeypatch):
    provider = SimpleNamespace(
        containerized=True, status=AsyncMock(),
        capabilities=lambda: frozenset({"status", "start", "restart"}),
    )
    target = SimpleNamespace(
        status="absent", provider_code="hermes", last_error=None,
        capabilities=provider.capabilities(),
    )
    monkeypatch.setattr(router, "get_agent_record", AsyncMock(return_value=SimpleNamespace(id=1)))
    monkeypatch.setattr(router.service, "resolve_target", AsyncMock(return_value=target))
    monkeypatch.setattr(router, "get_provider", lambda _: provider)
    result = await router.harness_status(1)
    assert result.status == "absent"
    assert result.available_actions == ["restart"]
    provider.status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle,action,allowed", [
    ("absent", "restart", True), ("error", "restart", True),
    ("absent", "start", False), ("provisioning", "restart", False),
    ("deprovisioning", "restart", False), ("ready", "start", True),
])
async def test_action_admission_uses_durable_lifecycle(monkeypatch, lifecycle, action, allowed):
    provider = SimpleNamespace(capabilities=lambda: frozenset({"start", "restart"}))
    monkeypatch.setattr(router, "get_provider", lambda _: provider)
    monkeypatch.setattr(router, "_selected", AsyncMock(return_value=(
        SimpleNamespace(id=1), SimpleNamespace(status=lifecycle, provider_code="hermes"), provider,
    )))
    background = BackgroundTasks()
    if allowed:
        await router.run_harness_action(1, action, background)
        assert len(background.tasks) == 1
    else:
        with pytest.raises(HTTPException) as exc:
            await router.run_harness_action(1, action, background)
        assert exc.value.status_code == 409
        assert background.tasks == []
