from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import Agent
from app.harnesses.contracts import HarnessProvisioningRequest
from app.mcp import mcp_token_service
from bridge.claude_agent import harness_provider


def _agent() -> Agent:
    return cast(
        Agent,
        SimpleNamespace(
            id=7,
            code="alice",
            task_harness_id=uuid4(),
        ),
    )


def _request() -> HarnessProvisioningRequest:
    return HarnessProvisioningRequest(
        harness_id=uuid4(),
        catalogue_harness_id=uuid4(),
        agent_id=7,
        agent_code="alice",
        name="Claude",
        base_url=None,
        model=None,
        revision=1,
    )


@pytest.mark.asyncio
async def test_retired_provider_cannot_provision_a_runtime():
    assert not {"update", "restart", "refresh"} & harness_provider.provider.capabilities()
    with pytest.raises(RuntimeError, match="runtime is retired"):
        await harness_provider.provider.provision(_agent(), _request(), token=None)


@pytest.mark.asyncio
async def test_provider_deprovision_destroys_runtime_and_revokes_system_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = AsyncMock()
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(
        harness_provider.manager,
        "list_instances",
        AsyncMock(return_value=["alice"]),
    )
    monkeypatch.setattr(harness_provider.manager, "delete_instance", delete)
    monkeypatch.setattr(mcp_token_service, "revoke_system_tokens", revoke)

    await harness_provider.provider.deprovision(_agent(), _request())

    delete.assert_awaited_once_with("alice")
    revoke.assert_awaited_once_with(7)
