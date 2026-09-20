from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.contracts import AgentModelConfigurationError
from app.agent.model_resolver import (
    has_agent_profile_model,
    resolve_agent_profile_model,
    resolve_conversation_model,
    resolve_model,
)
from app.llm import llm_service, model_usages


def _llm(identifier: int, code: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        code=code,
        llm_name=f"model-{code}",
        label=code,
    )


@pytest.mark.asyncio
async def test_orchestration_model_uses_the_single_effective_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = _llm(12, "dispatcher")
    resolver = AsyncMock(return_value=dispatcher)
    monkeypatch.setattr(llm_service, "get_profile_llm", resolver)
    agent = SimpleNamespace(profile_id=5)

    resolved = await resolve_agent_profile_model(agent, model_usages.DISPATCHER)

    assert resolved is dispatcher
    resolver.assert_awaited_once_with(model_usages.DISPATCHER, agent=agent)


@pytest.mark.asyncio
async def test_profile_model_availability_has_no_second_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(side_effect=[_llm(1, "briefing"), None])
    monkeypatch.setattr(llm_service, "get_profile_llm", resolver)
    agent = SimpleNamespace(profile_id=5)

    assert await has_agent_profile_model(agent, model_usages.BRIEFING)
    assert not await has_agent_profile_model(agent, model_usages.BRIEFING)


@pytest.mark.asyncio
async def test_high_model_is_resolved_from_the_effective_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    high = _llm(2, "high")
    profile_model = AsyncMock(return_value=high)
    monkeypatch.setattr(llm_service, "get_profile_llm", profile_model)
    standard = AsyncMock()
    monkeypatch.setattr(llm_service, "get_llm_for_agent", standard)
    reasoning = AsyncMock(return_value="xhigh")
    monkeypatch.setattr(llm_service, "get_profile_reasoning_effort", reasoning)

    agent = SimpleNamespace(code="alice", profile_id=5)
    resolved = await resolve_model(agent, "high")

    assert resolved.id == 2
    assert resolved.fallback_used is False
    assert resolved.reasoning_effort == "xhigh"
    profile_model.assert_awaited_once_with(model_usages.EXECUTOR_HIGH, agent=agent)
    standard.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_reasoning_override_wins_over_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard = _llm(1, "standard")
    monkeypatch.setattr(
        llm_service,
        "get_llm_for_agent",
        AsyncMock(return_value=standard),
    )
    profile_reasoning = AsyncMock(return_value="low")
    monkeypatch.setattr(
        llm_service,
        "get_profile_reasoning_effort",
        profile_reasoning,
    )

    resolved = await resolve_model(
        SimpleNamespace(code="alice"),
        "standard",
        reasoning_effort_override="xhigh",
    )

    assert resolved.reasoning_effort == "xhigh"
    profile_reasoning.assert_not_awaited()


@pytest.mark.asyncio
async def test_high_falls_back_only_to_standard_of_the_same_effective_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard = _llm(1, "standard")
    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=None))
    standard_for_agent = AsyncMock(return_value=standard)
    monkeypatch.setattr(llm_service, "get_llm_for_agent", standard_for_agent)
    reasoning = AsyncMock(return_value="low")
    monkeypatch.setattr(llm_service, "get_profile_reasoning_effort", reasoning)
    agent = SimpleNamespace(code="alice", profile_id=5)

    resolved = await resolve_model(agent, "high")

    assert resolved.id == 1
    assert resolved.fallback_used is True
    assert resolved.reasoning_effort == "low"
    reasoning.assert_awaited_once_with(model_usages.EXECUTOR, agent=agent)
    standard_for_agent.assert_awaited_once_with(agent)


@pytest.mark.asyncio
async def test_missing_standard_model_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service, "get_llm_for_agent", AsyncMock(return_value=None))

    with pytest.raises(AgentModelConfigurationError, match="No executor LLM"):
        await resolve_model(SimpleNamespace(code="alice"), "standard")


@pytest.mark.asyncio
async def test_conversation_model_comes_only_from_the_effective_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _llm(9, "conversation")
    resolver = AsyncMock(return_value=conversation)
    monkeypatch.setattr(llm_service, "get_profile_llm", resolver)
    reasoning = AsyncMock(return_value="low")
    monkeypatch.setattr(llm_service, "get_profile_reasoning_effort", reasoning)
    agent = SimpleNamespace(code="alice", profile_id=None)

    resolved = await resolve_conversation_model(agent, "fr")

    assert resolved.id == 9
    assert resolved.fallback_used is False
    assert resolved.reasoning_effort == "low"
    resolver.assert_awaited_once_with(model_usages.CONVERSATION, agent=agent)


@pytest.mark.asyncio
async def test_conversation_model_does_not_fall_back_to_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=None))
    executor = AsyncMock()
    monkeypatch.setattr(llm_service, "get_llm_for_agent", executor)

    with pytest.raises(AgentModelConfigurationError, match="No executor LLM"):
        await resolve_conversation_model(SimpleNamespace(code="alice"), "en")

    executor.assert_not_awaited()
