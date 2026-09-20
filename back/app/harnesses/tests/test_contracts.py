from uuid import uuid4
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import UniqueConstraint

from app.agent import (
    Agent,
    AgentRunEnvelopeV1,
    AgentRunIdentityV1,
    AgentRunLimitsV1,
    ResolvedExecutionTarget,
)
from app.harnesses.contracts import HarnessProvisioningRequest, HarnessProvisioningResult
from app.harnesses.models import AgentHarness, Harness
from app.harnesses import openai_provider, service
from app.harnesses.openai_client import _messages, normalize_base_url
from app.harnesses.registry import all_providers, get_provider, register_provider


def test_catalogue_is_reusable_and_runtime_is_unique_per_agent() -> None:
    constraints = {
        constraint.name
        for constraint in AgentHarness.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "agent_id" not in Harness.__table__.columns
    assert "uq_agent_harnesses_agent_id" in constraints
    assert "deployment_mode" not in Harness.__table__.columns
    assert "installation_mode" not in Harness.__table__.columns
    harness_checks = {constraint.name for constraint in Harness.__table__.constraints}
    assignment_checks = {
        constraint.name for constraint in AgentHarness.__table__.constraints
    }
    assert "ck_harnesses_openai_messages_only" in harness_checks
    assert "ck_agent_harnesses_selection_kind" in assignment_checks


def test_internal_harness_is_not_a_persisted_provider() -> None:
    provider = get_provider("openai_messages")

    assert provider.containerized is False
    assert provider.driver_code == "openai_messages"
    assert provider.max_parallel_tasks == 1
    assert "execute" in provider.capabilities()


def test_every_external_harness_provider_is_strongly_capped_at_one() -> None:
    assert all_providers()
    assert {provider.max_parallel_tasks for provider in all_providers()} == {1}


@pytest.mark.parametrize("provider_code, high", [
    ("openai_messages", False), ("codex", True), ("claude_agent", True),
    ("deepseek_harness", True), ("hermes", True),
])
def test_provider_advertises_only_implemented_dispatch_choices(provider_code, high):
    policy = get_provider(provider_code).pipeline_policy
    assert policy.uses_llm_calls is high
    assert policy.dispatch_choices() == (
        (("EXEC", "standard"), ("EXEC", "high")) if high else (("EXEC", "standard"),)
    )


def test_internal_harness_has_no_parallel_task_limit() -> None:
    assert service.internal_read(7).max_parallel_tasks is None


def test_provider_registry_rejects_an_unbounded_external_harness() -> None:
    invalid = cast(
        Any,
        SimpleNamespace(code="unbounded-test", max_parallel_tasks=None),
    )
    with pytest.raises(ValueError, match="max_parallel_tasks=1"):
        register_provider(invalid)


@pytest.mark.asyncio
async def test_openai_messages_coordinates_remain_in_the_shared_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = AsyncMock(
        return_value=HarnessProvisioningResult(
            base_url="https://shared.example/v1",
            model="shared-model",
            capabilities=frozenset({"execute", "stream"}),
        )
    )
    monkeypatch.setattr(openai_provider, "validate_configuration", validate)
    request = HarnessProvisioningRequest(
        harness_id=uuid4(),
        catalogue_harness_id=uuid4(),
        agent_id=7,
        agent_code="alice",
        name="Shared",
        base_url="https://shared.example/v1",
        model="shared-model",
        revision=1,
    )

    result = await openai_provider.provider.provision(
        cast(Agent, SimpleNamespace(id=7, code="alice")),
        request,
        token="shared-secret",
    )

    assert result.base_url is None
    assert result.model is None
    assert result.token is None


def test_openai_base_url_is_normalized_without_credentials() -> None:
    assert normalize_base_url(" https://harness.example.test/v1/ ") == (
        "https://harness.example.test/v1"
    )
    with pytest.raises(ValueError, match="credentials"):
        normalize_base_url("https://user:secret@harness.example.test/v1")


def test_envelope_projection_is_deterministic_and_keeps_resources_as_uris() -> None:
    envelope = AgentRunEnvelopeV1(
        identity=AgentRunIdentityV1(run_id=uuid4()),
        target=ResolvedExecutionTarget(
            provider_code="openai_messages",
            target_ref=f"harness:{uuid4()}",
            metadata={"model": "harness-model"},
        ),
        agent_id=7,
        agent_code="alice",
        effort="standard",
        objective="Finish the current task",
        model_id=3,
        model_code="fallback-model",
        model_name="fallback-model",
        system_instructions="Follow Galaris policy.",
        shared_context="Memory brief.",
        conversation_history=(
            {"role": "user", "content": "Earlier request"},
            {"role": "assistant", "content": "Earlier answer"},
        ),
        resource_uris=("galaris://task/123",),
        limits=AgentRunLimitsV1(),
    )

    assert _messages(envelope) == [
        {
            "role": "system",
            "content": (
                "Follow Galaris policy.\n\nMemory brief.\n\n"
                "Canonical resources:\n- galaris://task/123"
            ),
        },
        {"role": "user", "content": "Earlier request"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": "Finish the current task"},
    ]
