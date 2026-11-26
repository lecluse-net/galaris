"""Exercise the bundled Claude CLI, real gateway and durable inference journal."""

import asyncio
import json
import socket
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy import select

from app.agent import Agent, Title, executor_service
from app.agent.execution_errors import HarnessProtocolError
from app.agent.facade import build_run_request, cancel, stream
from app.connection import Connection
from app.connection.models import ConnectionFunctionState
from app.conversation import (
    ConversationRound, ConversationRoundAttempt, ConversationRoundMessage, ConversationTaskLink,
)
from app.conversation.service import admit_message, build_turn, claim_next_round, complete_round
from app.document.data.models import Dataset
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.harness.tests.test_ssh_checkpoint_recovery import ssh_with_lost_acknowledgement  # noqa: F401 - shared SSH fixture
from app.llm.embedded_runtime import EmbeddedRoundInference, EmbeddedTaskInference
from app.llm.models import LLMCall, LLMCallEvent
from app.llm.profile_models import LlmProfile
from app.messenger import Message, MessengerUser, Room, RoomUser
from app.services import ServiceModel
from app.services.authorization_models import ActionAuthorization
from app.services.facade import answer_action, wake_authorization_context
from app.task import Task, TaskStatus
from app.task import runner, scheduler, task_service
from app.task.models import TaskAttempt
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session, middleware
from core.params import runtime_settings
from core.user.auth_service import create_access_token_for_user
from core.user.models import User
from main import app
from tests.test_embedded_claude_chat_effects import _gateway, _http_server
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"])
@pytest.mark.parametrize("streaming", [False, True], ids=["json", "sse"])
async def test_agent_openai_completion_keeps_the_selected_harness_and_exact_lineage(
    runtime, committed_database, monkeypatch, tmp_path, driver, streaming,
):
    from app.llm import profile_service

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    receipts = []
    answer = "Synthetic completion confirmed."
    decision = json.dumps({"route": "EXEC", "effort": "standard", "language": "en", "organization": "direct"})
    mode.update(concurrent=True, structured=lambda _body: len(requests) == 1, outputs=[decision, answer],
                chat_response_ids=receipts)

    user = User(email=f"agent-api-{uuid4().hex}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic API profile", text_low_llm_id=model.id, text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    role = await db.scalar(select(Role).where(Role.code == "admin"))
    title = await db.scalar(select(Title.id).limit(1))
    assert role is not None and title is not None
    agent = Agent(code=f"agent-api-{uuid4().hex}", first_name="Synthetic", last_name="API",
                  user_id=user.id, title_id=title, profile_id=profile.id, agent_driver=driver)
    db.add_all([agent, Assignment(user_id=user.id, role_id=role.id, is_default=True)])
    await db.commit()
    assert await profile_service.set_current_profile_id(profile.id)
    access_token = await create_access_token_for_user(user, db, role_id=role.id)
    await db.commit()
    conversation_id = f"synthetic-api-{uuid4().hex}"
    question = "Repeat the synthetic reference FERN-204."

    scheduler.start()
    try:
        async with _http_server(app) as origin, AsyncClient(base_url=origin, timeout=30, trust_env=False) as client:
            monkeypatch.setattr(claude_driver, "CLAUDE_GATEWAY", f"{origin}/api/llm/anthropic")
            response = await client.post(
                "/api/agent/openai/chat/completions",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"model": agent.code, "conversation_id": conversation_id, "stream": streaming,
                      "messages": [{"role": "user", "content": question}]},
            )
    finally:
        await scheduler.stop()

    assert response.status_code == 200
    if streaming:
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
        assert frames[-1] == "[DONE]" and frames.count("[DONE]") == 1
        chunks = [json.loads(frame) for frame in frames[:-1]]
        assert len({chunk["id"] for chunk in chunks}) == 1
        assert all(chunk["model"] == agent.code for chunk in chunks)
        assert chunks[0]["conversation_id"] == conversation_id
        choices = [chunk["choices"][0] for chunk in chunks]
        assert choices[0]["delta"]["role"] == "assistant"
        assert "".join(choice["delta"].get("content", "") for choice in choices) == answer
        assert [choice["finish_reason"] for choice in choices if choice["finish_reason"] is not None] == ["stop"]
        assert choices[-1]["finish_reason"] == "stop"
    else:
        payload = response.json()
        assert payload["model"] == agent.code and payload["conversation_id"] == conversation_id
        [choice] = payload["choices"]
        assert choice["message"]["role"] == "assistant" and choice["message"]["content"] == answer
        assert choice["finish_reason"] == "stop"

    [task] = (await db.scalars(select(Task).where(Task.agent_id == agent.id))).all()
    assert task.status == TaskStatus.SUCCESS and task.requester_user_id == user.id
    assert task.data["conversation_id"] == f"human:{user.id}:{conversation_id}"
    result = task.get_execution_result()
    assert result is not None and result.success and result.result == answer
    assert result.metadata["driver_code"] == driver
    calls = (await db.scalars(select(LLMCall).where(LLMCall.llm_id == model.id).order_by(LLMCall.started_at))).all()
    assert len(requests) == len(receipts) == len(calls) == 2
    assert [call.upstream_request_id for call in calls] == receipts
    assert [call.purpose for call in calls] == ["agent.dispatch", "agent.exec"]
    assert all(call.task_id == task.id and call.agent_id == agent.id and call.status == "completed" for call in calls)
    assert all(question in json.dumps(request["messages"]) for request in requests)
    attempts = (await db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task.id)
                                  .order_by(TaskAttempt.attempt_number))).all()
    # The audit stores the state at claim, before dispatch or execution advances it.
    assert [attempt.phase for attempt in attempts] == [TaskStatus.CREATE.value, TaskStatus.DISPATCH.value]
    assert [call.task_attempt_id for call in calls] == [attempt.id for attempt in attempts]
    assert str(calls[1].agent_run_id) == result.metadata["run_id"]
    if driver == "claude_embedded":
        assert calls[1].correlation_ref == f"task:{task.id}:attempt:{calls[1].task_attempt_id}"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("content", "finish_reason"), [
    pytest.param("Synthetic truncated answer", "length", id="truncated"),
    pytest.param("", "stop", id="empty"),
])
async def test_claude_does_not_report_an_unusable_provider_answer_as_success(tmp_path, content, finish_reason):
    from fastapi import FastAPI
    from fastapi.responses import Response

    from app.harness.claude_runtime import stream_turn
    from app.llm.anthropic_service import AnthropicStreamTranslator

    provider = FastAPI()
    model = "synthetic-terminal"

    @provider.post("/v1/messages")
    async def complete() -> Response:
        translator = AnthropicStreamTranslator(model, input_tokens=7)
        events = [translator.start()]
        events.extend(translator.feed({"choices": [{"delta": {"content": content}, "finish_reason": finish_reason}],
                                       "usage": {"completion_tokens": 4 if content else 0}}))
        events.extend(translator.finish())
        return Response("".join(events), media_type="text/event-stream")

    async with _http_server(provider) as origin, asyncio.timeout(25):
        events = [event async for event in stream_turn(gateway=origin, credential="synthetic-key", model=model,
                  prompt="Reply with a complete synthetic answer.", system_prompt="You are a test agent.",
                  workspace_root=tmp_path)]
    [result] = [event.result for event in events if event.result is not None]
    assert events[-1].result is result
    assert not result.success and result.failure is not None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 2], ids=["exhausted", "retry-allowed"])
