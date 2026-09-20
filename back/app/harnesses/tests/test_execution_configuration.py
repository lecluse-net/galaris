"""Persistent policy admission: defaults, concurrent writers, and effective tool calls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agent import HarnessExecutionPolicy, negotiate_capabilities
from app.agent.capabilities import effective_capabilities
from app.agent.harness_port import harness_selection_port
from app.harnesses import configuration
from app.harnesses.agent_adapter import HarnessSelectionAdapter
from core.database import get_db_session


def test_capability_negotiation_cannot_invent_or_disable_guarantees():
    descriptor = negotiate_capabilities(
        {"execute", "stream", "checkpoints", "file_tools"},
        verified={"execute", "streaming", "checkpoints", "memory"},
        policy=HarnessExecutionPolicy(disabled_capabilities={"streaming"}),
    )
    assert descriptor.effective == {"execute", "checkpoints"}
    assert descriptor.unavailable == {"streaming": "disabled_by_configuration", "file_tools": "not_verified"}
    assert "checkpoints" not in descriptor.configurable
    with pytest.raises(ValidationError):
        HarnessExecutionPolicy(disabled_capabilities={"checkpoints"})
    with pytest.raises(ValueError):
        negotiate_capabilities({"invented_feature"})


@pytest.mark.asyncio
async def test_every_declared_provider_including_default_can_be_configured(db):
    from app.agent import list_driver_specs
    from app.harnesses.registry import all_providers

    configurations = await configuration.list_configurations()
    codes = {item.provider_code for item in configurations}
    assert {spec.code for spec in list_driver_specs()} <= codes
    assert {provider.code for provider in all_providers()} <= codes
    policies = {spec.code: spec.pipeline_policy for spec in list_driver_specs()}
    policies.update({provider.code: provider.pipeline_policy for provider in all_providers()})
    for item in configurations:
        assert item.pipeline_policy == policies[item.provider_code]
        assert item.model_dump(mode="json")["pipeline_policy"]["use_planner"] == policies[item.provider_code].use_planner
        assert item.revision == 0
        saved = await configuration.update_configuration(item.provider_code,
            configuration.HarnessConfigurationUpdate(expected_revision=0,
                policy=HarnessExecutionPolicy(disabled_capabilities={"execute"}, max_parallel_tasks=1)))
        assert saved.revision == 1
        assert "execute" not in saved.descriptor.effective
        assert (await configuration.describe_configuration(item.provider_code)) == saved


@pytest.mark.asyncio
async def test_pipeline_configuration_uses_the_provider_policy_over_its_transport(db, monkeypatch):
    from app.agent import DriverPipelinePolicy

    provider = SimpleNamespace(
        code="future-harness", label="Future harness", driver_code="openai_messages",
        pipeline_policy=DriverPipelinePolicy(use_planner=True, use_briefing=True,
            briefing_efforts=frozenset({"standard"})),
        capabilities=lambda: frozenset(),
    )
    monkeypatch.setattr(configuration, "all_providers", lambda: (provider,))
    result = await configuration.describe_configuration(provider.code)
    assert result.pipeline_policy.use_planner
    assert result.pipeline_policy.allows_briefing("standard")
    transport = await configuration.describe_configuration("openai_messages")
    assert not transport.pipeline_policy.use_planner
    assert not transport.pipeline_policy.use_briefing


@pytest.mark.asyncio
async def test_concurrent_configuration_updates_have_one_winner(committed_database):
    async def write(limit):
        async with get_db_session():
            return await configuration.update_configuration("internal",
                configuration.HarnessConfigurationUpdate(expected_revision=0,
                    policy=HarnessExecutionPolicy(max_parallel_tasks=limit)))

    outcomes = await asyncio.gather(write(2), write(3), return_exceptions=True)
    assert sum(isinstance(item, configuration.HarnessConfigurationConflict) for item in outcomes) == 1
    async with get_db_session():
        saved = await configuration.describe_configuration("internal")
        assert saved.revision == 1
        assert saved.descriptor.policy.max_parallel_tasks in {2, 3}


@pytest.mark.asyncio
async def test_configuration_is_rechecked_at_tool_execution(db, monkeypatch):
    from app.agent import agent_service
    from app.tools import mcp_loader, resource_effects
    from fastmcp.exceptions import ToolError

    # The agent and transport are external to this policy test; the policy repository,
    # capability negotiation, tool wrapper and execution gate are real.
    monkeypatch.setattr(agent_service, "get", AsyncMock(return_value=SimpleNamespace(id=7)))
    monkeypatch.setattr(harness_selection_port, "resolve", AsyncMock(return_value=None))
    monkeypatch.setattr(harness_selection_port, "configuration", HarnessSelectionAdapter().configuration)
    effect = AsyncMock(return_value="created")
    monkeypatch.setattr(resource_effects, "record_tool_resources", AsyncMock())
    definition = mcp_loader.McpToolDefinition(
        tool_code="files", name="test_create", description="Create", function=effect,
        required_capabilities=frozenset({"file_tools"}),
    )
    tool = mcp_loader._wrap_tool(definition, mcp_loader.McpToolContext(agent_id=7, runtime="internal"))
    assert "file_tools" in await effective_capabilities(7, "internal")
    await configuration.update_configuration("internal", configuration.HarnessConfigurationUpdate(
        expected_revision=0, policy=HarnessExecutionPolicy(disabled_capabilities={"file_tools"}),
    ))
    with pytest.raises(ToolError, match="ToolCallRejectedError"):
        await tool()
    effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_configuration_routes_require_authorization(client):
    for method, path in [("GET", "/api/harnesses/execution-configurations"),
                         ("PUT", "/api/harnesses/execution-configurations/internal")]:
        response = await client.request(method, path, json={"expected_revision": 0, "policy": {}})
        assert response.status_code in {401, 403}
