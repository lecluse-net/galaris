from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import Agent
from app.harnesses import service
from app.harnesses.contracts import HarnessProvisioningResult
from app.harnesses.models import AgentHarness, Harness
from app.harnesses.schemas import (
    HarnessCatalogCreate,
    HarnessCatalogUpdate,
    HarnessRead,
    HarnessSelectionUpdate,
)


class _Provider:
    driver_code = "replacement-driver"
    label = "Replacement"
    containerized = True
    enabled_param: str | None = "harness.test.enabled"
    max_parallel_tasks = 1

    def __init__(self, code: str, calls: list[str]) -> None:
        self.code = code
        self.calls = calls

    def capabilities(self):
        return frozenset({"execute", "stream"})

    async def provision(self, agent, request, *, token):
        del agent, request, token
        self.calls.append("provision-new")
        return HarnessProvisioningResult(
            base_url="https://new.example/v1",
            model="new-model",
            capabilities=frozenset({"execute", "stream"}),
        )

    async def deprovision(self, agent, request):
        del agent, request
        self.calls.append(f"deprovision-{self.code}")

    async def status(self, agent):
        del agent
        return "running"

    async def run_action(self, agent, action):
        del agent
        self.calls.append(f"action-{action}")
        return "done"

    async def logs(self, agent, lines):
        del agent, lines
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_code, expected", [("openai_messages", False), ("codex", True), ("hermes", True)])
async def test_activity_source_is_frozen_in_target_and_builtin_harnesses_stay_native(monkeypatch, provider_code, expected):
    harness = Harness(id=uuid4(), name="Harness", provider_code=provider_code, driver_code=provider_code,
                      settings={"streams_ai_messages": False, "secret": "not-in-target"}, capabilities=["execute", "stream"])
    assignment = AgentHarness(id=uuid4(), agent_id=8, harness_id=harness.id, provider_code=provider_code,
                              revision=3, lifecycle_status="ready", capabilities=["execute", "stream"])
    agent = Agent(id=8, task_harness_id=harness.id)
    monkeypatch.setattr(service, "_assignment_for_agent", AsyncMock(return_value=assignment))
    monkeypatch.setattr(service, "_harness_for_assignment", AsyncMock(return_value=harness))
    monkeypatch.setattr(service, "get_provider", lambda code: _Provider(code, []))
    target = await service.resolve_target(agent)
    assert target.metadata["streams_ai_messages"] is expected
    assert "secret" not in target.metadata
    harness.settings = {"streams_ai_messages": True}
    assert target.metadata["streams_ai_messages"] is expected
    assert (await service.resolve_target(agent)).metadata["streams_ai_messages"] is True


@pytest.mark.asyncio
async def test_replacement_only_saves_preference_and_returns_background_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    old_provider = _Provider("old-provider", calls)
    new_provider = _Provider("new-provider", calls)
    old_harness = Harness(
        id=uuid4(),
        name="Old",
        provider_code="old-provider",
        driver_code="old-driver",
        capabilities=["execute"],
    )
    new_harness = Harness(
        id=uuid4(),
        name="Shared new Harness",
        provider_code="new-provider",
        driver_code="replacement-driver",
        capabilities=["execute", "stream"],
        enabled=True,
    )
    old_assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=old_harness.id,
        provider_code="old-provider",
        lifecycle_status="ready",
        capabilities=["execute"],
    )
    agent = cast(
        Agent,
        SimpleNamespace(
            id=7,
            code="alice",
            agent_driver="old-driver",
            task_harness_id=old_harness.id,
        ),
    )

    def add(row: object) -> None:
        if isinstance(row, AgentHarness) and row.id is None:
            row.id = uuid4()

    db = SimpleNamespace(
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(),
        delete=AsyncMock(),
        add=add,
    )

    monkeypatch.setattr(service, "_require_switchable", AsyncMock())
    monkeypatch.setattr(service, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        service,
        "_assignment_for_agent",
        AsyncMock(return_value=old_assignment),
    )

    monkeypatch.setattr(
        service,
        "_catalogue_choice",
        AsyncMock(return_value=new_harness),
    )
    monkeypatch.setattr(
        service,
        "_harness_for_assignment",
        AsyncMock(return_value=old_harness),
    )
    monkeypatch.setattr(service, "get_db", lambda: db)
    monkeypatch.setattr(
        service,
        "get_provider",
        lambda code: old_provider if code == "old-provider" else new_provider,
    )

    result, cleanup = await service.install(
        7,
        HarnessSelectionUpdate(harness_id=new_harness.id),
    )

    assert calls == []
    assert cleanup is not None
    assert cleanup.provider_code == "old-provider"
    assert agent.task_harness_id is None
    assert agent.agent_driver == "replacement-driver"
    assert result.harness_id == new_harness.id
    assert result.provider_code == "new-provider"
    assert result.lifecycle_status == "deprovisioning"
    assert old_assignment.provider_code == "new-provider"
    assert old_assignment.runtime_base_url is None


