from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.llm import ManagedRuntimeCredential
from bridge.codex import runtime_credentials


@pytest.mark.asyncio
async def test_system_token_resolves_connected_chatgpt_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_credentials.mcp_token_service,
        "get_enabled_system_token_by_value",
        AsyncMock(return_value=SimpleNamespace(agent_id=7)),
    )
    agent = SimpleNamespace(id=7)
    monkeypatch.setattr(
        runtime_credentials,
        "get_agent_record",
        AsyncMock(return_value=agent),
    )
    monkeypatch.setattr(
        runtime_credentials,
        "resolve_agent_harness",
        AsyncMock(return_value=SimpleNamespace(provider_code="codex", status="ready")),
    )
    expected = ManagedRuntimeCredential(
        auth_mode="chatgpt",
        secret="short-lived",
        account_id="account-1",
    )
    resolve = AsyncMock(return_value=expected)
    monkeypatch.setattr(runtime_credentials, "get_managed_runtime_credential", resolve)

    result = await runtime_credentials.resolve_for_system_token("mcp-secret")

    assert result == expected
    resolve.assert_awaited_once_with("openai-codex")


@pytest.mark.asyncio
async def test_runtime_credential_rejects_non_system_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_credentials.mcp_token_service,
        "get_enabled_system_token_by_value",
        AsyncMock(return_value=None),
    )

    with pytest.raises(PermissionError, match="invalid"):
        await runtime_credentials.resolve_for_system_token("ordinary-token")


@pytest.mark.asyncio
async def test_runtime_credential_rejects_agent_using_another_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_credentials.mcp_token_service,
        "get_enabled_system_token_by_value",
        AsyncMock(return_value=SimpleNamespace(agent_id=7)),
    )
    monkeypatch.setattr(
        runtime_credentials,
        "get_agent_record",
        AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        runtime_credentials,
        "resolve_agent_harness",
        AsyncMock(return_value=SimpleNamespace(provider_code="hermes", status="ready")),
    )

    with pytest.raises(PermissionError, match="not assigned"):
        await runtime_credentials.resolve_for_system_token("mcp-secret")
