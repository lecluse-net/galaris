"""Native AI activities ask through messaging and submit validated data receipts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.agent import ExecutionResult
from app.agent.executor_service import _update_task_after_execution
from app.connection import Connection
from app.conversation import ProcessHumanMessenger, ConversationTurn
from app.conversation.models import ConversationRound, ConversationRoundMessage, ConversationProcessLink
from app.conversation.mcp import conversation_process_respond, conversation_process_start
from app.memory import read_workflow_document
from app.messenger import Room, RoomUser, Message, MessengerUser, Interaction
from app.process import human_directory, process_service
from app.process.bpmn import Workflow, Node, Flow, Actor
from app.process.human_requests import deliver_human_requests
from app.process.mcp import process_activity_complete, process_activity_question
from app.process.models import ProcessRun, ProcessNodeRun, ProcessNodeAttempt
from app.process.native_definitions import create
from app.process.values import Variable
from app.task import TaskCreate, TaskStatus, task_service
from app.task.workflow import transition, TaskEvent
from app.tools import McpToolContext
from app.tools.models import Tool
from app.tools import RecoverableToolError
from core.user import UserModel

from .test_native_bpmn import native as native, committed_native as committed_native


async def setup_activity(db, native, monkeypatch, *, delegated=False, human_manager=True):
    owner, other = native
    user = UserModel(email=f"synthetic-input-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add(user); await db.flush()
    if human_manager:
        owner.user_id = user.id
    age = Variable(name="age", type="int", nullable=False)
    graph = Workflow(schema_version="galaris.bpmn/v2", inputs=[], outputs=[], nodes=[
        Node(id="start", kind="start"), Node(id="collect", kind="task", title="Collect synthetic age",
            config={"prompt": "Ask the human for their age."}, inputs=[], outputs=[age]),
        Node(id="describe", kind="task", title="Describe synthetic age",
            config={"prompt": "Read age from the Dataset and describe it."}, inputs=[], outputs=[]),
        Node(id="end", kind="end")], flows=[Flow(id="a", source="start", target="collect"),
            Flow(id="b", source="collect", target="describe"), Flow(id="c", source="describe", target="end")])
    if delegated:
        other.user_id = user.id
        graph.actors = [Actor(id="performer", name="Synthetic performer", kind="agent", agent_id=other.id)]
        graph.nodes[1].config["actor"] = "performer"
    definition = await create(actor_agent_id=owner.id, title="Synthetic interactive process", graph=graph)
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    connection = Connection(agent_id=owner.id, tool_id=chat.id, active=True)
    db.add(connection); await db.flush()
    room = Room(connection_id=connection.id, external_id="synthetic-activity-origin",
        label="Synthetic origin", kind="direct", conversation_type="text")
    sender = MessengerUser(tool_id=chat.id, external_id=f"user:{user.id}",
        display_name="Synthetic requester", is_ai=False, galaris_user_id=user.id)
    bot = MessengerUser(tool_id=chat.id, external_id=f"agent:{owner.id}",
        display_name="Synthetic agent", is_ai=True, agent_id=owner.id)
    db.add_all([room, sender, bot]); await db.flush()
    db.add_all([RoomUser(room_id=room.id, user_id=sender.id), RoomUser(room_id=room.id, user_id=bot.id)])
    round_ = ConversationRound(room_id=room.id, requester_user_id=user.id, status="SUCCEEDED")
    message = Message(connection_id=connection.id, tool_id=chat.id, platform="internal",
        direction="inbound", text="Launch the synthetic process", remote_message_id=uuid4().hex,
        messenger_room_id=room.id, sender_messenger_user_id=sender.id, requester_user_id=user.id)
    db.add_all([round_, message]); await db.flush()
    db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
    await db.commit()
    turn = ConversationTurn(room_id=room.id, round_id=round_.id, agent_id=owner.id, language="en",
        objective=message.text, messages=({"text": message.text},), messaging_context={
            "connection_id": connection.id, "requester_user_id": user.id})
    launch_ctx = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    # Only this admission's provider is replaced. The remaining workflow keeps
    # its real profile, MCP, messaging and Task implementations.
    from app.conversation.tests.test_process_admission import provider
    with monkeypatch.context() as launch_patch:
        provider(launch_patch, [{"workflow_id": definition.code, "input": {}}])
        launched = await conversation_process_start(launch_ctx, workflow_id=definition.code)
    run_id = UUID(launched["run_id"])
    assert (await db.get(ProcessRun, run_id)).requester_user_id == (user.id if human_manager else None)
    replay = await conversation_process_start(launch_ctx, workflow_id=definition.code)
    assert replay["run_id"] == str(run_id) and replay["created"] is False
    assert await db.scalar(select(func.count()).select_from(ConversationProcessLink).where(
        ConversationProcessLink.round_id == round_.id)) == 1
    await db.commit()
    monkeypatch.setattr(human_directory, "_messenger", ProcessHumanMessenger())
    monkeypatch.setattr(human_directory, "_directory", SimpleNamespace(list_humans=AsyncMock(return_value=())))
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4): await process_service.refresh_run(run_id)
    attempt = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id))
    task = await task_service.get_by_id(attempt.task_id)
    transition(task, TaskEvent.START_EXECUTION)
    await task_service.save(task)
    return owner, other, user, run_id, room, task, attempt


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_timing,held,legacy,human_manager", [("after", False, False, True), ("before", False, False, True), ("after", True, False, True), ("after", False, True, True), ("after", False, False, False)])
async def test_ai_activity_asks_in_origin_room_resumes_and_passes_data_to_next_task(db, native, monkeypatch, reply_timing, held, legacy, human_manager):
    owner, _, user, run_id, room, task, attempt = await setup_activity(db, native, monkeypatch, human_manager=human_manager)
    if not human_manager:
        # Admission also serves ordinary participants on external messengers.
        # Internal Chat delivery itself requires Agent-management access.
        assert (await db.get(ProcessRun, run_id)).status == "running"
        assert task.status == TaskStatus.EXEC
        return
    ctx = McpToolContext(agent_id=owner.id, runtime="openai_messages", task_id=task.id)
    assert (await process_activity_question(ctx, "What is your age?"))["waiting_for_human"]
    assert (await process_activity_question(ctx, "What is your age?"))["waiting_for_human"]
    assert await task_service.get_children(task.id) == []
    if legacy:
        wait = await task_service.create(TaskCreate(label="Synthetic historical wait", agent_id=owner.id,
            parent_id=task.id, source_task_id=task.id, ai=False, paused=True, status=TaskStatus.DISPATCH,
            data={"pause_reasons": ["await"], "awaiting_reply": {"kind": "human_input", "deadline": None}}))
        occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
        occurrence.context = {**occurrence.context, "activity_question": {
            **occurrence.context["activity_question"], "wait_task_id": str(wait.id)}}
        task.data = {key: value for key, value in task.data.items() if key != "input_request"}
        task_service.release(task, task_service.PAUSE_INPUT)
        await task_service.save(task)
    with pytest.raises(ValueError, match="Wait for"):
        await process_activity_complete(ctx, {"age": 37})
    if reply_timing == "after":
        await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic driver", result="What is your age?"), base_cost=0)
        assert task.paused and task.status == TaskStatus.DISPATCH
    if held:
        task_service.suspend(task, task_service.PAUSE_USER)
        await task_service.save(task)
    await process_service.refresh_run(run_id)
    assert (await db.get(ProcessRun, run_id)).status == "running"
    if legacy:
        await db.refresh(wait)
        assert wait.deleted_at is not None and wait.status == TaskStatus.ERROR
        assert await task_service.get_children(task.id, refresh=True) == []
    assert await deliver_human_requests() == 1
    assert await deliver_human_requests() == 0
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "process_human_activity"))
    assert choice.room_id == str(room.id) and choice.metadata_["question_id"]
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=owner.id, language="en",
        objective="37", messages=({"text": "37"},), messaging_context={
            "connection_id": choice.connection_id, "tool_id": choice.tool_id,
            "participant_id": choice.user_id, "requester_user_id": user.id})
    reply_ctx = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    with pytest.raises(RecoverableToolError, match="expected type int"):
        await conversation_process_respond(reply_ctx, reference=choice.reference, output={"age": {"type": "string", "value": "37"}})
    for invalid in ({"age": "37"}, {"age": True}, {"age": 37, "unknown": 1}):
        with pytest.raises(RecoverableToolError):
            await conversation_process_respond(reply_ctx, reference=choice.reference, output=invalid)
    assert choice.status == "PENDING"
    output = {"age": {"type": "int", "value": 37}}
    await conversation_process_respond(reply_ctx, reference=choice.reference, output={"age": 37})
    assert not (await conversation_process_respond(reply_ctx, reference=choice.reference, output=output))["applied"]
    if reply_timing == "before":
        await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic driver", result="What is your age?"), base_cost=0)
    await db.refresh(task)
    if held:
        assert task.paused and task_service.is_held_by_user(task)
        task_service.release(task, task_service.PAUSE_USER)
        await task_service.save(task)
    assert not task.paused and task.status != TaskStatus.SUCCESS
    assert "37" in task.data["input_context"]
    transition(task, TaskEvent.START_EXECUTION)
    await task_service.save(task)
    assert (await process_activity_question(ctx, "What is your age?"))["response"] == output
    # A resumed model may rephrase its question. Its received answer must survive
    # that retry instead of opening a second human wait.
    question = (await db.get(ProcessNodeRun, attempt.node_run_id)).context["activity_question"]
    repeated = await process_activity_question(ctx, "Please tell me your age in years.")
    assert repeated["answered"] and repeated["response"] == output
    assert (await db.get(ProcessNodeRun, attempt.node_run_id)).context["activity_question"] == question
    assert not task.paused
    assert await deliver_human_requests() == 0
    assert await task_service.get_children(task.id) == []
    with pytest.raises(RecoverableToolError):
        await process_activity_complete(ctx, {"age": "bad"})
    assert await process_activity_complete(ctx, {"age": 37}) == {"accepted": True}
    assert await process_activity_complete(ctx, {"age": 37}) == {"accepted": True}
    with pytest.raises(ValueError, match="different result"):
        await process_activity_complete(ctx, {"age": 38})
    await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic driver", result="Collected the answer."), base_cost=0)
    for _ in range(6): await process_service.refresh_run(run_id)
    second = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(
        ProcessNodeRun.run_id == run_id, ProcessNodeRun.node_key == "describe"))
    assert second.task_id != task.id
    assert "age" in second.prompt and "37" in second.prompt
    second_task = await task_service.get_by_id(second.task_id)
    transition(second_task, TaskEvent.START_EXECUTION)
    await task_service.save(second_task)
    # An activity with no data outputs may finish with natural prose.
    await _update_task_after_execution(second_task, ExecutionResult(prompt="Synthetic driver", result="The synthetic person is 37."), base_cost=0)
    for _ in range(8): await process_service.refresh_run(run_id)
    run = await db.get(ProcessRun, run_id)
    assert run.status == "success", run.error_message
    assert run.output == {}
    assert run.engine_metadata["native"]["summary"] == "The synthetic person is 37."
    assert json.loads((await read_workflow_document(run.dataset_document_id, owner.id))["content"])["data"] == output
    assert await db.scalar(select(func.count()).select_from(ProcessNodeAttempt).where(ProcessNodeAttempt.node_run_id == attempt.node_run_id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("human_manager", [True, False])
async def test_delegated_activity_asks_and_receives_input_in_the_launch_conversation(db, native, monkeypatch, human_manager):
    if not human_manager:
        with pytest.raises(PermissionError, match="cannot assign another agent"):
            await setup_activity(db, native, monkeypatch, delegated=True, human_manager=False)
        assert not await db.scalar(select(ProcessRun.id).where(ProcessRun.launcher_agent_id == native[0].id))
        assert not await db.scalar(select(ConversationProcessLink.id))
        return
    owner, performer, user, run_id, room, task, _ = await setup_activity(db, native, monkeypatch, delegated=True)
    assert task.agent_id == performer.id
    ctx = McpToolContext(agent_id=performer.id, runtime="openai_messages", task_id=task.id)
    await process_activity_question(ctx, "What is your age?")
    await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic", result="Waiting"), base_cost=0)
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "process_human_activity"))
    assert choice is not None and choice.agent_id == owner.id and choice.room_id == str(room.id)
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=owner.id, language="en",
        objective="37", messages=({"text": "37"},), messaging_context={"connection_id": choice.connection_id,
            "tool_id": choice.tool_id, "participant_id": choice.user_id, "requester_user_id": user.id})
    reply = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    await conversation_process_respond(reply, reference=choice.reference, output={"age": 37})
    await db.refresh(task)
    assert task.agent_id == performer.id and not task.paused
    assert "37" in task.data["input_context"]
    assert (await db.get(ProcessRun, run_id)).status == "running"


@pytest.mark.asyncio
async def test_question_keys_keep_their_answer_when_later_questions_are_pending(db, native, monkeypatch):
    from app.process.activity_controls import answer_input

    owner, _, user, run_id, _, task, attempt = await setup_activity(db, native, monkeypatch)
    ctx = McpToolContext(agent_id=owner.id, runtime="openai_messages", task_id=task.id)
    await process_activity_question(ctx, "What is your age?", question_key="age-request")
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    first_id = UUID(occurrence.context["activity_question"]["id"])
    answer = {"age": {"type": "int", "value": 37}}
    run = await db.get(ProcessRun, run_id)
    await answer_input(run, occurrence, question_id=first_id, user_id=user.id, output=answer)
    await db.commit()
    occupation = [Variable(name="occupation", type="string", nullable=False)]
    await process_activity_question(ctx, "What is your occupation?", occupation, question_key="occupation-request")
    next_id = occurrence.context["activity_question"]["id"]
    assert (await process_activity_question(ctx, "An old age request retry", question_key="age-request"))["response"] == answer
    await answer_input(run, occurrence, question_id=first_id, user_id=user.id, output=answer)
    await db.commit()
    assert occurrence.context["activity_question"]["id"] == next_id
    assert occurrence.context["activity_question"]["status"] == "pending"
    assert task.data["input_request"]["key"] == next_id
    with pytest.raises(ValueError, match="variables"):
        await process_activity_question(ctx, "Changed request", occupation, question_key="age-request")


@pytest.mark.asyncio
async def test_old_question_snapshot_is_not_offered_after_a_followup_opens(db, native, monkeypatch):
    from app.process.activity_controls import answer_input
    from app.conversation.process_interactions import live_process_choices
    from app.messenger import list_pending_choices

    owner, _, user, run_id, _, task, attempt = await setup_activity(db, native, monkeypatch)
    ctx = McpToolContext(agent_id=owner.id, runtime="openai_messages", task_id=task.id)
    await process_activity_question(ctx, "What is your age?")
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "process_human_activity"))
    captured = await list_pending_choices(agent_id=owner.id, connection_id=choice.connection_id,
        tool_id=choice.tool_id, room_id=choice.room_id, user_id=choice.user_id)
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    await answer_input(await db.get(ProcessRun, run_id), occurrence,
        question_id=UUID(occurrence.context["activity_question"]["id"]), user_id=user.id,
        output={"age": {"type": "int", "value": 37}})
    await db.commit()
    await process_activity_question(ctx, "What is your occupation?", [Variable(name="occupation", type="string", nullable=False)])
    assert await live_process_choices(captured, requester_user_id=user.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_fails", [False, True])
async def test_withdrawal_of_an_old_question_cannot_close_a_new_question(db, native, monkeypatch, transport_fails):
    from app.process.activity_controls import answer_input
    from app.process.human_requests import withdraw_finished_requests

    owner, _, user, run_id, _, task, attempt = await setup_activity(db, native, monkeypatch)
    ctx = McpToolContext(agent_id=owner.id, runtime="openai_messages", task_id=task.id)
    await process_activity_question(ctx, "What is your age?")
    await deliver_human_requests()
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    old_id = UUID(occurrence.context["activity_question"]["id"])
    await answer_input(await db.get(ProcessRun, run_id), occurrence, question_id=old_id,
        user_id=user.id, output={"age": {"type": "int", "value": 37}})
    await db.commit()

    async def withdraw(**kwargs):
        assert kwargs["question_id"] == old_id
        await process_activity_question(ctx, "What is your occupation?", [Variable(name="occupation", type="string", nullable=False)])
        if transport_fails:
            raise OSError("Synthetic failed withdrawal")

    messenger = ProcessHumanMessenger()
    monkeypatch.setattr(messenger, "withdraw", withdraw)
    monkeypatch.setattr(human_directory, "_messenger", messenger)
    await withdraw_finished_requests()
    await db.refresh(occurrence)
    current_id = occurrence.context["activity_question"]["id"]
    assert current_id != str(old_id)
    assert occurrence.context["human_request_closed"] is None

    monkeypatch.setattr(human_directory, "_messenger", ProcessHumanMessenger())
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.metadata_["question_id"].as_string() == current_id))
    assert choice.status == "PENDING"
    await process_service.cancel_run(run_id)
    await withdraw_finished_requests()
    await db.refresh(choice)
    from app.messenger import list_pending_choices
    remaining = await list_pending_choices(agent_id=owner.id, connection_id=choice.connection_id,
        tool_id=choice.tool_id, room_id=choice.room_id, user_id=choice.user_id)
    assert choice.id not in {item.id for item in remaining}


@pytest.mark.asyncio
@pytest.mark.parametrize("ask_again", [False, True])
async def test_activity_can_request_new_information_without_losing_received_answers(db, native, monkeypatch, ask_again):
    from app.process.activity_controls import answer_input

    owner, _, user, run_id, _, task, attempt = await setup_activity(db, native, monkeypatch)
    ctx = McpToolContext(agent_id=owner.id, runtime="openai_messages", task_id=task.id)
    await process_activity_question(ctx, "What is your age?")
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    first_id = UUID(occurrence.context["activity_question"]["id"])
    await answer_input(await db.get(ProcessRun, run_id), occurrence, question_id=first_id,
        user_id=user.id, output={"age": {"type": "int", "value": 37}})
    await db.commit()
    variables = None if ask_again else [Variable(name="occupation", type="string", nullable=False)]
    question = "Please confirm your age." if ask_again else "What is your occupation?"
    key = "confirm-age" if ask_again else None
    assert (await process_activity_question(ctx, question, variables, question_key=key))["waiting_for_human"]
    current = occurrence.context["activity_question"]
    assert current["id"] != str(first_id) and current["status"] == "pending"
    assert "What is your age?" in task.data["input_context"]
    assert '"value": 37' in task.data["input_context"]
    assert await task_service.get_children(task.id) == []
    answer = {"age": {"type": "int", "value": 38}} if ask_again else {"occupation": {"type": "string", "value": "Synthetic occupation"}}
    await answer_input(await db.get(ProcessRun, run_id), occurrence, question_id=UUID(current["id"]),
        user_id=user.id, output=answer)
    await db.commit()
    assert (await process_activity_question(ctx, "A reworded retry", variables, question_key=key))["response"] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["process", "activity"])
async def test_activity_controls_reject_foreign_tasks_and_cancelled_questions(db, native, monkeypatch, stop):
    owner, other, user, run_id, _, task, attempt = await setup_activity(db, native, monkeypatch)
    with pytest.raises(PermissionError):
        await process_activity_complete(McpToolContext(agent_id=other.id, runtime="internal", task_id=task.id), {"age": 37})
    with pytest.raises(PermissionError):
        await process_activity_question(McpToolContext(agent_id=owner.id, runtime="internal"), "What is your age?")
    ctx = McpToolContext(agent_id=owner.id, runtime="internal", task_id=task.id)
    await process_activity_question(ctx, "What is your age?")
    occurrence = await db.get(ProcessNodeRun, attempt.node_run_id)
    question_id = UUID(occurrence.context["activity_question"]["id"])
    if stop == "process":
        await process_service.cancel_run(run_id)
    else:
        await task_service.cancel(task.id, task.revision)
        for _ in range(4): await process_service.refresh_run(run_id)
        assert (await db.get(ProcessRun, run_id)).error_code == "human_input_cancelled"
    from app.process.facade import complete_human_activity
    with pytest.raises(ValueError, match="no longer"):
        await complete_human_activity(attempt.id, question_id=question_id, user_id=user.id,
            output={"age": {"type": "int", "value": 37}})


@pytest.mark.asyncio
async def test_activity_tools_are_available_and_callable_through_the_real_mcp_boundary(inference_db, committed_native, monkeypatch):
    from fastmcp import Client
    from app.tools.mcp_loader import build_agent_galaris_fastmcp
    from app.tools.mandatory_tools import sync_integrated_tool_connections

    db = inference_db
    owner, _, _, _, _, task, _ = await setup_activity(db, committed_native, monkeypatch)
    await sync_integrated_tool_connections(owner.id)
    await db.commit()
    server = await build_agent_galaris_fastmcp(owner.id, runtime="internal", task_id=task.id)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {"process_activity_complete", "process_activity_question"} <= names
        invalid = await client.call_tool("process_activity_complete", {"output": {"age": "invalid"}}, raise_on_error=False)
        assert invalid.is_error and "int" in str(invalid.content)
        result = await client.call_tool("process_activity_question", {"question": "What is your age?"})
        assert not result.is_error
    assert await task_service.get_children(task.id, refresh=True) == []
    await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic MCP driver", result="Waiting for the reply."), base_cost=0)
    assert task.paused and task.status == TaskStatus.DISPATCH


@pytest.mark.asyncio
async def test_managed_deepseek_http_mcp_uses_its_driver_and_keeps_activity_task_scope(inference_db, committed_native, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from httpx import ASGITransport, AsyncClient
    from app.agent import AgentSnapshot, ResolvedExecutionTarget
    from app.agent.tests.test_driver_testkit import _request
    from app.harnesses.models import AgentHarness
    from app.mcp.service import rotate_system_token
    from app.tools.facade import issue_runtime_run_grant
    from app.tools.mandatory_tools import sync_integrated_tool_connections
    from app.task import scheduler
    from app.task.models import TaskAttempt
    from main import app

    db = inference_db
    owner, _, _, _, _, task, _ = await setup_activity(db, committed_native, monkeypatch)
    lease = uuid4()
    task.lease_token = lease
    task.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    db.add(TaskAttempt(task_id=task.id, attempt_number=1, phase="DISPATCH",
        status="CLAIMED", worker_id="synthetic-http-runtime", lease_token=lease))
    assignment = AgentHarness(agent_id=owner.id, provider_code="deepseek_harness",
        lifecycle_status="ready", runtime_base_url="http://synthetic-harness.invalid/v1",
        runtime_model="synthetic", provider_metadata={"authorization_enabled": True})
    db.add(assignment)
    await db.flush()
    assignment_id = assignment.id
    bearer = await rotate_system_token(owner.id)
    await sync_integrated_tool_connections(owner.id)
    await db.commit()
    request = replace(_request(), task_id=task.id, driver_code="openai_messages",
        agent=AgentSnapshot(id=owner.id, code=owner.code, first_name="Synthetic", last_name="Runtime", driver_code="openai_messages"),
        target=ResolvedExecutionTarget(provider_code="deepseek_harness", target_ref=f"harness:{assignment_id}", revision="1"))
    credential = await issue_runtime_run_grant(request)
    headers = {"Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": credential,
        "Accept": "application/json, text/event-stream"}
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://localhost") as client:
        async def invoke(method, params=None):
            response = await client.post(f"/api/mcp/{owner.code}", headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
            assert response.status_code == 200, response.text
            payload = next(json.loads(line[5:].strip()) for line in response.text.splitlines()
                if line.startswith("data:")) if response.headers.get("Content-Type", "").startswith("text/event-stream") else response.json()
            assert "error" not in payload, payload
            return payload["result"]

        catalog = await invoke("tools/list")
        assert {"process_activity_complete", "process_activity_question"} <= {tool["name"] for tool in catalog["tools"]}
        asked = await invoke("tools/call", {"name": "process_activity_question",
            "arguments": {"question": "What is your age?"}})
        assert not asked.get("isError"), asked
    await db.refresh(task)
    assert not task.paused and await scheduler._renew_lease(task.id, lease)
    await db.commit()
    assert await task_service.get_children(task.id, refresh=True) == []
    await _update_task_after_execution(task, ExecutionResult(prompt="Synthetic HTTP driver", result="Waiting for the reply."), base_cost=0)
    assert task.paused and task.status == TaskStatus.DISPATCH
    await scheduler._complete_claim(task.id, TaskStatus.DISPATCH, lease)
    await db.refresh(task)
    assert task.lease_token is None and task.paused and task.status == TaskStatus.DISPATCH


@pytest.mark.asyncio
@pytest.mark.parametrize("followup,transport_loss", [(False, False), (True, False), (False, True)])
async def test_managed_activity_continues_after_human_reply_with_a_new_runtime_run(inference_db, committed_native, monkeypatch, followup, transport_loss):
    import asyncio
    import hashlib
    import httpx
    from app.agent import agent_skill_revision
    from app.harnesses.driver import OpenAIMessagesDriver
    from app.harnesses.models import AgentHarness
    from app.harnesses.openai_client import OpenAIHarnessClient
    from app.llm.profile_models import LlmProfile
    from app.llm.provider_models import LLM, LLMProvider
    from app.mcp.service import rotate_system_token
    from app.task import scheduler
    from app.conversation.service import claim_next_process_notification, deliver_process_notification
    from app.tools.mandatory_tools import sync_integrated_tool_connections
    from main import app

    db = inference_db
    owner, _, user, run_id, room, task, _ = await setup_activity(db, committed_native, monkeypatch)
    provider = LLMProvider(name="Synthetic managed model", base_url="https://model.example.invalid")
    db.add(provider); await db.flush()
    model = LLM(llm_provider_id=provider.id, code="synthetic-managed", llm_name="synthetic", label="Synthetic")
    db.add(model); await db.flush()
    profile = LlmProfile(code="synthetic-managed", label="Synthetic", text_standard_llm_id=model.id)
    db.add(profile); await db.flush()
    owner.profile_id = profile.id
    owner.agent_driver = "openai_messages"
    await sync_integrated_tool_connections(owner.id)
    bearer = await rotate_system_token(owner.id)
    db.add(AgentHarness(agent_id=owner.id, provider_code="deepseek_harness",
        lifecycle_status="ready", runtime_base_url="http://synthetic-harness.invalid/v1", runtime_model="synthetic",
        capabilities=["execute", "streaming", "checkpoints"],
        provider_metadata={"authorization_enabled": True, "skill_revision": await agent_skill_revision(owner.id)}))
    transition(task, TaskEvent.INTERRUPT_EXECUTION)
    await task_service.save(task)
    started = []
    results = {}
    lost_reply = False

    async def respond(request):
        nonlocal lost_reply
        if request.url.path.endswith("/galaris/capabilities"):
            return httpx.Response(200, json={"authorization_protocol": "galaris.runtime-authorization/v1", "resumable_runs": True})
        if request.method == "POST":
            identifier = hashlib.sha256(request.headers["X-Galaris-Run-Context"].encode()).hexdigest()
            started.append(identifier)
            if len(started) <= 2:
                name = "process_activity_question" if len(started) == 1 else "process_activity_complete"
                arguments = {"question": "What is your age?"} if len(started) == 1 else {"output": {"age": 37}}
                if len(started) == 2:
                    context = json.loads(request.content)["messages"][0]["content"]
                    assert "What is your age?" in context
                    assert '"response": {"age": {"type": "int", "value": 37}}' in context
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as mcp:
                    if len(started) == 2:
                        repeated = await mcp.post(f"/api/mcp/{owner.code}", headers={
                            "Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": request.headers["X-Galaris-Run-Context"],
                            "Accept": "application/json, text/event-stream"},
                            json={"jsonrpc": "2.0", "id": "retry", "method": "tools/call", "params": {
                                "name": "process_activity_question", "arguments": {"question": "Please tell me your age in years."}}})
                        repeated_payload = next(json.loads(line[5:].strip()) for line in repeated.text.splitlines() if line.startswith("data:"))
                        assert not repeated_payload["result"].get("isError"), repeated_payload
                        answer = repeated_payload["result"]["structuredContent"]
                        assert answer["answered"]
                        arguments = {"output": {"age": answer["response"]["age"]["value"]}}
                    response = await mcp.post(f"/api/mcp/{owner.code}", headers={
                        "Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": request.headers["X-Galaris-Run-Context"],
                        "Accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
                    assert response.status_code == 200, response.text
                    payload = next(json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:"))
                    assert "error" not in payload and not payload["result"].get("isError"), payload
                results[identifier] = "Waiting for the human." if len(started) == 1 else "Collected the answer."
            else:
                assert "37" in request.content.decode()
                if followup and len(started) == 3:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as mcp:
                        response = await mcp.post(f"/api/mcp/{owner.code}", headers={
                            "Authorization": f"Bearer {bearer}", "X-Galaris-Run-Context": request.headers["X-Galaris-Run-Context"],
                            "Accept": "application/json, text/event-stream"},
                            json={"jsonrpc": "2.0", "id": "followup", "method": "tools/call", "params": {
                                "name": "process_activity_question", "arguments": {"question": "What is your occupation?",
                                    "variables": [{"name": "occupation", "type": "string", "nullable": False}]}}})
                        payload = next(json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:"))
                        assert not payload["result"].get("isError"), payload
                    results[identifier] = "Waiting for the occupation."
                else:
                    if followup:
                        assert "Synthetic occupation" in request.content.decode()
                    results[identifier] = "The synthetic person is 37."
            return httpx.Response(200, json={"runtime_run_id": identifier})
        identifier = request.url.path.rsplit("/", 1)[-1]
        if transport_loss and not lost_reply:
            lost_reply = True
            raise httpx.ReadError("Synthetic lost runtime reply", request=request)
        return httpx.Response(200, json={"runtime_run_id": identifier, "status": "completed", "result": results[identifier]})

    client = OpenAIHarnessClient(base_url="http://synthetic-harness.invalid/v1", token="synthetic", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(OpenAIMessagesDriver, "_client", AsyncMock(return_value=client))
    async def execute(current):
        await db.commit()
        assert await asyncio.wait_for(scheduler.run_once(), timeout=20)
        await db.refresh(current)
        return current.get_execution_result()

    first_result = await execute(task)
    if not transport_loss:
        assert first_result.success
    await db.refresh(task)
    assert task.status == TaskStatus.DISPATCH
    assert task.paused == (not transport_loss)
    assert await task_service.get_children(task.id) == []
    await process_service.refresh_run(run_id)
    await deliver_human_requests()
    if followup:
        from app.process import registry
        from app.process.native_engine import NativeProcessEngine
        from app.process.native_runs import control_run
        registry.register(NativeProcessEngine())
        await control_run(run_id, owner.id, "pause")
    choice = await db.scalar(select(Interaction).where(Interaction.kind == "process_human_activity"))
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=owner.id, language="en",
        objective="37", messages=({"text": "37"},), messaging_context={"connection_id": choice.connection_id,
            "tool_id": choice.tool_id, "participant_id": choice.user_id, "requester_user_id": user.id})
    reply = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    await conversation_process_respond(reply, reference=choice.reference, output={"age": 37})
    if transport_loss:
        # Expediting the persisted timer replaces only the clock boundary. The
        # scheduler must reconcile the existing remote turn before a fresh turn.
        await db.refresh(task)
        task.next_attempt_at = None
        await task_service.save(task)
        assert (await execute(task)).success
        assert task.status == TaskStatus.DISPATCH and not task.paused
        assert len(started) == 1
    assert (await execute(task)).success
    for _ in range(6): await process_service.refresh_run(run_id)
    if followup:
        assert await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id,
            ProcessNodeRun.node_key == "describe")) is None
        await control_run(run_id, owner.id, "resume")
        for _ in range(6): await process_service.refresh_run(run_id)
    second = await db.scalar(select(ProcessNodeAttempt).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run_id,
        ProcessNodeRun.node_key == "describe"))
    second_task = await task_service.get_by_id(second.task_id)
    assert (await execute(second_task)).success
    if followup:
        assert second_task.paused and second_task.status == TaskStatus.DISPATCH
        await deliver_human_requests()
        pending = await db.scalar(select(Interaction).where(Interaction.kind == "process_human_activity", Interaction.status == "PENDING"))
        assert pending.id != choice.id
        # A repeated reply to the first question cannot wake the second Task.
        assert not (await conversation_process_respond(reply, reference=choice.reference, output={"age": 37}))["applied"]
        await db.refresh(second_task)
        assert second_task.paused
        await conversation_process_respond(reply, reference=pending.reference, output={"occupation": "Synthetic occupation"})
        assert (await execute(second_task)).success
    for _ in range(8): await process_service.refresh_run(run_id)
    run = await db.get(ProcessRun, run_id)
    assert run.status == "success", run.error_message
    assert run.engine_metadata["native"]["summary"] == "The synthetic person is 37."
    assert json.loads((await read_workflow_document(run.dataset_document_id, owner.id))["content"])["data"] == {"age": {"type": "int", "value": 37}}
    assert len(set(started)) == len(started) == (4 if followup else 3)
    assert "_agent_run_checkpoint" not in task.data
    assert not await scheduler.run_once()
    notification_id = await claim_next_process_notification()
    assert notification_id is not None
    await deliver_process_notification(notification_id)
    assert await claim_next_process_notification() is None
    assert await db.scalar(select(func.count()).select_from(Message).where(
        Message.messenger_room_id == room.id, Message.direction == "outbound",
        Message.text.contains("The synthetic person is 37."))) == 1
