from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest

from app.agent import Agent
from app.harnesses import HarnessProvisioningRequest
from bridge.codex import harness_provider
from bridge.codex.harness_provider import CodexHarnessProvider
from core.params import params_service
from core.settings import settings as bootstrap_settings


@pytest.fixture(autouse=True)
def isolate_runtime_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness_provider.settings, "HARNESS_MANAGER_GALARIS_API_URL", "")
    monkeypatch.setattr(params_service, "get", AsyncMock(return_value=None))


def _request(*, model: str | None = None) -> HarnessProvisioningRequest:
    return HarnessProvisioningRequest(
        harness_id=uuid4(),
        catalogue_harness_id=uuid4(),
        agent_id=7,
        agent_code="alice",
        name="Alice Codex",
        base_url=None,
        model=model,
        revision=1,
    )


def _agent() -> Agent:
    return cast(Agent, SimpleNamespace(id=7, code="alice"))


@pytest.mark.asyncio
async def test_provider_provisions_private_codex_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        create_instance=AsyncMock(),
        configured=True,
        delete_tree=AsyncMock(),
        get_system_info=AsyncMock(return_value={"uid": 1000, "gid": 1000}),
        upload_file_from=AsyncMock(),
        write_text_file=AsyncMock(),
        run_action=AsyncMock(return_value="started"),
        delete_instance=AsyncMock(),
    )
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(
        bootstrap_settings, "APP_HOST", "https://galaris.example.test/"
    )
    monkeypatch.setattr(
        harness_provider.mcp_token_service,
        "rotate_system_token",
        AsyncMock(return_value="mcp-secret"),
    )
    monkeypatch.setattr(harness_provider, "_sync_skills", AsyncMock(return_value="revision-1"))
    monkeypatch.setattr(harness_provider, "_probe_runtime", AsyncMock())

    result = await CodexHarnessProvider().provision(
        _agent(),
        _request(model="obsolete-catalogue-model"),
        token=None,
    )

    manager.create_instance.assert_awaited_once_with("alice")
    manager.run_action.assert_awaited_once_with("alice", "start")
    assert result.base_url == "http://alice-agent:8787/v1"
    assert result.model == "galaris-profile"
    assert result.token is not None and result.token.startswith("galaris_codex_")
    assert {"mcp", "memory", "runtime_files"}.issubset(result.capabilities)

    written = {call.args[1]: call.args[2] for call in manager.write_text_file.await_args_list}
    assert set(written) == {
        "Dockerfile",
        "Makefile",
        "requirements.txt",
        "server.py",
        "stream_trace.py",
        "compose.yaml",
        ".env",
        "codex-home/config.toml",
        "workspace/AGENTS.md",
    }
    assert "CODEX_API_KEY" not in written[".env"]
    assert "CODEX_AUTH_URL=" not in written[".env"]
    assert "CODEX_MODEL=" not in written[".env"]
    assert 'GALARIS_LLM_URL="https://galaris.example.test/api/llm/openai"' in written[".env"]
    assert 'GALARIS_MCP_TOKEN="mcp-secret"' in written[".env"]
    assert "APP_UID: 1000" in written["compose.yaml"]
    assert 'model_provider = "galaris"' in written["codex-home/config.toml"]
    assert 'wire_api = "responses"' in written["codex-home/config.toml"]
    assert "bearer_token_env_var = \"GALARIS_MCP_TOKEN\"" in written["codex-home/config.toml"]
    assert result.metadata["model_passthrough"] is True
    assert result.metadata["galaris_extensions"] is True
    assert result.metadata["sdk_version_policy"] == "pinned"


@pytest.mark.asyncio
async def test_provider_ignores_retained_internal_token_on_reinstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        create_instance=AsyncMock(),
        configured=True,
        delete_tree=AsyncMock(),
        get_system_info=AsyncMock(return_value={"uid": 1000, "gid": 1000}),
        upload_file_from=AsyncMock(),
        write_text_file=AsyncMock(),
        run_action=AsyncMock(return_value="started"),
        delete_instance=AsyncMock(),
    )
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(
        harness_provider.mcp_token_service,
        "rotate_system_token",
        AsyncMock(return_value="mcp-secret"),
    )
    monkeypatch.setattr(harness_provider, "_sync_skills", AsyncMock(return_value="revision-1"))
    monkeypatch.setattr(harness_provider, "_probe_runtime", AsyncMock())

    result = await CodexHarnessProvider().provision(
        _agent(),
        _request(),
        token="galaris_codex_old-token",
    )

    assert result.token is not None
    assert result.token != "galaris_codex_old-token"