@pytest.mark.asyncio
async def test_non_terminal_tasks_block_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "agent_has_open_tasks", AsyncMock(return_value=True))

    with pytest.raises(service.HarnessConflictError, match="non-terminal Tasks"):
        await service._require_switchable(9)


@pytest.mark.asyncio
async def test_explicit_recreate_deprovisions_then_provisions_selected_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    provider = _Provider("codex", calls)
    harness = Harness(
        id=service._bridge_catalogue_id("codex"),
        name="Codex",
        provider_code="codex",
        driver_code="replacement-driver",
        enabled=True,
    )
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=None,
        provider_code="codex",
        lifecycle_status="absent",
    )
    agent = cast(
        Agent,
        SimpleNamespace(
            id=7,
            code="alice",
            agent_driver="replacement-driver",
            task_harness_id=None,
        ),
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_switchable", AsyncMock())
    monkeypatch.setattr(service, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        service,
        "_assignment_for_agent",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        service,
        "_harness_for_assignment",
        AsyncMock(return_value=harness),
    )
    monkeypatch.setattr(service, "get_provider", lambda _code: provider)
    monkeypatch.setattr(service, "get_db", lambda: db)

    await service._recreate_selected_runtime(7)

    assert calls == ["deprovision-codex", "provision-new"]
    assert assignment.lifecycle_status == "ready"
    assert assignment.runtime_base_url == "https://new.example/v1"
    assert assignment.last_error is None


@pytest.mark.asyncio
async def test_start_does_not_create_an_absent_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    provider = _Provider("codex", calls)
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=None,
        provider_code="codex",
        lifecycle_status="absent",
    )
    db = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def db_context():
        yield db

    monkeypatch.setattr(service, "get_db_session", db_context)
    monkeypatch.setattr(
        service,
        "_assignment_for_agent",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(service, "get_provider", lambda _code: provider)
    monkeypatch.setattr(service, "get_db", lambda: db)

    await service.run_action_in_background(7, "start")

    assert calls == []
    assert assignment.lifecycle_status == "error"
    assert assignment.last_error == (
        "Use restart or update to create the selected Harness runtime."
    )


@pytest.mark.asyncio
async def test_superseded_cleanup_never_deletes_the_recreated_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation_id = uuid4()
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=None,
        provider_code="codex",
        lifecycle_status="ready",
        provider_metadata={"selection_operation": str(uuid4())},
    )
    agent = cast(Agent, SimpleNamespace(id=7, code="alice"))
    cleanup = service.HarnessCleanup(
        assignment_id=assignment.id,
        agent_id=7,
        operation_id=operation_id,
        provider_code="hermes",
        request=service.HarnessProvisioningRequest(
            harness_id=assignment.id,
            catalogue_harness_id=uuid4(),
            agent_id=7,
            agent_code="alice",
            name="Hermes",
            base_url=None,
            model=None,
            revision=1,
        ),
    )

    @asynccontextmanager
    async def db_context():
        yield SimpleNamespace()

    monkeypatch.setattr(service, "get_db_session", db_context)
    monkeypatch.setattr(service, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        service,
        "_assignment_for_agent",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(
        service,
        "get_provider",
        lambda _code: pytest.fail("superseded cleanup must not resolve its provider"),
    )

    await service.cleanup_previous_runtime(cleanup)


def test_agent_selection_contract_never_contains_the_token() -> None:
    assert "token" not in HarnessRead.model_fields
    assert "api_token_encrypted" not in HarnessRead.model_fields
    assert "token_configured" in HarnessRead.model_fields


@pytest.mark.asyncio
async def test_only_openai_messages_harnesses_can_be_added() -> None:
    with pytest.raises(service.HarnessConflictError, match="Only OpenAI Messages"):
        await service.create_catalogue_harness(
            HarnessCatalogCreate(provider_code="codex", name="Another Codex")
        )


@pytest.mark.asyncio
async def test_disabling_catalogue_harness_returns_assignments_to_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(
        id=service._bridge_catalogue_id("codex"),
        name="Codex",
        provider_code="codex",
        driver_code="codex",
        enabled=True,
        settings={"bridge": True},
    )
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=None,
        provider_code="codex",
        lifecycle_status="ready",
    )
    fallback = AsyncMock()
    provider = _Provider("codex", [])

    monkeypatch.setattr(service, "_bridge_provider_for_id", lambda _id: provider)
    monkeypatch.setattr(service, "_bridge_harness", AsyncMock(return_value=harness))
    monkeypatch.setattr(service, "_assignments_for", AsyncMock(return_value=[assignment]))
    monkeypatch.setattr(service, "_return_assignments_to_internal", fallback)
    monkeypatch.setattr(service, "get_provider", lambda _code: provider)
    monkeypatch.setattr(service.params_service, "set", AsyncMock(return_value=True))

    result = await service.update_catalogue_harness(
        harness.id,
        HarnessCatalogUpdate(
            name=harness.name,
            enabled=False,
            settings={"bridge": True},
        ),
    )

    fallback.assert_awaited_once_with(harness, [assignment])
    assert harness.enabled is False
    assert result.assigned_agents == 0


