from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import app.harnesses as harnesses_module
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


def test_runtime_compose_does_not_force_the_deployment_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "HARNESS_MANAGER_DOCKER_NETWORK",
        "galaris_executor_net",
    )

    compose = harness_provider._compose("alice", uid=1000, gid=1000)

    assert "alice-agent" in compose
    assert "galaris_executor_net" not in compose
    assert "networks:" not in compose
    assert "./data:/data" in compose
    assert "8642/health" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "galaris/claude-agent-harness:latest" in compose
    assert "no_cache: true" in compose
    assert "pull: true" in compose
    requirements = (
        harness_provider._DEFAULT_AGENT_DIR / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert any(line.startswith("claude-agent-sdk==") for line in requirements.splitlines())
    dockerfile = (harness_provider._DEFAULT_AGENT_DIR / "Dockerfile").read_text()
    assert "pip install --upgrade" in dockerfile
    assert "pip freeze > requirements-resolved.txt" in dockerfile


@pytest.mark.asyncio
async def test_provider_provisions_runtime_with_model_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock()
    action = AsyncMock(return_value="started")
    monkeypatch.setattr(
        harness_provider.manager,
        "list_instances",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        type(harness_provider.manager),
        "configured",
        property(lambda _self: True),
    )
    monkeypatch.setattr(harness_provider.manager, "create_instance", create)
    monkeypatch.setattr(harness_provider.manager, "run_action", action)
    monkeypatch.setattr(
        harness_provider,
        "_sync_runtime",
        AsyncMock(return_value="skill-revision"),
    )

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def list_models(self) -> list[str]:
            return ["claude-agent"]

    monkeypatch.setattr(harnesses_module, "OpenAIHarnessClient", Client)

    result = await harness_provider.provider.provision(
        _agent(),
        _request(),
        token="retained-token",
    )

    create.assert_awaited_once_with("alice")
    action.assert_awaited_once_with("alice", "start")
    assert result.base_url == "http://alice-agent:8642/v1"
    assert result.model == "claude-agent"
    assert result.metadata["model_passthrough"] is True
    assert result.metadata["galaris_extensions"] is True
    assert result.metadata["model_gateway"] == "galaris-anthropic"
    assert result.metadata["runtime"] == "claude-agent-sdk"
    assert result.metadata["sdk_version_policy"] == "pinned"
    assert result.token == "retained-token"


@pytest.mark.asyncio
async def test_template_projects_the_stream_trace_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = AsyncMock()
    monkeypatch.setattr(harness_provider.manager, "upload_file_from", upload)

    await harness_provider._sync_template("alice")

    assert any(
        call.args[1:] == (
            "stream_trace.py",
            harness_provider.Path(harness_provider.__file__).with_name("stream_trace.py"),
        )
        for call in upload.await_args_list
    )


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