@pytest.mark.parametrize("first_error", [
    pytest.param((503, {"message": "Synthetic transient outage"}), id="sdk-retry"),
    pytest.param((400, {"message": "Synthetic provider rejects stream options",
                        "code": "unsupported_parameter", "param": "stream_options"}), id="gateway-retry"),
    pytest.param((401, {"message": "Synthetic provider token expired"}), id="credential-refresh"),
    pytest.param(None, id="concurrent-admissions"),
])
async def test_claude_retry_cannot_exceed_the_physical_request_budget(
    runtime, committed_database, monkeypatch, tmp_path, limit, first_error,
):
    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", limit)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    mode.update(concurrent=True, first_error=first_error)
    refreshes = []
    if first_error is not None and first_error[0] == 401:
        from app.llm import proxy_service

        async def prepare_request(provider_id, connection, body, *, force_stream, force_refresh=False):
            refreshes.append(force_refresh)
            return SimpleNamespace(endpoint="https://provider.test/v1/chat/completions", body=body,
                                   headers={"Authorization": "Bearer synthetic"})

        transport = SimpleNamespace(stream_only=False, prepare_request=prepare_request,
                                    create_stream_adapter=lambda model: None)
        monkeypatch.setattr(proxy_service, "chat_transport_for", lambda connection: transport)
    user = User(email=f"claude-budget-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic request budget", text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    agent = Agent(code=f"claude-budget-{uuid4().hex}", user_id=user.id, first_name="Claude", last_name="Budget",
                  title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id,
                  agent_driver="claude_embedded")
    db.add(agent)
    await db.flush()
    lease = uuid4()
    task = Task(label="Synthetic request-budget task", objective="Answer one synthetic question without tools.",
                agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="standard",
                lease_token=lease, lease_owner="claude-budget-test", attempt_count=1,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(task)
    await db.flush()
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", worker_id="claude-budget-test",
                       lease_token=lease))
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    request = await build_run_request(task)
    assert request.limits.request_limit == limit
    await db.commit()
    assert request.attempt_id is not None

    if first_error is None:
        origin = EmbeddedTaskInference(
            agent_id=agent.id, task_id=task.id, attempt_id=request.attempt_id, run_id=request.run_id,
            model_id=model.id, model_code=model.code, request_limit=limit,
            executor_profile_effort=request.model.executor_profile_effort,
        )
        body = {"model": model.code, "max_tokens": 16, "stream": True,
                "messages": [{"role": "user", "content": "Synthetic concurrent call"}]}
        async with _gateway(monkeypatch), AsyncClient() as client, asyncio.timeout(25):
            replies = await asyncio.gather(*(client.post(f"{claude_driver.CLAUDE_GATEWAY}/v1/messages",
                headers={"x-api-key": origin.credential()}, json=body) for _ in range(2)))
        assert sorted(reply.status_code for reply in replies) == ([200, 429] if limit == 1 else [200, 200])
        for reply in replies:
            if reply.status_code == 429:
                assert reply.headers["x-should-retry"] == "false"
                assert "model request limit" in reply.json()["error"]["message"]
        expected_statuses = ["completed"] * limit
    else:
        async with _gateway(monkeypatch), asyncio.timeout(25):
            events = [event async for event in stream(request)]
        [result] = [event.result for event in events if event.result is not None]
        assert result.success is (limit == 2)
        if limit == 1:
            assert result.failure is not None and result.failure.code == "quota" and result.failure.retry == "never"
        expected_statuses = ["error", "completed"] if limit == 2 else ["error"]

    calls = (await db.scalars(select(LLMCall).where(LLMCall.llm_id == model.id).order_by(LLMCall.started_at))).all()
    assert len(requests) == len(calls) == limit
    assert all(call.task_id == task.id and call.task_attempt_id == request.attempt_id
               and call.agent_run_id == request.run_id for call in calls)
    assert [call.status for call in calls] == expected_statuses
    if first_error is None:
        assert {reply.headers["x-galaris-llm-call-id"] for reply in replies if reply.status_code == 200} == {
            str(call.id) for call in calls
        }

    if first_error is not None and first_error[0] == 400:
        assert "stream_options" in requests[0]
        if limit == 2:
            assert "stream_options" not in requests[1]
    if first_error is not None and first_error[0] == 401:
        assert refreshes == [False, True]
    if limit == 1 and first_error is not None and first_error[0] == 503:
        from app.agent.facade import _apply_run_result, prepare_run_retry

        monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 2)
        resumed, resumed_result = request, result
        async with _gateway(monkeypatch), asyncio.timeout(25):
            for number in (2, 3):
                await db.refresh(task)
                if number == 3:
                    _apply_run_result(task, resumed_result, resumed)
                    assert "_agent_run_identity" not in task.data
                    task.data = prepare_run_retry(task.data)
                task.lease_token = uuid4()
                task.lease_owner = "replacement-worker"
                task.attempt_count = number
                db.add(TaskAttempt(task_id=task.id, attempt_number=number, phase="EXEC", worker_id=task.lease_owner,
                                   lease_token=task.lease_token))
                await db.commit()
                previous_attempt = resumed.attempt_id
                resumed = await build_run_request(task)
                await db.commit()
                assert resumed.attempt_id != previous_attempt and resumed.run_id == request.run_id
                resumed_events = [event async for event in stream(resumed)]
                [resumed_result] = [event.result for event in resumed_events if event.result is not None]
                assert len(requests) == 1
                assert resumed_result.failure is not None and resumed_result.failure.code == "quota"
                assert resumed.limits.request_limit == 1
        assert (await db.scalars(select(LLMCall.id).where(LLMCall.llm_id == model.id))).all() == [calls[0].id]


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize("recovery", [
    "receipt", "reported-receipt", "reported-batch", "quiet-recovery", "running-start", "running-exec", "missing",
    "wrong-operation", "changed-console", "revoked-tool", "revoked-during-lookup",
])
async def test_embedded_reconciles_a_lost_console_receipt_before_another_model_call(
    runtime, committed_database, monkeypatch, tmp_path, recovery, driver, ssh_with_lost_acknowledgement,
):
    from app.agent import HarnessCheckpointError, has_resumable_run_checkpoint
    from app.connection import connection_service
    from app.console import ConsoleResult, SshExecutionTransport

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    workspace = tmp_path / "claude"
    workspace.mkdir()
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    tool_name = "console_start" if recovery == "running-start" else "console_exec"
    reported = recovery in {"reported-receipt", "reported-batch"}
    real_ssh = reported or recovery == "receipt"
    ssh = ssh_with_lost_acknowledgement
    user = User(email=f"console-recovery-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic Console recovery", text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    agent = Agent(code=f"console-recovery-{uuid4().hex}", user_id=user.id, first_name="Synthetic", last_name="Console",
                  title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id, agent_driver=driver)
    db.add(agent)
    await db.flush()
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "console"))
    connection = Connection(agent_id=agent.id, service_id=service.id, active=True)
    db.add(connection)
    await db.flush()
    params = {
        "host": "console.example.test", "username": "synthetic",
        "private_key": "synthetic", "known_host_key": "synthetic-pinned-key",
    }
    if real_ssh:
        params = {"host": ssh.config.host, "port": str(ssh.config.port), "username": ssh.config.username,
                  "private_key": ssh.config.private_key.get_secret_value(), "known_host_key": ssh.config.known_host_key}
    await connection_service.set_params_bulk(connection.id, params)
    policy = ConnectionFunctionState(connection_id=connection.id, function_name=tool_name,
                                     state="enabled", enabled=True)
    alternate_tool = "console_exec" if tool_name == "console_start" else "console_start"
    alternate_policy = ConnectionFunctionState(connection_id=connection.id, function_name=alternate_tool,
                                               state="enabled", enabled=True)
    lease = uuid4()
    task = Task(label="Synthetic lost Console receipt", objective="Run the synthetic Console command once.",
                agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="standard",
                lease_token=lease, lease_owner="initial-console-worker", attempt_count=1,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add_all([policy, alternate_policy, task])
    await db.flush()
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC",
                       worker_id=task.lease_owner, lease_token=lease))
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    request = await build_run_request(task)
    await db.commit()

    command = "printf x >> effect; printf 'Exact synthetic receipt'" if real_ssh else "printf synthetic"
    executions, lookups = [], []
    exec_operation, recover_operation = SshExecutionTransport.exec_operation, SshExecutionTransport.recover_operation
    lost, rechecking, proposed = False, False, False
    acknowledgement = asyncio.Event()

    async def save_if_worker_alive(checkpoint):
        if not lost:
            await request.save_checkpoint(checkpoint)

    async def lose_receipt(self, sent_command, *, operation_id, task_id, **kwargs):
        assert sent_command == command and task_id == task.id
        executions.append(operation_id)
        if real_ssh and not rechecking:
            if reported:
                return await exec_operation(self, sent_command, operation_id=operation_id, task_id=task_id, **kwargs)
            with pytest.raises(RuntimeError, match="no acknowledged operation receipt"):
                await exec_operation(self, sent_command, operation_id=operation_id, task_id=task_id, **kwargs)
        if not rechecking:
            acknowledgement.set()
            await asyncio.Future()
        return ConsoleResult(run_id=operation_id, status="completed", exit_code=0, stdout="Duplicated synthetic operation")

    async def find_receipt(self, operation_id, *, allow_running=False):
        assert allow_running is (tool_name == "console_start") and self.config.host == params["host"]
        lookups.append(operation_id)
        if real_ssh:
            return await recover_operation(self, operation_id, allow_running=allow_running)
        if recovery == "revoked-during-lookup":
            async with get_db_session():
                await connection_service.set_connection_function_state(connection.id, tool_name, "disabled")
            return ConsoleResult(run_id=operation_id, status="completed", exit_code=0, stdout="Revoked synthetic receipt")
        if recovery in {"running-start", "running-exec"}:
            return ConsoleResult(run_id=operation_id, status="running", stdout="Exact synthetic receipt")
        if recovery == "quiet-recovery":
            return ConsoleResult(run_id=operation_id, status="completed", exit_code=0, stdout="Exact synthetic receipt")
        if recovery == "wrong-operation":
            return ConsoleResult(run_id=uuid4(), status="completed", exit_code=0, stdout="Unrelated synthetic receipt")
        return None

    def choose_tools(body):
        nonlocal proposed
        if proposed:
            return []
        proposed = True
        prefix = "mcp__galaris__" if driver == "claude_embedded" else ""
        arguments = {"command": command}
        if real_ssh:
            arguments["cwd"] = str(ssh.work)
        if rechecking:
            if recovery == "quiet-recovery":
                return []
            return [
                ("console-duplicate-exec", f"{prefix}console_exec",
                 {**arguments, "cwd": arguments.get("cwd", "."), "timeout_s": 15}),
                ("console-duplicate-start", f"{prefix}console_start", arguments),
            ]
        calls = [("synthetic-console-command", f"{prefix}{tool_name}", arguments)]
        if recovery == "reported-batch":
            calls.append(("same-batch-console-command", f"{prefix}{alternate_tool}", arguments))
        return calls

    monkeypatch.setattr(SshExecutionTransport, "exec_operation", lose_receipt)
    monkeypatch.setattr(SshExecutionTransport, "recover_operation", find_receipt)
    if real_ssh:
        async def working_helper(transport):
            transport._helper_version = "2"
            return str(ssh.helper)
        monkeypatch.setattr(SshExecutionTransport, "_working_helper", working_helper)
    else:
        monkeypatch.setattr(SshExecutionTransport, "start", lose_receipt)
    receipts = []
    mode.update(concurrent=True, tool_calls_for=choose_tools, chat_response_ids=receipts)
    can_resume = real_ssh or recovery in {"quiet-recovery", "running-start"}
    async with _gateway(monkeypatch), asyncio.timeout(30):
        async def interruptible_run():
            interrupted = replace(request, control=replace(request.control, save_checkpoint=save_if_worker_alive))
            return [event async for event in stream(interrupted)]

        if reported:
            events = await interruptible_run()
            assert len(requests) == 1
            assert not events[-1].result.success
            assert events[-1].result.failure.code == "effect_unknown"
            assert events[-1].result.failure.retry == "reconcile"
        else:
            worker = asyncio.create_task(interruptible_run())
            try:
                await acknowledgement.wait()
            finally:
                lost = True
                worker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await worker
        [operation_id] = executions
        await db.refresh(task)
        assert has_resumable_run_checkpoint(task)
        checkpoint = task.data["_agent_run_checkpoint"]["data"]["effects"]
        assert checkpoint[0]["operation_id"] == str(operation_id)
        assert checkpoint[0]["status"] == ("outcome_unknown" if reported else "started")

        if real_ssh:
            probe = ssh.transport()
            try:
                async with asyncio.timeout(5):
                    while await recover_operation(probe, operation_id) is None:
                        await asyncio.sleep(0.02)
            finally:
                await probe.close()
        if recovery == "changed-console":
            await connection_service.set_params_bulk(connection.id, {"host": "replacement.example.test"})
        if recovery == "revoked-tool":
            policy.state, policy.enabled = "disabled", False
        task.lease_token = uuid4()
        task.lease_owner = "new-console-worker"
        task.attempt_count = 2
        db.add(TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC",
                           worker_id=task.lease_owner, lease_token=task.lease_token))
        await db.commit()
        await db.refresh(agent, attribute_names=["title"])
        resumed = await build_run_request(task)
        assert resumed.run_id == request.run_id and resumed.attempt_id != request.attempt_id
        await db.commit()
        previous_calls = len(requests)
        rechecking, proposed = True, False
        if can_resume:
            events = [event async for event in stream(resumed)]
            [result] = [event.result for event in events if event.result is not None]
            assert result.success
        else:
            with pytest.raises(HarnessCheckpointError) as blocked:
                async with aclosing(stream(resumed)) as events:
                    async for _ in events:
                        pytest.fail("An unresolved Console effect emitted an execution event")
            assert blocked.value.failure.code == "effect_unknown" and blocked.value.failure.retry == "never"

    assert executions == [operation_id]
    if real_ssh:
        assert ssh.operations == [operation_id]
        assert (ssh.work / "effect").read_text() == "x"
    assert lookups == ([] if recovery in {"changed-console", "revoked-tool"} else [operation_id])
    if can_resume:
        assert "Exact synthetic receipt" in json.dumps(requests[previous_calls]["messages"])
        if driver == "claude_embedded" and recovery != "quiet-recovery":
            assert json.dumps(requests[-1]["messages"]).count("already recorded") == 2
        await db.refresh(task)
        [stored] = task.data["_agent_run_checkpoint"]["data"]["effects"]
        assert stored["operation_id"] == str(operation_id) and stored["status"] == "completed"
        assert stored["result"]["stdout"] == "Exact synthetic receipt"
        assert stored["result"]["status"] == ("running" if recovery == "running-start" else "completed")
        saved = task.get_execution_result()
        assert saved is not None
        for trace in (result.messages, saved.messages):
            assert any(message.type == "tool" and str(operation_id) in json.dumps(message.tool_result)
                       for message in trace)
            assert any(message.type == "tool" and "Exact synthetic receipt" in
                       (message.content + json.dumps(message.tool_result)) for message in trace)
        recovered_calls = (await db.scalars(select(LLMCall).where(LLMCall.task_attempt_id == resumed.attempt_id))).all()
        assert len(recovered_calls) == len(requests) - previous_calls > 0
        assert {call.upstream_request_id for call in recovered_calls} == set(receipts[previous_calls:])
        assert all(call.task_id == task.id and call.agent_run_id == request.run_id for call in recovered_calls)
    else:
        assert len(requests) == previous_calls
        await db.refresh(task)
        assert task.data["_agent_run_checkpoint"]["data"]["effects"][0]["status"] in {"started", "outcome_unknown"}
    assert list(workspace.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize("completed", [False, True], ids=["model-in-progress", "result-saved-before-worker-loss"])
async def test_embedded_task_recovers_worker_loss_without_a_tool_effect(
    runtime, committed_database, monkeypatch, tmp_path, completed, driver,
):
    from app.agent import has_resumable_run_checkpoint

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 2)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(scheduler, "wake", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_last_lease_recovery", 0.0)
    gate = asyncio.Event()
    if completed:
        gate.set()
    receipts, closed = [], set()
    mode.update(concurrent=True, partial_gate=gate, chat_response_ids=receipts, closed_streams=closed)
    user = User(email=f"task-recovery-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic recovery without effects", text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    agent = Agent(code=f"pure-recovery-{uuid4().hex}", user_id=user.id, first_name="Synthetic",
                  last_name="Recovery", title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id,
                  agent_driver=driver)
    db.add(agent)
    await db.flush()
    task = Task(label="Synthetic read-only work", objective="Return a short synthetic answer without using tools.",
                agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="standard",
                ai=True, lease_token=uuid4(), lease_owner="lost-worker", attempt_count=1,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(task)
    await db.flush()
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase=TaskStatus.DISPATCH.value,
                       worker_id=task.lease_owner, lease_token=task.lease_token))
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    original = await build_run_request(task)
    await db.commit()
    emitted = asyncio.Event()
    lost = False

    async def save_while_worker_is_live(checkpoint):
        if not lost:
            await original.save_checkpoint(checkpoint)

    interrupted = replace(original, control=replace(original.control, save_checkpoint=save_while_worker_is_live))

    async def abandon_before_task_result():
        async with aclosing(stream(interrupted)) as events:
            async for event in events:
                if event.result is not None:
                    assert event.result.success
                    emitted.set()
                    await asyncio.Future()

    async with _gateway(monkeypatch), asyncio.timeout(35):
        worker = asyncio.create_task(abandon_before_task_result())
        try:
            if completed:
                await emitted.wait()
            else:
                partial = select(LLMCallEvent.id).join(LLMCall).where(
                    LLMCall.task_id == task.id, LLMCallEvent.payload["message"]["type"].astext == "text",
                ).limit(1)
                while not worker.done():
                    async with get_db_session() as reader:
                        if await reader.scalar(partial) is not None:
                            break
                    await asyncio.sleep(0.01)
                else:
                    await worker
                    pytest.fail("The original worker never reached the first provider text.")
            assert len(requests) == 1
        finally:
            # A lost process cannot make its shutdown checkpoint durable.
            lost = True
            worker.cancel()
            try:
                with pytest.raises(asyncio.CancelledError):
                    await worker
                async with asyncio.timeout(6):
                    while not closed:
                        await asyncio.sleep(0.02)
            finally:
                gate.set()
            assert closed == set(receipts)
        await db.refresh(task)
        task.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        await scheduler._recover_expired_leases()
        await db.refresh(task)
        assert task.status == TaskStatus.DISPATCH
        assert has_resumable_run_checkpoint(task)
        checkpoint = task.data["_agent_run_checkpoint"]
        assert checkpoint["driver_code"] == driver and checkpoint["data"]["effects"] == []
        assert checkpoint["status"] == ("completed" if completed else "running")
        monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_REQUESTS", 1)
        task.next_attempt_at = None
        await db.commit()
        claim = await scheduler._claim_specific(task.id, priority=0)
        assert claim is not None
        task_id, phase, _priority, _agent_id, lease = claim
        await scheduler._run_claimed_action(task_id, phase, lease)
        await db.refresh(task)
    assert task.status == TaskStatus.SUCCESS and task.get_execution_result().result == "Bonjour !"
    assert len(requests) == (1 if completed else 2)
    calls = (await db.scalars(select(LLMCall).where(LLMCall.task_id == task.id).order_by(LLMCall.started_at))).all()
    assert len(calls) == len(requests)
    assert calls[-1].upstream_request_id == receipts[-1] and calls[-1].status == "completed"
    assert all(call.agent_run_id == original.run_id for call in calls)
    assert calls[0].task_attempt_id == original.attempt_id
    if completed:
        assert calls[0].cost > 0 and task.cost == pytest.approx(calls[0].cost)
    else:
        assert calls[0].status == "cancelled" and calls[1].task_attempt_id != original.attempt_id
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize("boundary", ["before-journal", "waiting-for-provider", "after-dispatch"])
async def test_embedded_preserves_provider_lineage_when_the_task_attempt_is_replaced(
    runtime, committed_database, monkeypatch, tmp_path, driver, boundary,
):
    from app.agent import HarnessExecutionError
    from app.agent.contracts import StaleAgentRunError
    from app.llm import llm_call_service, provider_scheduler

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    receipts, closed = [], set()
    mode.update(concurrent=True, chat_response_ids=receipts, closed_streams=closed)

    user = User(email=f"stale-inference-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic frozen model", text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    agent = Agent(code=f"frozen-attempt-{uuid4().hex}", user_id=user.id, first_name="Synthetic", last_name="Attempt",
                  title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id, agent_driver=driver)
    db.add(agent)
    await db.flush()
    expiration = datetime.now(timezone.utc) + timedelta(minutes=5)
    task = Task(label="Synthetic frozen inference", objective="Reply with a short synthetic answer.",
                agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="standard",
                lease_token=uuid4(), lease_owner="old-inference-worker", lease_expires_at=expiration, attempt_count=1)
    db.add(task)
    await db.flush()
    first = TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", worker_id=task.lease_owner,
                        lease_token=task.lease_token)
    db.add(first)
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    old = await build_run_request(task)
    await db.commit()

    reached, release = asyncio.Event(), asyncio.Event()
    after_dispatch = boundary == "after-dispatch"
    if after_dispatch:
        mode["partial_gate"] = release
    else:
        target, method = ((llm_call_service, "create_running_call") if boundary == "before-journal"
                          else (provider_scheduler, "acquire_call"))
        original = getattr(target, method)

        async def wait_for_replacement(*args, **kwargs):
            if not reached.is_set():
                reached.set()
                await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(target, method, wait_for_replacement)

    async def collect(request):
        async with aclosing(stream(request)) as events:
            return [event async for event in events if event.result is not None]

    async with _gateway(monkeypatch), asyncio.timeout(45):
        worker = asyncio.create_task(collect(old))
        try:
            if after_dispatch:
                async with asyncio.timeout(12):
                    while not requests:
                        await asyncio.sleep(0.01)
                [running] = (await db.scalars(select(LLMCall).where(LLMCall.task_id == task.id))).all()
                assert running.status == "running" and running.task_attempt_id == old.attempt_id
            else:
                await asyncio.wait_for(reached.wait(), 12)
                assert requests == []
            await db.refresh(task)
            await db.refresh(first)
            first.status, first.finished_at = "RETRY", datetime.now(timezone.utc)
            task.lease_token, task.lease_owner, task.attempt_count = uuid4(), "replacement-inference-worker", 2
            replacement = TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", worker_id=task.lease_owner,
                                      lease_token=task.lease_token)
            db.add(replacement)
            await db.commit()
            await db.refresh(agent, attribute_names=["title"])
            current = await build_run_request(task)
            await db.commit()
            assert current.run_id == old.run_id and current.attempt_id != old.attempt_id
        finally:
            release.set()
            try:
                stale_outcome = await worker
            except (HarnessExecutionError, StaleAgentRunError):
                stale_outcome = []
        assert not any(event.result.success for event in stale_outcome)
        assert len(requests) == int(after_dispatch)
        [finished] = await collect(current)
        assert finished.result.success and finished.result.result == "Bonjour !"

    assert len(requests) == (2 if after_dispatch else 1)
    calls = (await db.scalars(select(LLMCall).where(LLMCall.task_id == task.id)
                             .order_by(LLMCall.started_at).execution_options(populate_existing=True))).all()
    assert [call.upstream_request_id for call in calls] == receipts
    assert [call.agent_run_id for call in calls] == [current.run_id] * len(calls)
    assert [call.requester_user_id for call in calls] == [user.id] * len(calls)
    assert current.attempt_id == replacement.id
    assert [call.task_attempt_id for call in calls] == ([old.attempt_id, current.attempt_id] if after_dispatch
                                                       else [current.attempt_id])
    assert closed == set(receipts)
    assert all(call.completed_at is not None for call in calls)
    assert calls[-1].status == "completed"
    if after_dispatch:
        # A stale progress write can close the old SDK stream before the provider's
        # terminal chunk arrives. Either outcome must stay on the original attempt.
        assert calls[0].status in {"cancelled", "completed"}


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize("scenario", [
    "confirmed", "text-confirmed", "unconfirmed", "document-removed", "tool-disabled", "tool-budget", "approved-budget",
])
async def test_embedded_resumes_a_durable_document_creation_without_creating_it_twice(
    runtime, committed_database, monkeypatch, tmp_path, scenario, driver,
):
    from app.agent import HarnessCheckpointError, has_resumable_run_checkpoint
    from app.document import Document

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    approved = scenario == "approved-budget"
    capped = scenario in {"tool-budget", "approved-budget"}
    if capped:
        monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 1)
    user = User(email=f"creation-recovery-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic document recovery", text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    if approved:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
        role = Role(code=f"document-recovery-{uuid4().hex}", privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
    agent = Agent(code=f"creation-recovery-{uuid4().hex}", user_id=user.id, first_name="Synthetic", last_name="Document",
                  title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id, agent_driver=driver)
    db.add(agent)
    await db.flush()
    files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    connection = Connection(agent_id=agent.id, service_id=files.id, active=True)
    db.add(connection)
    await db.flush()
    policy = ConnectionFunctionState(connection_id=connection.id, function_name="file_create",
                                     state="ask" if approved else "enabled", enabled=True)
    task = Task(label="Synthetic confirmed document creation", objective="Create the synthetic inventory once.",
                agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="standard",
                lease_token=uuid4(), lease_owner="before-interruption", attempt_count=1,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add_all([policy, task])
    await db.flush()
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", worker_id=task.lease_owner,
                       lease_token=task.lease_token))
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    request = await build_run_request(task)
    await db.commit()
    title = "Synthetic receipt inventory"
    text_document = scenario == "text-confirmed"
    resource = Document if text_document else Dataset
    scheme = "document" if text_document else "data"
    arguments = {"path": f"{scheme}://", "name": title, "content": "<p>42</p>" if text_document else '{"stock":42}'}
    replacement_title = "Synthetic second inventory"
    reached = asyncio.Event()
    lost = False
    continuing = False
    proposal_sent = False

    async def hold_at_receipt(checkpoint):
        if lost:
            return
        effects = checkpoint.data["effects"]
        if not effects or effects[-1]["status"] != "completed":
            await request.save_checkpoint(checkpoint)
            return
        if scenario != "unconfirmed":
            await request.save_checkpoint(checkpoint)
        reached.set()
        await asyncio.Future()

    def choose_tools(body):
        nonlocal proposal_sent
        tool_name = "file_create" if driver == "internal" else "mcp__galaris__file_create"
        offered_tools = {tool["function"]["name"] for tool in body.get("tools", [])}
        if proposal_sent or tool_name not in offered_tools:
            return []
        proposal_sent = True
        tool_arguments = {**arguments, "name": replacement_title} if continuing and capped else arguments
        call_id = "resumed-file-request" if continuing else "initial-file-request"
        return [(call_id, tool_name, tool_arguments)]

    async def collect(request):
        return [event async for event in stream(request)]

    receipts = []
    mode.update(concurrent=True, tool_calls_for=choose_tools, chat_response_ids=receipts)
    async with _gateway(monkeypatch), asyncio.timeout(30):
        documents = select(resource).where(resource.owner_agent_id == agent.id, resource.title == title)
        if approved:
            [pending] = [event.result for event in await collect(request) if event.result is not None]
            assert pending.disposition == "waiting_for_authorization"
            [approval_id] = pending.authorization_requests
            assert await db.scalar(documents) is None
            assert await answer_action(approval_id, user_id=user.id, approved=True)
        else:
            interrupted = replace(request, control=replace(request.control, save_checkpoint=hold_at_receipt))
            worker = asyncio.create_task(collect(interrupted))
            try:
                await reached.wait()
            finally:
                lost = True
                worker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await worker
        created_before_resume = (await db.scalars(documents)).one_or_none()
        assert (created_before_resume is None) is approved
        original_identity = created_before_resume.id if created_before_resume is not None else None
        await db.refresh(task)
        [original] = task.data["_agent_run_checkpoint"]["data"]["effects"]
        expected_status = {"unconfirmed": "started", "approved-budget": "waiting_for_authorization"}
        assert original["status"] == expected_status.get(scenario, "completed")
        assert has_resumable_run_checkpoint(task) is (scenario != "unconfirmed")

        if scenario == "unconfirmed":
            return
        if scenario == "document-removed":
            created_before_resume.soft_delete()
        if scenario == "tool-disabled":
            policy.state, policy.enabled = "disabled", False
        if capped:
            monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 4)
        task.lease_token = uuid4()
        task.lease_owner = "replacement-worker"
        task.attempt_count = 2
        db.add(TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", worker_id=task.lease_owner,
                           lease_token=task.lease_token))
        await db.commit()
        await db.refresh(agent, attribute_names=["title"])
        resumed = await build_run_request(task)
        await db.commit()
        previous_calls = len(requests)
        assert resumed.run_id == request.run_id and resumed.attempt_id != request.attempt_id
        continuing, proposal_sent = True, False
        if scenario in {"document-removed", "tool-disabled"}:
            with pytest.raises(HarnessCheckpointError) as blocked:
                await collect(resumed)
            assert blocked.value.failure.retry == "never"
            assert len(requests) == previous_calls
            return
        events = await collect(resumed)

    [result] = [event.result for event in events if event.result is not None]
    assert result.success
    [created] = (await db.scalars(documents)).all()
    if not approved:
        assert created.id == original_identity
    uri = f"{scheme}://{created.id}"
    assert any(uri in json.dumps(body["messages"]) for body in requests[previous_calls:])
    if capped:
        assert proposal_sent
        assert await db.scalar(select(resource.id).where(resource.owner_agent_id == agent.id,
                                                         resource.title == replacement_title)) is None
        assert resumed.limits.tool_call_limit == request.limits.tool_call_limit == 1
    elif driver == "claude_embedded":
        assert "already recorded" in json.dumps(requests[-1]["messages"])
    [receipt] = [message for message in result.messages if message.type == "tool" and message.success
                 and uri in json.dumps(message.tool_result)]
    assert receipt.tool_name == "file_create"
    await db.refresh(task)
    [stored] = task.data["_agent_run_checkpoint"]["data"]["effects"]
    assert stored["operation_id"] == original["operation_id"]
    calls = (await db.scalars(select(LLMCall).where(LLMCall.task_attempt_id == resumed.attempt_id))).all()
    assert len(calls) == len(requests) - previous_calls > 0
    assert {call.upstream_request_id for call in calls} == set(receipts[previous_calls:])
    assert all(call.task_id == task.id and call.agent_run_id == request.run_id for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(("effect_state", "decision"), [
    pytest.param(None, None, id="reads"),
    pytest.param("enabled", None, id="task-write"),
    pytest.param("ask", None, id="task-pending"),
    pytest.param("ask", "approved", id="task-approved"),
    pytest.param("ask", "denied", id="task-denied"),
    pytest.param("ask", "revoked", id="task-revoked-after-approval"),
])
async def test_embedded_claude_attributes_concurrent_rounds_and_their_task_to_exact_attempts(
    runtime, committed_database, monkeypatch, tmp_path, effect_state, decision,
):
    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    mode["concurrent"] = True
    mode["gate"] = asyncio.Event()
    # Two text rounds and one background task must overlap while voice retains its reserved slot.
    model.provider.max_concurrent_calls = 4
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
    assert service is not None
    user = User(email=f"claude-lineage-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic Claude lineage", text_low_llm_id=model.id,
                         text_standard_llm_id=model.id, text_high_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    if decision is not None:
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
        role = Role(code=f"claude-approval-{uuid4().hex}", privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
    agent = Agent(
        code=f"claude-lineage-{uuid4().hex}", user_id=user.id, first_name="Claude", last_name="Lineage",
        title_id=await db.scalar(select(Title.id).limit(1)),
        profile_id=profile.id, agent_driver="claude_embedded",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(service_id=service.id, agent_id=agent.id, active=True)
    files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    assert files is not None
    file_connection = Connection(service_id=files.id, agent_id=agent.id, active=True)
    db.add(file_connection)
    sender = MessengerUser(service_id=service.id, galaris_user_id=user.id, external_id=str(uuid4()))
    assistant = MessengerUser(service_id=service.id, agent_id=agent.id, external_id=f"agent:{agent.id}", is_ai=True)
    db.add_all([connection, sender, assistant])
    await db.flush()
    if effect_state is not None:
        db.add(ConnectionFunctionState(connection_id=file_connection.id, function_name="file_create",
                                       state=effect_state, enabled=effect_state == "enabled"))

    async def create_turn(prompt, *, response_only):
        room = Room(connection_id=connection.id, external_id=str(uuid4()), label="Synthetic room",
                    kind="direct", conversation_type="text")
        db.add(room)
        await db.flush()
        inbound = Message(
            connection_id=connection.id, service_id=service.id, messenger_room_id=room.id, room=room,
            platform="internal", remote_message_id=str(uuid4()), direction="inbound",
            requester_user_id=user.id, messenger_user_id=sender.id, sender_messenger_user_id=sender.id,
            user_id=sender.external_id,
            text=prompt,
        )
        db.add_all([inbound, *(RoomUser(room_id=room.id, user_id=member.id) for member in (sender, assistant))])
        await db.flush()
        assert await admit_message(inbound, agent_id=agent.id, connection_id=connection.id)
        round_ = await claim_next_round("claude-lineage-test")
        assert round_ is not None and round_.room_id == room.id and round_.lease_token is not None
        assert round_.driver_code == "claude_embedded"
        round_.response_only = response_only
        await db.commit()
        attempt = await db.scalar(select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id == round_.id))
        assert attempt is not None and attempt.inference_admission is None
        turn = await build_turn(round_.id, lease_token=round_.lease_token)
        await db.commit()
        return turn, EmbeddedRoundInference(
            agent_id=agent.id, round_id=round_.id, attempt_id=attempt.id, run_id=round_.id,
            model_id=model.id, model_code=model.code, driver_code=turn.driver_code,
            request_limit=runtime_settings.TASK_AGENT_MAX_REQUESTS,
        )

    round_prompts = ("Synthetic first turn", "Synthetic second turn")
    turns, origins_by_room = zip(
        await create_turn(round_prompts[0], response_only=True),
        await create_turn(round_prompts[1], response_only=False), strict=True,
    )
    rounds = list(origins_by_room)
    lease_token = uuid4()
    task_prompt = "Synthetic follow-up task"
    read_ids = ("synthetic-read-first", "synthetic-read-second")
    label = "Synthetic Claude receipt dataset"
    contents = {"synthetic": "journal-qualified"}

    def choose_tools(body):
        text = json.dumps(body["messages"])
        if "Galaris has resolved the earlier tool authorization" in text:
            if any(item["role"] == "tool" and "already recorded" in str(item["content"]) for item in body["messages"]):
                return []
            return [("synthetic-replay", "mcp__galaris__file_create",
                     {"path": "data://", "name": label, "content": json.dumps(contents)})] if decision != "revoked" else []
        if not any(prompt in text for prompt in (task_prompt, round_prompts[1])):
            return []
        if any(item["role"] == "tool" for item in body["messages"]):
            return []
        if effect_state is not None and task_prompt in text:
            return [("synthetic-write", "mcp__galaris__file_create",
                     {"path": "data://", "name": label, "content": json.dumps(contents)})]
        return [(call_id, "mcp__galaris__file_schemes", {}) for call_id in read_ids]

    mode["tool_calls_for"] = choose_tools
    task = Task(
        label="Synthetic round follow-up", objective=task_prompt,
        agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC,
        effort="high", reasoning_effort_override="medium",
        lease_token=lease_token, lease_owner="claude-lineage-test", attempt_count=1,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        data={"conversation_round_id": str(rounds[0].round_id)},
    )
    db.add(task)
    await db.flush()
    db.add_all([
        ConversationTaskLink(round_id=rounds[0].round_id, task_id=task.id, action_key="synthetic-follow-up"),
        TaskAttempt(task_id=task.id, attempt_number=1, phase="EXEC", worker_id="claude-lineage-test",
                    lease_token=lease_token),
    ])
    await db.commit()
    await db.refresh(agent, attribute_names=["title"])
    task_request = await build_run_request(task)
    task_attempt_id = task_request.attempt_id
    assert task_attempt_id is not None
    assert task_request.effort == "high" and task_request.model.reasoning_effort == "medium"
    task_origin = EmbeddedTaskInference(
        agent_id=agent.id, task_id=task.id, attempt_id=task_attempt_id, run_id=task_request.run_id,
        model_id=model.id, model_code=model.code, reasoning_effort="medium",
        executor_profile_effort=task_request.model.executor_profile_effort,
    )
    origins = [*rounds, task_origin]
    await db.commit()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning", access_log=False))
        gateway = f"http://127.0.0.1:{listener.getsockname()[1]}/api/llm/anthropic"
        monkeypatch.setattr(claude_driver, "CLAUDE_GATEWAY", gateway)
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.01)

            body = {"model": model.code, "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Must never reach provider"}]}
            async with AsyncClient() as client:
                response = await client.get(
                    f"{gateway}/v1/models", headers={"x-api-key": origins[0].credential()},
                )
                assert response.status_code == 403, response.text

            def check_read_receipts(result):
                receipts = [message for message in result.messages if message.tool_name == "file_schemes"]
                assert len(receipts) == 2 and all(item.success and "schemes" in item.content for item in receipts)
                receipt_ids = {message.tool_call_external_id for message in receipts}
                assert len(receipt_ids) == 2 and None not in receipt_ids
                return receipt_ids

            async def run(stream_events):
                events = [event async for event in stream_events]
                assert len(events) >= 2
                assert all(event.kind == "message" for event in events[:-1])
                assert "".join(event.message.content for event in events[:-1] if event.message.type == "text") == "Bonjour !"
                result = events[-1].result
                assert result is not None
                assert result.usage.requests == 2
                if effect_state == "ask":
                    assert not result.success and not result.result
                    assert result.disposition == "waiting_for_authorization" and len(result.authorization_requests) == 1
                else:
                    assert result.success and result.result == "Bonjour !", result
                if effect_state is not None:
                    receipts = [message for message in result.messages if message.tool_name == "file_create"]
                    assert len(receipts) == 1 and receipts[0].success is (effect_state == "enabled"), receipts
                    return {receipts[0].tool_call_external_id}
                return check_read_receipts(result)

            async def run_round(turn):
                from dataclasses import replace

                async def publish(message):
                    if message.type == "text":
                        fragments.append(message.content)
                    else:
                        live_tool_ids.add(message.tool_call_external_id)

                fragments = []
                live_tool_ids = set()
                outcome = await HarnessConversationController().run(replace(turn, publish_progress=publish))
                assert "".join(fragments) == "Bonjour !"
                assert outcome.text == "Bonjour !"
                result = outcome.execution_result
                assert result is not None and result.success
                assert result.metadata["driver_code"] == "claude_embedded"
                assert result.usage is not None and result.usage.requests == (1 if turn.force_response else 2)
                assert live_tool_ids == (set() if turn.force_response else check_read_receipts(result))
                return outcome, live_tool_ids

            prompts = (*round_prompts, task_prompt)

            async def allow_concurrent_responses():
                while len(requests) < 3:
                    await asyncio.sleep(0.02)
                mode["gate"].set()

            async with asyncio.timeout(60):
                _, task_receipt_ids, *round_runs = await asyncio.gather(
                    allow_concurrent_responses(), run(stream(task_request)), *(run_round(turn) for turn in turns),
                )
            assert list(tmp_path.iterdir()) == []
            outcomes, round_receipt_ids = zip(*round_runs, strict=True)
            receipt_ids_by_prompt = dict(zip(prompts, (*round_receipt_ids, task_receipt_ids), strict=True))
            assert len(requests) == 5
            names = {definition["function"]["name"] for body in requests for definition in body.get("tools", [])}
            assert "mcp__galaris__file_schemes" in names
            assert all(name.startswith("mcp__galaris__") for name in names), sorted(names)
            round_names = {item["function"]["name"] for body in requests
                           if task_prompt not in json.dumps(body["messages"]) for item in body.get("tools", [])}
            assert "mcp__galaris__file_delete" not in round_names
            assert "mcp__galaris__file_create" not in round_names
            observed = [json.dumps(request["messages"]) for request in requests]
            calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id)))
            assert len(calls) == 5
            for origin, prompt in zip(origins, prompts, strict=True):
                run_calls = [call for call in calls if call.agent_run_id == origin.run_id]
                expected = 1 if prompt == round_prompts[0] else 2
                assert len(run_calls) == sum(prompt in request for request in observed) == expected
                for call in run_calls:
                    assert call.correlation_ref == origin.correlation_ref
                    if isinstance(origin, EmbeddedRoundInference):
                        assert call.conversation_round_id == origin.round_id
                        assert call.purpose == "conversation.text"
                        assert call.task_id is None and call.task_attempt_id is None
                    else:
                        assert call.conversation_round_id == rounds[0].round_id
                        assert call.purpose == "agent.exec"
                        assert call.task_id == task.id and call.task_attempt_id == task_attempt_id
                        assert call.reasoning_effort == "medium"
                    trace = json.dumps(call.request_messages)
                    assert prompt in trace
                    assert all(other not in trace for other in prompts if other != prompt)
                    assert call.inference_attempt_id is not None
                    assert call.requester_user_id == user.id
                returned = [message for request in requests if prompt in json.dumps(request["messages"])
                            for message in request["messages"] if message["role"] == "tool"]
                if prompt == task_prompt:
                    assert all(request.get("reasoning_effort") == "medium" for request in requests
                               if prompt in json.dumps(request["messages"]))
                assert {message["tool_call_id"] for message in returned} == receipt_ids_by_prompt[prompt]
                assert len(returned) == len(receipt_ids_by_prompt[prompt])
                expected_content = {"enabled": "data://", "ask": "requires authorization"}.get(effect_state, "schemes") if prompt == task_prompt else "schemes"
                assert all(expected_content in str(message["content"]) for message in returned)
            assert len({call.inference_attempt_id for call in calls}) == 5
            assert task_receipt_ids.isdisjoint(round_receipt_ids[1])
            if effect_state is not None:
                await db.refresh(task)
                persisted = task.data["_agent_run_checkpoint"]
                expected_status = "completed" if effect_state == "enabled" else "waiting_for_authorization"
                assert persisted["status"] == expected_status
                assert persisted["data"]["tool_calls_used"] == 1
                effects = persisted["data"]["effects"]
                assert len(effects) == 1 and effects[0]["status"] == expected_status
                assert effects[0]["tool_name"] == "file_create"
                assert effects[0]["tool_call_id"] in task_receipt_ids
                datasets = list(await db.scalars(select(Dataset).where(Dataset.title == label)))
                if effect_state == "enabled":
                    assert len(datasets) == 1 and json.loads(datasets[0].content) == contents
                else:
                    assert datasets == []
                    receipt = effects[0]["result"]
                    approval = await db.get(ActionAuthorization, UUID(receipt["authorization_request_id"]))
                    assert approval is not None and approval.status == "pending" and approval.agent_id == agent.id
                    continuation = receipt["sealed_continuation"]
                    assert isinstance(continuation, str) and continuation and continuation not in json.dumps(requests)
                    transcript = persisted["data"]["sdk_session"]
                    assert isinstance(transcript, str) and task_prompt not in transcript
                original_attempt = await db.get(TaskAttempt, task_attempt_id, populate_existing=True)
                assert original_attempt.data["agent_checkpoint"] == persisted

            stale = await db.get(ConversationRound, rounds[0].round_id)
            assert stale is not None
            stale.lease_token = uuid4()
            await db.commit()
            async with AsyncClient() as client:
                models = await client.get(f"{gateway}/v1/models", headers={"x-api-key": origins[1].credential()})
                assert models.status_code == 200, models.text
                assert [item["id"] for item in models.json()["data"]] == [model.code]
                denied = await client.post(f"{gateway}/v1/messages", json=body,
                                           headers={"x-api-key": origins[0].credential()})
                assert denied.status_code == 403
                missing = await client.post(f"{gateway}/v1/messages", json=body)
                assert missing.status_code == 401
                conflicting = await client.post(
                    f"{gateway}/v1/messages", json=body,
                    headers={"x-api-key": origins[1].credential(), "X-Galaris-Conversation-Round-Id": str(stale.id)},
                )
                assert conflicting.status_code == 403
                for mismatch in ({"run_id": uuid4()}, {"audio": True}, {"driver_code": "internal"},
                                 {"model_id": model.id + 1}, {"model_code": "unadmitted"}, {"reasoning_effort": "high"},
                                 {"request_limit": runtime_settings.TASK_AGENT_MAX_REQUESTS + 1}):
                    wrong_round = rounds[1].model_copy(update=mismatch)
                    denied_round = await client.post(
                        f"{gateway}/v1/messages", json=body, headers={"x-api-key": wrong_round.credential()},
                    )
                    assert denied_round.status_code == 403
                wrong_effort = "high" if task_origin.executor_profile_effort == "standard" else "standard"
                for mismatch in ({"run_id": uuid4()}, {"reasoning_effort": "low"}, {"reasoning_effort": None},
                                 {"executor_profile_effort": wrong_effort}, {"executor_profile_effort": None}):
                    wrong_task = task_origin.model_copy(update=mismatch)
                    denied_task = await client.post(
                        f"{gateway}/v1/messages", json=body,
                        headers={"x-api-key": wrong_task.credential()},
                    )
                    assert denied_task.status_code == 403
                await db.refresh(task)
                task.lease_token = uuid4()
                await db.commit()
                stale_task = await client.post(
                    f"{gateway}/v1/messages", json=body, headers={"x-api-key": task_origin.credential()},
                )
                assert stale_task.status_code == 403
                if effect_state == "enabled":
                    db.add(TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", worker_id="recovery-worker",
                                       lease_token=task.lease_token))
                    await db.commit()
                    resumed = await build_run_request(task)
                    assert resumed.attempt_id != task_attempt_id and resumed.run_id == task_request.run_id
                    replay = [event async for event in stream(resumed)]
                    assert len(replay) == 1 and replay[0].result.result == "Bonjour !"
                    assert len(requests) == 5
                    assert list(await db.scalars(select(Dataset.id).where(Dataset.title == label))) == [datasets[0].id]
                elif effect_state == "ask":
                    task.attempt_count = 2
                    db.add(TaskAttempt(task_id=task.id, attempt_number=2, phase="EXEC", worker_id="recovery-worker",
                                       lease_token=task.lease_token))
                    await db.commit()
                    resumed = await build_run_request(task)
                    pending_events = [event async for event in stream(resumed)]
                    assert len(pending_events) == 1
                    assert pending_events[0].result.authorization_requests == [approval.id]
                    assert len(requests) == 5
                    if decision is not None:
                        await db.refresh(task)
                        await executor_service._update_task_after_execution(task, pending_events[0].result, base_cost=0)
                        await db.commit()
                        await scheduler._complete_claim(task.id, TaskStatus.DISPATCH, task.lease_token)
                        await db.refresh(task)
                        assert task.lease_token is None
                        assert task_service.is_paused_for(task, task_service.PAUSE_APPROVAL)
                        wakeups = []
                        monkeypatch.setattr(runner, "go_next", lambda task_id, *, fast=False: wakeups.append((task_id, fast)))
                        context_key = f"task:{task.id}"
                        assert not await wake_authorization_context(agent.id, context_key)
                        assert wakeups == []
                        assert await answer_action(approval.id, user_id=user.id, approved=decision != "denied")
                        if decision == "revoked":
                            state = await db.scalar(select(ConnectionFunctionState).where(
                                ConnectionFunctionState.connection_id == file_connection.id,
                                ConnectionFunctionState.function_name == "file_create",
                            ))
                            state.state = "disabled"
                            state.enabled = False
                            await db.commit()
                        assert await wake_authorization_context(agent.id, context_key)
                        assert wakeups == [(task.id, True)]
                        claimed = await scheduler._claim_specific(task.id, priority=0)
                        assert claimed is not None and claimed[1] == TaskStatus.DISPATCH
                        await db.commit()
                        await db.refresh(task)
                        await executor_service._update_task_status(task, executor_service.TaskPhase.EXEC)
                        await db.commit()
                        await db.refresh(agent, attribute_names=["title"])
                        resumed = await build_run_request(task)
                        assert resumed.run_id == task_request.run_id and resumed.attempt_id != task_attempt_id
                        resumed_events = [event async for event in stream(resumed)]
                        result = resumed_events[-1].result
                        assert result is not None and result.success, result
                        assert result.result == "Bonjour !"
                        db_calls = list(await db.scalars(select(LLMCall).where(
                            LLMCall.task_attempt_id == resumed.attempt_id,
                        )))
                        assert len(db_calls) == (1 if decision == "revoked" else 2)
                        assert all(call.task_id == task.id and call.agent_run_id == task_request.run_id
                                   and call.conversation_round_id == rounds[0].round_id for call in db_calls)
                        assert all(task_prompt in json.dumps(call.request_messages) for call in db_calls)
                        assert any("authorization" in json.dumps(call.request_messages) and
                                   effects[0]["tool_call_id"] in json.dumps(call.request_messages) for call in db_calls)
                        await db.refresh(task)
                        await db.refresh(approval)
                        after = task.data["_agent_run_checkpoint"]
                        assert after["status"] == "completed" and "sdk_session" not in after["data"]
                        assert after["data"]["tool_calls_used"] == 1
                        resumed_effects = after["data"]["effects"]
                        assert len(resumed_effects) == 1
                        assert resumed_effects[0]["operation_id"] == effects[0]["operation_id"]
                        assert resumed_effects[0]["tool_call_id"] == effects[0]["tool_call_id"]
                        assert resumed_effects[0]["arguments"] == effects[0]["arguments"]
                        actual = list(await db.scalars(select(Dataset).where(Dataset.title == label)))
                        if decision == "approved":
                            assert len(actual) == 1 and json.loads(actual[0].content) == contents
                            assert resumed_effects[0]["status"] == approval.status == "completed"
                        else:
                            assert actual == []
                            assert resumed_effects[0]["status"] == "rejected"
                            if decision == "denied":
                                assert approval.status == "denied"
                completed = await db.get(ConversationRound, rounds[1].round_id)
                assert completed is not None and completed.lease_token is not None
                completion = await complete_round(completed.id, outcomes[1], lease_token=completed.lease_token)
                assert completion == "SUCCEEDED", completed.last_error
                delivered = list(await db.scalars(select(Message.text).join(
                    ConversationRoundMessage, ConversationRoundMessage.message_id == Message.id,
                ).where(ConversationRoundMessage.round_id == completed.id, ConversationRoundMessage.role == "output")))
                assert delivered == ["Bonjour !"]
                finished_round = await client.post(
                    f"{gateway}/v1/messages", json=body, headers={"x-api-key": origins[1].credential()},
                )
                assert finished_round.status_code == 403
            assert len(requests) == 5 + (0 if decision is None else 1 if decision == "revoked" else 2)
            if effect_state is None:
                # The completed run now returns its checkpoint without starting a worker.
                # Exercise cancellation on newly admitted work from the same round.
                stoppable = Task(label="Synthetic cancellation", objective="Wait for a synthetic response.",
                    agent=agent, requester_user_id=user.id, status=TaskStatus.EXEC, effort="high",
                    reasoning_effort_override="medium", lease_token=uuid4(), lease_owner="stop-worker",
                    attempt_count=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    data={"conversation_round_id": str(rounds[0].round_id)})
                db.add(stoppable)
                await db.flush()
                db.add_all([
                    ConversationTaskLink(round_id=rounds[0].round_id, task_id=stoppable.id, action_key="synthetic-cancel"),
                    TaskAttempt(task_id=stoppable.id, attempt_number=1, phase="EXEC", worker_id="stop-worker",
                                lease_token=stoppable.lease_token),
                ])
                await db.commit()
                cancellation = await build_run_request(stoppable)
                await db.commit()
                mode["gate"] = asyncio.Event()

                async def execute_stoppable():
                    async with get_db_session():
                        return [event async for event in stream(cancellation)]

                running = asyncio.create_task(execute_stoppable())
                try:
                    async with asyncio.timeout(20):
                        while len(requests) < 6 and not running.done():
                            await asyncio.sleep(0.02)
                        assert len(requests) == 6 and not running.done()
                        with pytest.raises(HarnessProtocolError, match="different driver"):
                            await cancel("internal", cancellation.run_id, task_id=stoppable.id)
                        await db.refresh(stoppable)
                        stoppable.cancel_requested = True
                        await db.commit()
                        receipt = await cancel("claude_embedded", cancellation.run_id, task_id=stoppable.id)
                        assert receipt.state == "confirmed" and receipt.scope == "local"
                        assert receipt == await cancel("claude_embedded", cancellation.run_id, task_id=stoppable.id)
                        assert isinstance((await asyncio.gather(running, return_exceptions=True))[0], asyncio.CancelledError)
                        observed_call = await db.scalar(select(LLMCall).where(LLMCall.task_attempt_id == cancellation.attempt_id))
                        assert observed_call is not None and observed_call.agent_run_id == cancellation.run_id
                        assert observed_call.task_id == stoppable.id and observed_call.conversation_round_id == rounds[0].round_id
                        assert len(requests) == 6 and list(tmp_path.iterdir()) == []
                finally:
                    mode["gate"].set()
                    if not running.done():
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
        finally:
            mode["gate"].set()
            server.should_exit = True
            await server_task