@pytest.mark.asyncio
async def test_provider_cleans_partial_runtime_when_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        create_instance=AsyncMock(),
        configured=True,
        delete_tree=AsyncMock(),
        get_system_info=AsyncMock(return_value={"uid": 1000, "gid": 1000}),
        upload_file_from=AsyncMock(),
        write_text_file=AsyncMock(),
        run_action=AsyncMock(side_effect=RuntimeError("build failed")),
        delete_instance=AsyncMock(),
    )
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(
        harness_provider.mcp_token_service,
        "rotate_system_token",
        AsyncMock(return_value="mcp-secret"),
    )
    monkeypatch.setattr(
        harness_provider.mcp_token_service,
        "revoke_system_tokens",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(harness_provider, "_sync_skills", AsyncMock(return_value="revision-1"))
    monkeypatch.setattr(harness_provider, "_probe_runtime", AsyncMock())

    with pytest.raises(RuntimeError, match="build failed"):
        await CodexHarnessProvider().provision(_agent(), _request(), token=None)

    manager.delete_instance.assert_awaited_once_with("alice")


@pytest.mark.asyncio
async def test_provider_deprovision_revokes_managed_mcp_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(delete_instance=AsyncMock())
    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(harness_provider.mcp_token_service, "revoke_system_tokens", revoke)

    await CodexHarnessProvider().deprovision(_agent(), _request())

    assert manager.delete_instance.await_args_list == [
        call("alice"),
        call("alice-codex"),
    ]
    revoke.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_provider_refreshes_skills_then_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(run_action=AsyncMock(return_value="restarted"))
    sync_skills = AsyncMock(return_value="revision-2")
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(harness_provider, "_sync_skills", sync_skills)

    result = await CodexHarnessProvider().run_action(_agent(), "refresh")

    assert result == "restarted"
    sync_skills.assert_awaited_once_with("alice", 7)
    manager.run_action.assert_awaited_once_with("alice", "restart")


@pytest.mark.asyncio
async def test_provider_update_migrates_existing_runtime_to_galaris_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        get_system_info=AsyncMock(return_value={"uid": 1000, "gid": 1000}),
        read_text_file=AsyncMock(return_value=(
            'CODEX_AUTH_URL="http://old-auth"\n'
            'HARNESS_API_TOKEN="service-secret"\n'
            'GALARIS_MCP_TOKEN="mcp-secret"\n'
            'CODEX_MODEL="gpt-5.4"\n'
        )),
        run_action=AsyncMock(return_value="updated"),
        write_text_file=AsyncMock(),
    )
    monkeypatch.setattr(harness_provider, "manager", manager)
    monkeypatch.setattr(
        bootstrap_settings, "APP_HOST", "https://galaris.example.test/"
    )

    result = await CodexHarnessProvider().run_action(_agent(), "update")

    assert result == "updated"
    written = {call.args[1]: call.args[2] for call in manager.write_text_file.await_args_list}
    assert "CODEX_AUTH_URL" not in written[".env"]
    assert "CODEX_MODEL" not in written[".env"]
    assert 'GALARIS_LLM_URL="https://galaris.example.test/api/llm/openai"' in written[".env"]
    assert "galaris/codex-harness:latest" in written["compose.yaml"]
    assert "no_cache: true" in written["compose.yaml"]
    assert "pull: true" in written["compose.yaml"]
    assert any(line.startswith("openai-codex==") for line in written["requirements.txt"].splitlines())
    assert "pip install --upgrade" in written["Dockerfile"]
    assert "pip freeze > requirements-resolved.txt" in written["Dockerfile"]
    manager.run_action.assert_awaited_once_with("alice", "update")
