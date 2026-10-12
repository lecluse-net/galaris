"""Managed recovery observes one existing actor across all network providers."""

import hashlib
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.agent import AgentRunCheckpoint, AgentRunControl, ResolvedExecutionTarget
from app.agent.tests.test_driver_testkit import _request
from app.harnesses.checkpoint_policy import RuntimeCheckpointPolicy
from app.harnesses.driver import OpenAIMessagesDriver
from app.harnesses.openai_client import OpenAIHarnessClient
from core.util import get_encryption_service


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek_harness", "claude_agent", "codex", "openai_messages"])
@pytest.mark.parametrize("outcome", ["completed", "waiting_for_authorization", "outcome_unknown", "authority_missing"])
async def test_interrupted_checkpoint_observes_the_same_actor_without_restarting(monkeypatch, provider, outcome):
    from app.tools import facade as authority

    credential = "synthetic-runtime-authority"
    identifier = hashlib.sha256(credential.encode()).hexdigest()
    authorization_id = uuid4()
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/galaris/capabilities"):
            return httpx.Response(200, json={"authorization_protocol": "galaris.runtime-authorization/v1", "resumable_runs": True})
        assert request.method == "GET" and request.url.path.endswith(f"/galaris/runs/{identifier}")
        assert request.headers["X-Galaris-Run-Context"] == credential
        return httpx.Response(200, json={"runtime_run_id": identifier, "status": outcome,
            "result": "recorded outcome", "authorization_requests": [str(authorization_id)] if outcome == "waiting_for_authorization" else []})

    client = OpenAIHarnessClient(base_url="http://harness.example.test/v1", token="synthetic",
                                transport=httpx.MockTransport(respond))
    monkeypatch.setattr(OpenAIMessagesDriver, "_client", AsyncMock(return_value=client))
    issue, renew, close = AsyncMock(), AsyncMock(return_value=credential), AsyncMock()
    if outcome == "authority_missing":
        renew.side_effect = PermissionError("The suspended runtime authority is missing")
    monkeypatch.setattr(authority, "issue_runtime_run_grant", issue)
    monkeypatch.setattr(authority, "renew_runtime_run_grant", renew)
    monkeypatch.setattr(authority, "close_runtime_run_grant", close)
    # Accounting is a separate database boundary; no model request is made here.
    import app.agent
    monkeypatch.setattr(app.agent, "aggregate_llm_run_usage", AsyncMock(return_value=None))
    checkpoint = AgentRunCheckpoint(driver_code="openai_messages", runtime_run_id=identifier, status="interrupted",
        data={"version": 1, "run_context": get_encryption_service().encrypt(credential), "cursor": {"messages": 0, "text": 0}})
    request = _request()
    save = AsyncMock()
    request = replace(request, driver_code="openai_messages", agent=replace(request.agent, driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code=provider, target_ref=f"harness:{uuid4()}"),
        resume_checkpoint=checkpoint, control=AgentRunControl(save_checkpoint=save))

    assert RuntimeCheckpointPolicy().assess(checkpoint).resumable
    if outcome == "authority_missing":
        with pytest.raises(PermissionError, match="authority is missing"):
            await OpenAIMessagesDriver().run(request)
        assert requests == [("GET", "/v1/galaris/capabilities")]
        issue.assert_not_awaited()
        save.assert_not_awaited()
        close.assert_not_awaited()
        return
    result = await OpenAIMessagesDriver().run(request)

    assert result.success is (outcome == "completed")
    assert result.metadata["runtime_run_id"] == identifier
    assert result.metadata["runtime_status"] == outcome
    assert all(method == "GET" for method, _ in requests)
    assert len(requests) == 2
    issue.assert_not_awaited()
    renew.assert_awaited_once_with(credential, request)
    assert all(call.args[0].runtime_run_id == identifier for call in save.await_args_list)
    if outcome == "waiting_for_authorization":
        assert result.authorization_requests == [authorization_id]
        close.assert_not_awaited()
    else:
        close.assert_awaited_once_with(credential)
    if outcome == "outcome_unknown":
        assert result.failure.code == "effect_unknown"


@pytest.mark.parametrize("status", ["completed", "failed", "outcome_unknown", "cancelled"])
def test_terminal_managed_checkpoints_do_not_authorize_new_execution(status):
    checkpoint = AgentRunCheckpoint(driver_code="openai_messages", runtime_run_id="a" * 64, status=status,
        data={"version": 1, "run_context": "synthetic-authority"})
    assert not RuntimeCheckpointPolicy().assess(checkpoint).resumable
