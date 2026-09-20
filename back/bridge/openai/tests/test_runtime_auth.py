from unittest.mock import AsyncMock

import pytest

from bridge.openai import codex_oauth
from bridge.openai.codex import CodexBridge


@pytest.mark.asyncio
async def test_codex_runtime_auth_returns_only_fresh_external_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_access_token = AsyncMock(return_value="fresh-access-token")
    monkeypatch.setattr(codex_oauth, "get_access_token", get_access_token)
    monkeypatch.setattr(codex_oauth, "account_id", lambda _token: "account-1")
    monkeypatch.setattr(codex_oauth, "plan_type", lambda _token: "pro")

    credential = await CodexBridge().get_runtime_credential(42)

    assert credential.auth_mode == "chatgpt"
    assert credential.secret == "fresh-access-token"
    assert credential.account_id == "account-1"
    assert credential.plan_type == "pro"
    get_access_token.assert_awaited_once_with(42)