@pytest.mark.asyncio
async def test_disabling_openai_configuration_returns_assignments_to_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(
        id=uuid4(),
        name="Shared API",
        provider_code="openai_messages",
        driver_code="openai_messages",
        enabled=True,
        settings={},
    )
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=8,
        harness_id=harness.id,
        provider_code="openai_messages",
        lifecycle_status="ready",
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    fallback = AsyncMock()
    provider = _Provider("openai_messages", [])

    monkeypatch.setattr(service, "_catalogue_harness", AsyncMock(return_value=harness))
    monkeypatch.setattr(service, "_assignments_for", AsyncMock(return_value=[assignment]))
    monkeypatch.setattr(service, "_require_unique_name", AsyncMock())
    monkeypatch.setattr(service, "_return_assignments_to_internal", fallback)
    monkeypatch.setattr(service, "get_provider", lambda _code: provider)
    monkeypatch.setattr(service, "get_db", lambda: db)

    result = await service.update_catalogue_harness(
        harness.id,
        HarnessCatalogUpdate(name=harness.name, enabled=False),
    )

    fallback.assert_awaited_once_with(harness, [assignment])
    assert harness.enabled is False
    assert result.assigned_agents == 0


@pytest.mark.asyncio
async def test_deleting_catalogue_harness_returns_assigned_agents_to_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(
        id=uuid4(),
        name="Shared API",
        provider_code="openai_messages",
        driver_code="openai_messages",
        enabled=True,
    )
    assignment = AgentHarness(
        id=uuid4(),
        agent_id=7,
        harness_id=harness.id,
        lifecycle_status="ready",
    )
    agent = cast(
        Agent,
        SimpleNamespace(
            id=7,
            code="alice",
            agent_driver="openai_messages",
            task_harness_id=harness.id,
        ),
    )
    rows = SimpleNamespace(all=lambda: [assignment])
    db = SimpleNamespace(scalars=AsyncMock(return_value=rows), commit=AsyncMock())
    destroy = AsyncMock()

    monkeypatch.setattr(service, "_catalogue_harness", AsyncMock(return_value=harness))
    monkeypatch.setattr(service, "_require_switchable", AsyncMock())
    monkeypatch.setattr(service, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        service,
        "_assignment_for_agent",
        AsyncMock(return_value=assignment),
    )
    monkeypatch.setattr(service, "_destroy_assignment", destroy)
    monkeypatch.setattr(service, "get_db", lambda: db)

    await service.delete_catalogue_harness(harness.id)

    destroy.assert_awaited_once_with(
        agent=agent,
        assignment=assignment,
        harness=harness,
    )
    assert agent.agent_driver == "internal"
    assert harness.deleted_at is not None
