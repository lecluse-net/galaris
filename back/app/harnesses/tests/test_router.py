from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.harnesses import router
from app.agent import AgentTaskBlocker, AgentTaskBlockers
from app.harnesses.contracts import HarnessTarget


@pytest.fixture(autouse=True)
def default_configuration(monkeypatch):
    from app.harnesses import configuration
    from app.agent import HarnessExecutionPolicy

    monkeypatch.setattr(configuration, "read_policy", AsyncMock(return_value=(HarnessExecutionPolicy(), 0)))
    monkeypatch.setattr(configuration, "get_provider", lambda code: router.get_provider(code), raising=False)
    async def configured(code):
        return router.get_provider(code).capabilities()
    monkeypatch.setattr(router, "configured_provider_capabilities", configured)


@pytest.mark.asyncio
async def test_status_exposes_runtime_manager_unavailability_as_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(id=2)
    provider = SimpleNamespace(
        containerized=True,
        capabilities=lambda: frozenset({"status"}),
        status=AsyncMock(side_effect=RuntimeError("manager unavailable")),
    )
    target = HarnessTarget(
        id=uuid4(),
        harness_id=uuid4(),
        agent_id=2,
        name="Codex",
        provider_code="codex",
        driver_code="openai_messages",
        base_url=None,
        model=None,
        revision=1,
        status="ready",
        capabilities=frozenset({"status"}),
    )
    monkeypatch.setattr(router, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(router.service, "resolve_target", AsyncMock(return_value=target))
    monkeypatch.setattr(router, "get_provider", lambda _code: provider)

    with pytest.raises(HTTPException) as error:
        await router.harness_status(2)

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_logs_return_persisted_diagnostic_while_runtime_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(
        capabilities=lambda: frozenset({"logs"}),
        logs=AsyncMock(),
    )
    target = HarnessTarget(
        id=uuid4(),
        harness_id=uuid4(),
        agent_id=2,
        name="Hermes Agent",
        provider_code="hermes",
        driver_code="hermes",
        base_url=None,
        model=None,
        revision=1,
        status="error",
        last_error="The previous runtime could not be removed.",
        capabilities=frozenset({"logs"}),
    )
    monkeypatch.setattr(
        router,
        "_selected",
        AsyncMock(return_value=(SimpleNamespace(id=2), target, provider)),
    )

    result = await router.harness_logs(2)

    assert result.lines == ["The previous runtime could not be removed."]
    provider.logs.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_blockers_expose_paused_tasks_and_active_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    monkeypatch.setattr(
        router,
        "get_agent_task_blockers",
        AsyncMock(
            return_value=AgentTaskBlockers(
                paused_tasks=(AgentTaskBlocker(id=task_id, label="Paused task"),),
                active_count=1,
                active_tasks=(AgentTaskBlocker(id=task_id, label="Retry pending"),),
            )
        ),
    )

    result = await router.harness_task_blockers(7)

    assert result.active_count == 1
    assert [(task.id, task.label) for task in result.active_tasks] == [
        (task_id, "Retry pending")
    ]
    assert [(task.id, task.label) for task in result.paused_tasks] == [
        (task_id, "Paused task")
    ]


@pytest.mark.asyncio
async def test_terminate_paused_task_blockers_returns_remaining_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminate = AsyncMock(return_value=AgentTaskBlockers(active_count=1))
    monkeypatch.setattr(router, "terminate_paused_agent_tasks", terminate)

    result = await router.terminate_harness_paused_tasks(8)

    terminate.assert_awaited_once_with(8)
    assert result.paused_tasks == []
    assert result.active_count == 1
