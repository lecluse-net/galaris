"""Configuration-state checks used by the welcome experience."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.agent import AgentManagementScope
from app.connection.models import Connection
from app.llm import LLM, LLMProvider
from app.process import ProcessDefinition
from app.tools.models import Tool as ToolModel

from .. import services
from ..services import (
    check_llm_status,
    check_messaging_status,
    check_processes_status,
    check_skills_status,
)


@pytest.mark.asyncio
async def test_llm_status_requires_a_configured_model(db) -> None:
    provider = LLMProvider(
        name="Welcome provider",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()

    assert await check_llm_status() is False

    db.add(
        LLM(
            llm_provider_id=provider.id,
            code="welcome-model",
            llm_name="example/welcome-model",
            label="Welcome model",
        )
    )
    await db.flush()

    assert await check_llm_status() is True


@pytest.mark.asyncio
async def test_llm_status_ignores_models_from_inactive_providers(db) -> None:
    provider = LLMProvider(
        name="Inactive welcome provider",
        base_url="https://example.test/v1",
        is_active=False,
    )
    db.add(provider)
    await db.flush()
    db.add(
        LLM(
            llm_provider_id=provider.id,
            code="inactive-welcome-model",
            llm_name="example/inactive-welcome-model",
            label="Inactive welcome model",
        )
    )
    await db.flush()

    assert await check_llm_status() is False


@pytest.mark.asyncio
async def test_llm_status_ignores_resources_without_chat_capability(db) -> None:
    provider = LLMProvider(
        name="Embedding welcome provider",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    db.add(
        LLM(
            llm_provider_id=provider.id,
            code="welcome-embedding",
            llm_name="example/welcome-embedding",
            label="Welcome embedding",
            primary_capability="embedding",
            service_capabilities=["embedding"],
        )
    )
    await db.flush()

    assert await check_llm_status() is False


@pytest.mark.asyncio
async def test_messaging_status_requires_an_active_enabled_bridge_connection(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services,
        "enabled_specs",
        lambda: [
            SimpleNamespace(
                kind="telegram",
            )
        ],
    )
    title = Title(label="Welcome messenger", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code="welcome-messenger",
        first_name="Welcome",
        last_name="Messenger",
        job_title="Messaging agent",
        avatar=b"welcome",
    )
    db.add(agent)
    await db.flush()
    ordinary_tool = (
        await db.execute(select(ToolModel).where(ToolModel.code == "galaris"))
    ).scalar_one()
    messaging_tool = ToolModel(
        code="welcome-telegram",
        label="Welcome Telegram",
        description="",
        messenger_config={
            "service": "telegram",
            "settings": {},
            "param_map": {"token": "bot_token"},
        },
        connection_schema={
            "params": {
                "bot_token": {"type": "password", "required": True},
            }
        },
    )
    db.add(messaging_tool)
    await db.flush()
    db.add(
        Connection(
            agent_id=agent.id,
            tool_id=ordinary_tool.id,
            active=True,
        )
    )
    await db.flush()

    assert await check_messaging_status() is False

    messaging_connection = Connection(
        agent_id=agent.id,
        tool_id=messaging_tool.id,
        active=False,
    )
    db.add(messaging_connection)
    await db.flush()

    assert await check_messaging_status() is False

    messaging_connection.active = True
    await db.flush()

    assert await check_messaging_status() is True


@pytest.mark.asyncio
async def test_optional_capability_statuses_report_existing_configuration(db) -> None:
    assert await check_skills_status() is True

    tool = (
        await db.execute(select(ToolModel).where(ToolModel.code == "galaris"))
    ).scalar_one()
    db.add(
        ProcessDefinition(
            agent_id=None,
            tool_id=tool.id,
            engine_process_id="onboarding-configured-process",
            label="Onboarding configured process",
        )
    )
    await db.flush()

    assert await check_processes_status(agent_ids=frozenset()) is True


@pytest.mark.asyncio
async def test_overview_reports_configuration_without_edit_privileges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = import_module("app.onboarding.router")
    monkeypatch.setattr(
        router,
        "check_privilege",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        router,
        "management_scope_for",
        AsyncMock(return_value=AgentManagementScope(7, frozenset())),
    )
    checks = [
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
        AsyncMock(return_value=True),
    ]
    monkeypatch.setattr(router.services, "check_llm_status", checks[0])
    monkeypatch.setattr(router.services, "check_tools_status", checks[1])
    monkeypatch.setattr(router.services, "check_messaging_status", checks[2])
    monkeypatch.setattr(router.services, "check_agent_status", checks[3])
    monkeypatch.setattr(router.services, "check_skills_status", checks[4])
    monkeypatch.setattr(router.services, "check_processes_status", checks[5])

    overview = await router.get_onboarding_overview(
        current_user=SimpleNamespace(id=7, is_active=True),
        db=AsyncMock(),
    )

    for item in (
        overview.llm_provider,
        overview.tools,
        overview.connections,
        overview.agents,
        overview.skills,
        overview.processes,
    ):
        assert item.has_privilege is False
        assert item.has_data is True
        assert item.show is False
    assert overview.skills_access is False
    assert overview.processes_access is False
    assert router.check_privilege.await_count == 6
    for check in checks:
        check.assert_awaited_once()