@pytest.mark.asyncio
@pytest.mark.parametrize("discovery", ["eager", "deferred", "revoked", "approved", "native"])
async def test_planned_claude_task_executes_its_child_through_the_scheduler(
    runtime, committed_database, monkeypatch, tmp_path, discovery,
):
    from fastmcp import Context, FastMCP

    from app.agent import planner_service
    from app.agent.planner_contracts import Plan, PlanBrief, PlanStep
    from app.llm import proxy_service
    from app.services import tool_search_service
    from app.services.contracts import EXECUTION_META_KEY
    from app.services.facade import AUTHORIZATION_META_KEY

    db, model, requests, mode = runtime
    # Keep the language-model transport scripted while FastMCP uses real HTTP.
    provider_http = proxy_service.httpx
    monkeypatch.setattr(proxy_service, "httpx", SimpleNamespace(**vars(provider_http)))
    monkeypatch.setattr(provider_http, "AsyncClient", AsyncClient)
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)

    async def no_embedding_model():
        return None

    monkeypatch.setattr(tool_search_service, "configured_embedding_model", no_embedding_model)
    mode["concurrent"] = True
    user = User(email=f"claude-planned-{uuid4().hex}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic plan profile", text_standard_llm_id=model.id, text_high_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    if discovery == "approved":
        privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
        role = Role(code=f"claude-plan-approval-{uuid4().hex}", privileges=[privilege])
        db.add(role)
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
    agent = Agent(code=f"claude-plan-{uuid4().hex}", user_id=user.id, first_name="Claude", last_name="Plan",
                  title_id=await db.scalar(select(Title.id).limit(1)), profile_id=profile.id, agent_driver="claude_embedded")
    db.add(agent)
    await db.flush()
    objective = "Write the synthetic release note about fictional apricots."
    step_objective = "Draft one concise sentence about fictional apricots."
    tool_name = "file_schemes" if discovery == "native" else "synthetic_plan_mcp_record_apricots"
    blocked_name = "synthetic_plan_mcp_record_private_apricots"
    anchor_name = "synthetic_plan_mcp_planning_anchor"
    receipts = []
    remote = FastMCP("Synthetic plan Service")

    @remote.tool(description="Record one fictional apricot in the synthetic plan ledger.")
    def record_apricots(value: str, ctx: Context) -> str:
        meta = ctx.request_context.meta or {}
        assert AUTHORIZATION_META_KEY not in meta and EXECUTION_META_KEY not in meta
        receipts.append(value)
        return "Synthetic apricots recorded."

    @remote.tool(description="Record private apricots from a separate fictional ledger.")
    def record_private_apricots(value: str) -> str:
        pytest.fail(f"The disabled tool reached the Service with {value!r}")

    @remote.tool(description="Read the synthetic planning anchor.")
    def planning_anchor() -> str:
        return "Synthetic anchor"

    revoke_gate = asyncio.Event()
    search_name = "mcp__galaris__search_deferred_tools"
    alias = "mcp__galaris__call_discovered_tool"
    args = {} if discovery == "native" else {"value": "one fictional apricot"}
    query = "file_schemes" if discovery == "native" else "record apricots"

    def choose_tools(body):
        messages = body["messages"]
        if "Galaris has resolved the earlier tool authorization" in json.dumps(messages):
            return []
        count = sum(item["role"] == "tool" for item in messages)
        if discovery == "eager":
            return [("synthetic-plan-effect", f"mcp__galaris__{tool_name}", args)] if count == 0 else []
        if count == 0:
            return [("synthetic-premature-effect", alias, {"name": tool_name, "arguments": args})]
        if count == 1:
            return [("synthetic-tool-search", search_name, {"query": query})]
        if count == 2:
            if discovery == "revoked":
                mode["tool_gate"] = revoke_gate
            return [("synthetic-plan-effect", alias, {"name": tool_name, "arguments": args})]
        return []

    mode["tool_calls_for"] = choose_tools
    parent = Task(label="Synthetic planned work", objective=objective, agent=agent, requester_user_id=user.id,
                  status=TaskStatus.CREATE, ai=True, forced_route="PLAN", forced_effort="high")
    db.add(parent)
    await db.commit()

    # Replace the shared planner's model reply so the real scheduler, plan tree,
    # subprocess and gateway can be verified deterministically.
    planner_calls = []

    async def planner_reply(**kwargs):
        planner_calls.append((kwargs["output_type"], kwargs["task_id"]))
        if kwargs["output_type"] is Plan:
            return SimpleNamespace(output=Plan(brief=PlanBrief(objective=objective),
                steps=[PlanStep(label="Draft the note", objective=step_objective,
                                tools=[tool_name if discovery == "eager" else anchor_name])]), cost=0.0, messages=[])
        assert kwargs["output_type"] is str
        assert "Bonjour !" in kwargs["prompt"]
        return SimpleNamespace(output="Synthetic plan completed.", cost=0.0)

    monkeypatch.setattr(planner_service, "run_structured", planner_reply)
    external_app = remote.http_app(path="/mcp", stateless_http=True)
    async with _http_server(external_app, lifespan="on") as service_url, _gateway(monkeypatch), asyncio.timeout(60):
        service = ServiceModel(code="synthetic_plan_mcp", label="Synthetic plan Service",
            mcp_config={"type": "http", "url": f"{service_url}/mcp"})
        db.add(service)
        await db.flush()
        connection = Connection(service_id=service.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        tool_state = "ask" if discovery == "approved" else "enabled"
        function = ConnectionFunctionState(connection_id=connection.id, function_name="record_apricots",
                                           state=tool_state, enabled=tool_state == "enabled")
        db.add_all([function, ConnectionFunctionState(connection_id=connection.id, function_name="record_private_apricots",
                                                     state="disabled", enabled=False),
                    ConnectionFunctionState(connection_id=connection.id, function_name="planning_anchor",
                                            state="enabled", enabled=True)])
        if discovery == "native":
            files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
            assert files is not None
            db.add(Connection(service_id=files.id, agent_id=agent.id, active=True))
        await db.commit()
        assert await scheduler.run_once()
        await db.refresh(parent)
        assert parent.status == TaskStatus.PLAN and parent.get_dispatch_result().decision.route == "PLAN"
        assert await scheduler.run_once()
        [child] = await task_service.get_children(parent.id)
        assert child.agent_id == agent.id and child.requester_user_id == user.id
        assert child.status == TaskStatus.DISPATCH and not child.paused
        if discovery == "revoked":
            async def run_child():
                async with get_db_session():
                    return await scheduler.run_once()

            worker = asyncio.create_task(run_child())
            try:
                while "tool_gate" not in mode and not worker.done():
                    await asyncio.sleep(0.025)
                assert "tool_gate" in mode
                function.state, function.enabled = "disabled", False
                await db.commit()
            finally:
                revoke_gate.set()
                assert await worker
        else:
            assert await scheduler.run_once()
        await db.refresh(child)
        if discovery == "approved":
            assert task_service.is_paused_for(child, task_service.PAUSE_APPROVAL)
            approval = await db.scalar(select(ActionAuthorization).where(
                ActionAuthorization.agent_id == agent.id, ActionAuthorization.context_key == f"task:{child.id}",
            ))
            assert approval is not None and approval.capability_name == "record_apricots" and receipts == []
            assert await answer_action(approval.id, user_id=user.id, approved=True)
            monkeypatch.setattr(runner, "go_next", lambda *_args, **_kwargs: None)
            assert await wake_authorization_context(agent.id, f"task:{child.id}")
            assert await scheduler.run_once()
            await db.refresh(child)
        assert child.status == TaskStatus.SUCCESS and "Bonjour !" in child.get_execution_result().result
        await db.refresh(parent)
        if parent.status != TaskStatus.SUCCESS:
            assert await scheduler.run_once()
            await db.refresh(parent)
        assert parent.status == TaskStatus.SUCCESS and "Synthetic plan completed." in parent.feedback
        assert planner_calls == [(Plan, parent.id), (str, parent.id)]
        expected_calls = {"eager": 2, "approved": 5}.get(discovery, 4)
        assert len(requests) == expected_calls
        assert receipts == ([] if discovery in {"revoked", "native"} else ["one fictional apricot"])
        initial = {item["function"]["name"] for item in requests[0]["tools"]}
        assert (f"mcp__galaris__{tool_name}" in initial) is (discovery == "eager")
        if discovery != "eager":
            assert {search_name, alias, f"mcp__galaris__{anchor_name}"} <= initial
            assert "Use an exact tool name from a search result" in json.dumps(requests[1]["messages"])
            search_receipt = [item for item in requests[2]["messages"] if item["role"] == "tool"][-1]
            assert tool_name in json.dumps(search_receipt) and "input_schema" in json.dumps(search_receipt)
            assert all(blocked_name not in json.dumps(body) for body in requests)
        final_messages = json.dumps(requests[-1]["messages"])
        if discovery == "approved":
            assert "Galaris has resolved the earlier tool authorization" in final_messages
            assert "Galaris catalog results expire" in final_messages and "input_schema" not in final_messages
        if discovery == "revoked":
            assert "This discovered Galaris tool is no longer available." in final_messages
        elif discovery == "native":
            assert "document_formats" in final_messages
        else:
            assert "Synthetic apricots recorded." in final_messages
        result_messages = child.get_execution_result().messages
        [physical] = [message for message in result_messages if message.tool_name == tool_name]
        assert physical.tool_arguments == args and physical.tool_call_external_id and physical.success is (discovery != "revoked")
        assert all(message.tool_name != "call_discovered_tool" for message in result_messages)
        calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id)))
        assert len(calls) == expected_calls
        execution_attempts = list(await db.scalars(select(TaskAttempt).where(
            TaskAttempt.task_id == child.id, TaskAttempt.phase == TaskStatus.DISPATCH.value,
        ).order_by(TaskAttempt.attempt_number)))
        assert {call.task_attempt_id for call in calls} == {attempt.id for attempt in execution_attempts}
        if discovery == "approved":
            [resumed_call] = [call for call in calls if call.task_attempt_id == execution_attempts[-1].id]
            assert "Galaris has resolved the earlier tool authorization" in json.dumps(resumed_call.request_messages)
        for call in calls:
            assert call.task_id == child.id and call.requester_user_id == user.id and call.purpose == "agent.exec"
            assert call.task_attempt_id is not None and call.agent_run_id is not None
            assert step_objective in json.dumps(call.request_messages)
        assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize(("wait", "lose_worker", "early_reply"), [
    pytest.param(True, False, False, id="wait-after-batch"),
    pytest.param(False, False, False, id="continue-independent-work"),
    pytest.param(True, True, False, id="recover-before-terminal"),
    pytest.param(True, False, True, id="reply-before-parent-parks"),
])
async def test_embedded_peer_request_drains_the_batch_and_parent_resumes_once(
    runtime, committed_database, monkeypatch, tmp_path, wait, lose_worker, early_reply, driver,
):
    from app.agent import facade as agent_facade
    from app.agent.models import AgentTeam
    from app.task import collab
    from core.team import TeamModel

    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(runner, "go_next", lambda *_args, **_kwargs: None)
    provider_receipts = []
    mode.update(concurrent=True, chat_response_ids=provider_receipts)
    title = await db.scalar(select(Title.id).limit(1))
    chat = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
    files = await db.scalar(select(ServiceModel).where(ServiceModel.code == "file_sharing"))
    assert title is not None and chat is not None and files is not None
    user = User(email=f"claude-peer-{uuid4().hex}@example.test", hashed_password="unused")
    peer_user = User(email=f"claude-colleague-{uuid4().hex}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic peer profile", text_standard_llm_id=model.id)
    team = TeamModel(name=f"Synthetic collaborators {uuid4().hex}")
    db.add_all([user, peer_user, profile, team])
    await db.flush()
    parent_agent = Agent(code=f"claude-parent-{uuid4().hex}", user_id=user.id, first_name="Parent", last_name="Agent",
                         title_id=title, profile_id=profile.id, agent_driver=driver)
    peer = Agent(code=f"claude-peer-{uuid4().hex}", user_id=peer_user.id, first_name="Peer", last_name="Agent",
                 title_id=title, profile_id=profile.id, agent_driver="internal")
    db.add_all([parent_agent, peer])
    await db.flush()
    db.add_all([AgentTeam(agent_id=agent.id, team_id=team.id) for agent in (parent_agent, peer)])
    db.add_all([Connection(agent_id=agent.id, service_id=chat.id, active=True) for agent in (parent_agent, peer)])
    db.add(Connection(agent_id=parent_agent.id, service_id=files.id, active=True))
    db.add(MessengerUser(service_id=chat.id, agent_id=peer.id, external_id=f"agent:{peer.id}", is_ai=True))
    parent = Task(label="Synthetic peer collaboration", objective="<p>Ask the synthetic peer and save a receipt.</p>",
                  agent=parent_agent, requester_user_id=user.id, status=TaskStatus.DISPATCH, ai=True,
                  forced_route="EXEC", forced_effort="standard", data={"language": "en"})
    db.add(parent)
    await db.commit()
    note = "Synthetic pear count is seven"
    tool = "messenger_send_message_to_user"
    parent_id = parent.id
    original_stream = agent_facade.stream
    interrupted = replied = False

    async def inject_after_tool_receipt(request):
        nonlocal interrupted, replied
        observed = set()
        async with aclosing(original_stream(request)) as events:
            async for event in events:
                if (request.task_id == parent_id and event.message is not None
                        and event.message.type == "tool" and event.message.success):
                    observed.add(event.message.tool_name)
                if early_reply and not replied and tool in observed:
                    replied = True
                    async with get_db_session():
                        [child] = await task_service.get_children(parent_id)
                        child.status, child.feedback = TaskStatus.SUCCESS, note
                        await task_service.save(child)
                        await collab.maybe_fan_in(parent_id)
                yield event
                if lose_worker and not interrupted and {tool, "file_schemes"} <= observed:
                    interrupted = True
                    raise ConnectionError("Synthetic worker lost after tool checkpoint")

    if early_reply or lose_worker:
        monkeypatch.setattr(agent_facade, "stream", inject_after_tool_receipt)

    def choose_tools(body):
        if len(requests) != 1:
            return []
        prefix = "mcp__galaris__" if driver == "claude_embedded" else ""
        assert {f"{prefix}{name}" for name in (tool, "file_schemes")} <= {
            item["function"]["name"] for item in body["tools"]
        }
        return [
            ("synthetic-peer-request", f"{prefix}{tool}", {"user": f"agent:{peer.id}",
                "channel": "internal", "message": "Count the fictional pears.", "wait_for_reply": wait}),
            ("synthetic-sibling-receipt", f"{prefix}file_schemes", {}),
        ]

    mode["tool_calls_for"] = choose_tools
    async with _gateway(monkeypatch), asyncio.timeout(55):
        assert await scheduler.run_once()
        await db.refresh(parent)
        [child] = await task_service.get_children(parent.id)
        assert child.requester_agent_id == parent_agent.id and child.agent_id == peer.id
        [first_attempt] = (await db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == parent.id))).all()
        if lose_worker:
            assert first_attempt.status == "RETRY" and interrupted
            assert len(requests) == 1 and parent.status == TaskStatus.DISPATCH
            saved = first_attempt.data["agent_checkpoint"]["result"]
            assert saved is None or saved["disposition"] != "waiting_for_children"
            # Keep the peer runnable only after the replacement parent has parked.
            task_service.suspend(child, task_service.PAUSE_USER)
            await task_service.save(child)
            parent.next_attempt_at = None
            await task_service.save(parent)
            assert await scheduler.run_once()
            await db.refresh(parent)
            parked = await db.scalar(select(TaskAttempt).where(TaskAttempt.task_id == parent.id,
                TaskAttempt.id != first_attempt.id))
            assert parked is not None
            assert {event["message"]["tool_name"] for event in first_attempt.data["agent_events"]
                    if event.get("message") and event["message"]["type"] == "tool"} >= {
                tool, "file_schemes"
            }
            [paid] = (await db.scalars(select(LLMCall).where(LLMCall.task_id == parent.id))).all()
            assert paid.inference_cost > 0 and parent.cost == pytest.approx(paid.inference_cost)
        else:
            parked = first_attempt
        partial = parent.get_execution_result()
        assert partial is not None
        if not lose_worker:
            receipts = {message.tool_name: message for message in partial.messages if message.type == "tool"}
            assert receipts[tool].success and receipts["file_schemes"].success
        if early_reply:
            assert replied and not parent.paused and parent.status == TaskStatus.DISPATCH
        else:
            assert parked.status == "WAITING_CHILDREN" and task_service.is_paused_for(parent, task_service.PAUSE_CHILD)
        assert parked.error is None and "partial_execution_failure" not in parked.data
        assert len(requests) == (1 if wait else 2)
        assert partial.disposition == ("waiting_for_children" if wait else "completed")
        assert parked.data["agent_checkpoint"]["status"] == ("waiting_for_children" if wait else "completed")
        assert parked.data["agent_checkpoint"]["result"]["disposition"] == partial.disposition

        if not early_reply:
            task_service.release(child, task_service.PAUSE_USER)
            child.status, child.feedback = TaskStatus.SUCCESS, note
            await task_service.save(child)
            await collab.maybe_fan_in(parent.id)
            await db.commit()
        await db.refresh(parent)
        assert not parent.paused and note in parent.data[collab.COLLAB_CONTEXT_KEY]
        assert await scheduler.run_once()
        await db.refresh(parent)
        assert parent.status == TaskStatus.SUCCESS and "Bonjour !" in parent.get_execution_result().result
        assert note in json.dumps(requests[-1]["messages"])
        [same_child] = await task_service.get_children(parent.id)
        assert same_child.id == child.id

    calls = (await db.scalars(select(LLMCall).where(LLMCall.task_id == parent.id).order_by(LLMCall.started_at))).all()
    assert len(calls) == len(requests) == (2 if wait else 3)
    assert [call.upstream_request_id for call in calls] == provider_receipts
    assert parent.cost == pytest.approx(sum(call.inference_cost for call in calls))
    assert {call.requester_user_id for call in calls} == {user.id}
    assert calls[0].agent_run_id is not None and calls[-1].agent_run_id is not None
    assert calls[0].agent_run_id != calls[-1].agent_run_id
    assert calls[0].task_attempt_id == first_attempt.id != calls[-1].task_attempt_id
