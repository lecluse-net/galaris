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
@pytest.mark.parametrize("outcome", ["completed", "waiting_for_authorization", "waiting_for_children", "outcome_unknown", "authority_missing"])
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
            "stopped": outcome == "waiting_for_children",
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
    checkpoint = AgentRunCheckpoint(driver_code="openai_messages", runtime_run_id=identifier,
        status="waiting_for_children" if outcome == "waiting_for_children" else "interrupted",
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
    if outcome == "waiting_for_children":
        renew.assert_not_awaited()
    else:
        renew.assert_awaited_once_with(credential, request)
    assert all(call.args[0].runtime_run_id == identifier for call in save.await_args_list)
    if outcome == "waiting_for_authorization":
        assert result.authorization_requests == [authorization_id]
        close.assert_not_awaited()
    else:
        close.assert_awaited_once_with(credential)
    if outcome == "outcome_unknown":
        assert result.failure.code == "effect_unknown"
    if outcome == "waiting_for_children":
        assert result.disposition == "waiting_for_children" and result.failure is None
        assert all(call.args[0].status == "waiting_for_children" for call in save.await_args_list)


@pytest.mark.parametrize("status", ["completed", "failed", "outcome_unknown", "cancelled"])
def test_terminal_managed_checkpoints_do_not_authorize_new_execution(status):
    checkpoint = AgentRunCheckpoint(driver_code="openai_messages", runtime_run_id="a" * 64, status=status,
        data={"version": 1, "run_context": "synthetic-authority"})
    assert not RuntimeCheckpointPolicy().assess(checkpoint).resumable


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek_harness", "claude_agent", "codex", "openai_messages"])
@pytest.mark.parametrize("previous_state", ["stopped", "running", "missing", "stop_failed"])
async def test_explicit_retry_creates_new_operation_with_same_parameters_after_stopping_previous(
    monkeypatch, provider, previous_state,
):
    import json
    import app.agent
    from app.agent import prepare_run_retry
    from app.tools import facade as authority

    old_context, new_context = "synthetic-old-authority", "synthetic-new-authority"
    old_id = hashlib.sha256(old_context.encode()).hexdigest()
    new_id = hashlib.sha256(new_context.encode()).hexdigest()
    previous_run = uuid4()
    checkpoint = {"driver_code": "openai_messages", "runtime_run_id": old_id,
        "request_run_id": str(previous_run), "status": "outcome_unknown",
        "data": {"version": 1, "run_context": get_encryption_service().encrypt(old_context)},
        "result": {"prompt": "Produce a report", "result": "Previous interruption", "success": False,
            "messages": [{"type": "tool", "tool_name": "skill_read", "content": "Synthetic instructions. " * 10000},
                {"type": "tool", "tool_name": "file_create", "content": "Saved",
                "tool_arguments": {"uri": "synthetic://report"}, "tool_result": {"uri": "synthetic://report"}}]}}
    prepared = prepare_run_retry({"_agent_run_checkpoint": checkpoint})
    request = _request()
    request = replace(request, driver_code="openai_messages", agent=replace(request.agent, driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code=provider, target_ref=f"harness:{uuid4()}"), task_data=prepared)
    requests, submitted = [], []
    cancelled = False

    def respond(http_request):
        nonlocal cancelled
        requests.append((http_request.method, http_request.url.path))
        if http_request.url.path.endswith("/galaris/capabilities"):
            return httpx.Response(200, json={"authorization_protocol": "galaris.runtime-authorization/v1", "resumable_runs": True})
        if http_request.url.path.endswith(f"/galaris/runs/{old_id}"):
            assert http_request.headers["X-Galaris-Run-Context"] == old_context
            if previous_state == "missing":
                return httpx.Response(404)
            return httpx.Response(200, json={"status": "cancelled" if cancelled else "running",
                "stopped": previous_state == "stopped" or cancelled})
        if http_request.url.path.endswith(f"/galaris/runs/{old_id}/cancel"):
            if previous_state == "stop_failed":
                return httpx.Response(503)
            cancelled = True
            return httpx.Response(200, json={"accepted": True})
        if http_request.method == "POST":
            assert http_request.url.path.endswith('/galaris/runs')
            assert http_request.headers["X-Galaris-Run-Context"] == new_context
            submitted.append(json.loads(http_request.content))
            return httpx.Response(200, json={"runtime_run_id": new_id})
        assert http_request.url.path.endswith(f"/galaris/runs/{new_id}")
        return httpx.Response(200, json={"status": "completed", "stopped": True, "result": "Recorded success"})

    client = OpenAIHarnessClient(base_url="http://harness.example.test/v1", token="synthetic", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(OpenAIMessagesDriver, "_client", AsyncMock(return_value=client))
    issue, renew, revoke, close = AsyncMock(return_value=new_context), AsyncMock(), AsyncMock(return_value=None), AsyncMock()
    for name, value in [("issue_runtime_run_grant", issue), ("renew_runtime_run_grant", renew),
                        ("revoke_runtime_run_grant", revoke), ("close_runtime_run_grant", close)]:
        monkeypatch.setattr(authority, name, value)
    monkeypatch.setattr(app.agent, "aggregate_llm_run_usage", AsyncMock(return_value=None))
    if previous_state == "stop_failed":
        with pytest.raises(httpx.HTTPStatusError):
            await OpenAIMessagesDriver().run(request)
        issue.assert_not_awaited()
        assert submitted == []
        return
    result = await OpenAIMessagesDriver().run(request)
    assert result.success and result.metadata['runtime_run_id'] == new_id
    assert request.run_id != previous_run
    issue.assert_awaited_once_with(request)
    renew.assert_not_awaited()
    revoke.assert_awaited_once_with(previous_run)
    assert len(submitted) == 1
    assert submitted[0]['messages'][-1]['content'] == request.objective
    assert submitted[0]['model'] == request.model.model_name
    assert 'synthetic://report' in submitted[0]['messages'][0]['content']
    if previous_state == 'running':
        assert requests.index(('POST', f'/v1/galaris/runs/{old_id}/cancel')) < requests.index(('POST', '/v1/galaris/runs'))


@pytest.mark.asyncio
async def test_retry_does_not_start_while_previous_actor_still_runs():
    requests = []

    def respond(request):
        requests.append(request.method)
        return httpx.Response(200, json={"status": "running", "stopped": False})

    client = OpenAIHarnessClient(base_url="http://harness.example.test/v1", token="synthetic",
                                transport=httpx.MockTransport(respond))
    with pytest.raises(TimeoutError):
        await client.stop_control_run_for_retry("synthetic-run", timeout_seconds=0.02)
    assert requests == ["GET", "POST"]
