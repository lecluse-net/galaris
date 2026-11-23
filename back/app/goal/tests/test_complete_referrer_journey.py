"""Goal → dispatcher → native harness/MCP → Chat wait → answer → judgement.

Only the external model is scripted. Database commits, scheduling, authorization,
the native Chat journal, interaction correlation and driver execution are real.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import func, select

from app.agent import agent_service
from app.agent.models import Title
from app.agent.schemas import AgentCreate
from app.connection import Connection, facade as connections
from app.document.models import Document
from app.goal import goal_service, referrer_wait, runner
from app.goal.models import Goal, GoalCycle, GoalStatus, GoalVerdict
from app.goal.schemas import GoalCreate, GoalMessengerReferrerInput
from app.llm import LLM, LLMProvider
from app.llm.profile_models import LlmProfile
from app.llm.models import LLMCall
from app.messenger import create_internal_room, publish_internal_message
from app.messenger.models import Interaction, Message
from app.task import scheduler, task_service
from app.task.models import Task, TaskStatus
from app.task.workflow import TaskEvent, transition
from app.services import ServiceModel
from app.services.authorization import answer_action
from app.services.authorization_notifications import reconcile_authorizations
from app.services.authorization_models import ActionAuthorization
from core.database import get_db_session
from core.user import UserModel, user_service


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["fr", "en"])
@pytest.mark.parametrize(("late_answer", "revoke_question", "approval_tool", "failed_cycles"), [
    (False, False, None, 0), (True, False, None, 0), (False, True, None, 0),
    (False, False, "messenger_send_message_to_user", 0), (False, False, "goal_update_suivi", 0),
    pytest.param(False, False, None, 1, id="answer-after-cycle-error"),
    pytest.param(False, False, None, 2, id="answer-survives-recovery-error"),
])
async def test_complete_human_decision_journey(inference_db, monkeypatch, language, late_answer, revoke_question, approval_tool, failed_cycles):
    db = inference_db
    owner = UserModel(email=f"goal-owner-{uuid4().hex}@example.test", display_name="Synthetic owner",
                      hashed_password="unused", is_active=True, language=language)
    outsider = UserModel(email=f"goal-outsider-{uuid4().hex}@example.test", display_name="Synthetic outsider",
                         hashed_password="unused", is_active=True)
    title = Title(label="Synthetic qualification", gender="X")
    provider = LLMProvider(name=f"synthetic-{uuid4().hex}", base_url="https://example.test/v1")
    db.add_all([owner, outsider, title, provider])
    await db.flush()
    # This journey exercises real approval decisions with their explicit privilege.
    from core.authorize import Assignment, Privilege, Role
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "PERMISSION_DECIDE"))
    role = Role(code=f"goal-approver-{uuid4().hex}", privileges=[privilege])
    db.add(role)
    await db.flush()
    db.add(Assignment(user_id=owner.id, role_id=role.id))
    llm = LLM(llm_provider_id=provider.id, code=f"synthetic-{uuid4().hex}",
              llm_name="synthetic", label="Synthetic boundary", context_length=128000)
    db.add(llm)
    await db.flush()
    profile = LlmProfile(code=f"synthetic-{uuid4().hex}", label="Qualification",
                         text_low_llm_id=llm.id, text_standard_llm_id=llm.id,
                         text_high_llm_id=llm.id)
    db.add(profile)
    await db.flush()
    agent = await agent_service.create(AgentCreate(user_id=owner.id, title_id=title.id, profile_id=profile.id,
                  code=f"qualified-{uuid4().hex}", first_name="Synthetic", last_name="Operator",
                  agent_driver="internal", job_description="<p>Obtain authorized decisions and record evidence. Create content only when the mission requires it.</p>"),
                  actor_user_id=owner.id)
    connection = await db.scalar(select(Connection).join(ServiceModel).where(
        Connection.agent_id == agent.id, ServiceModel.code == "goal"))
    assert connection is not None
    native_connection_id = connection.id
    await connections.set_connection_function_state(connection.id, "goal_ask_referrer", "enabled")
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    assert room is not None
    agent_id, owner_id, outsider_id, room_id = agent.id, owner.id, outsider.id, room.id
    profile_id = profile.id
    connection_id = room.connection_id
    initial_documents = await db.scalar(select(func.count()).select_from(Document))
    user_service.set_current_user(owner)
    try:
        goal = await goal_service.create(GoalCreate(
            title="Confirmer le choix de livraison" if language == "fr" else "Confirm delivery decision",
            description=("<p>Obtenir du référent son choix entre standard et express. Ne pas choisir à sa place. "
                         "Le goal est atteint quand sa réponse authentifiée est reçue et consignée.</p>"
                         if language == "fr" else
                         "<p>Obtain the referrer's choice between standard and express. Do not choose for them. "
                         "The Goal is achieved when their authenticated answer is received and recorded.</p>"),
            agent_id=agent_id,
            referrer=GoalMessengerReferrerInput(type="MESSENGER", connection_id=connection_id,
                                                user_id=f"user:{owner_id}", display_name="Synthetic owner"),
        ))
    finally:
        user_service.set_current_user(None)
    goal_id = goal.id
    tracking_uri = f"document://{goal.tracking_document_id}"

    stages: list[str] = []

    # Only the external provider boundary is replaced. The decision admission,
    # durable inference, call accounting and Goal transition remain real.
    from app.llm.facade import ProviderDecisionResponse
    from app.llm.decision_contracts import ChoiceAnswer

    class SyntheticDecisionProvider:
        async def decide(self, connection, *, model, state, questions, timeout_seconds):
            stages.append("judge")
            assert set(questions) == {"action"}
            assert "Authenticated referrer answer received: express" in state or revoke_question
            return ProviderDecisionResponse(model=model, answers={"action": ChoiceAnswer(
                choice="CONTINUE" if revoke_question else "STOP")})

    decision_llm = LLM(llm_provider_id=provider.id, code=f"synthetic-decision-{uuid4().hex}",
        llm_name="synthetic-decision", label="Synthetic decision boundary",
        primary_capability="decision", service_capabilities=["decision"])
    db.add(decision_llm)
    await db.flush()
    # Keep dispatcher routing on its text path; enable the specialist only when
    # the completed cycle reaches monitoring below.
    decision_llm_id = decision_llm.id
    monkeypatch.setattr("app.llm.decision_service.decision_provider_for", lambda _connection: SyntheticDecisionProvider())

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.test"
        body = json.loads(request.content)
        functions = [tool["function"] for tool in body.get("tools", [])]
        output = next((tool for tool in functions
                       if {"route", "effort"} <= tool.get("parameters", {}).get("properties", {}).keys()), None)
        tool_name = None
        value = None
        text = None
        if output is not None:
            stages.append("dispatch")
            value = {"route": "EXEC", "effort": "standard", "language": language,
                     "organization": "direct", "clarification_questions": []}
            tool_name = output["name"]
        elif "SYNTHETIC-ANSWER: express" in str(body["messages"]):
            confirmed = any(call["function"]["name"] == approval_tool
                            for message in body["messages"] for call in message.get("tool_calls", []))
            if approval_tool == "goal_update_suivi" and not confirmed:
                read_ids = {call["id"] for message in body["messages"] for call in message.get("tool_calls", [])
                            if call["function"]["name"] == "file_read"
                            and json.loads(call["function"]["arguments"]).get("uri") == f"galaris://goal/{goal_id}"}
                reads = [message for message in body["messages"]
                         if message.get("role") == "tool" and message.get("tool_call_id") in read_ids]
                if not reads:
                    stages.append("inspect")
                    tool_name, value = "file_read", {"uri": f"galaris://goal/{goal_id}"}
                else:
                    stages.append("record")
                    revision = json.loads(reads[-1]["content"])["revision"]
                    tool_name, value = "goal_update_suivi", {"goal_id": str(goal_id), "expected_revision": revision,
                        "tracking_content": "<p>Authenticated referrer choice: express.</p>"}
            elif approval_tool and not confirmed:
                stages.append("confirm")
                tool_name = approval_tool
                value = {"user": f"user:{owner_id}", "message": "Authenticated choice recorded: express."}
            else:
                stages.append("resume")
                text = "Authenticated referrer answer received: express. The requested decision is recorded."
        elif any(call["function"]["name"] == "goal_ask_referrer"
                 for message in body["messages"] for call in message.get("tool_calls", [])):
            stages.append("wait")
            text = ("Question permission denied; the delivery choice remains unknown."
                    if revoke_question else "Question sent; waiting for the referrer's answer.")
        elif not any(call["function"]["name"] == "file_read"
                     and json.loads(call["function"]["arguments"]).get("uri") == tracking_uri
                     for message in body["messages"] for call in message.get("tool_calls", [])):
            stages.append("read_tracking")
            tool_name, value = "file_read", {"uri": tracking_uri}
        else:
            stages.append("ask")
            tracking_reads = {call["id"] for message in body["messages"] for call in message.get("tool_calls", [])
                              if call["function"]["name"] == "file_read"
                              and json.loads(call["function"]["arguments"]).get("uri") == tracking_uri}
            receipts = [json.loads(message["content"]) for message in body["messages"]
                        if message.get("role") == "tool" and message.get("tool_call_id") in tracking_reads]
            assert receipts and receipts[-1]["uri"] == tracking_uri
            assert receipts[-1]["offset_unit"] == "block"
            assert isinstance(receipts[-1]["blocks"], list)
            assert "goal_ask_referrer" in {tool["name"] for tool in functions}
            tool_name = "goal_ask_referrer"
            value = {
                "question": "Standard ou express ?" if language == "fr" else "Standard or express?"
            }
            if revoke_question:
                # Revoke after advertisement, before the native effect. The real
                # authorization layer must reread the live function permission.
                async with get_db_session():
                    await connections.set_connection_function_state(native_connection_id, "goal_ask_referrer", "disabled")
        delta = ({"tool_calls": [{"index": 0, "id": f"synthetic-call-{len(stages)}", "type": "function",
                  "function": {"name": tool_name, "arguments": json.dumps(value)}}]}
                 if tool_name else {"content": text})
        chunk = {"id": "synthetic-completion", "model": "synthetic", "created": 1,
                 "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta,
                 "finish_reason": "tool_calls" if tool_name else "stop"}],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

    original_client = httpx.AsyncClient

    class ExternalClient(original_client):
        def __init__(self, *args, **kwargs):
            if "transport" not in kwargs:
                kwargs["transport"] = httpx.MockTransport(respond)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("app.llm.proxy_service.httpx.AsyncClient", ExternalClient)

    assert await runner.start_due_cycle()
    task_id = await db.scalar(select(GoalCycle.task_id).where(GoalCycle.goal_id == goal_id))
    assert task_id is not None
    await db.commit()
    for _ in range(4):
        await asyncio.wait_for(scheduler.run_once(), timeout=40)
        db.expire_all()
        task = await db.get(Task, task_id)
        if task.paused:
            break
        if task.status in (TaskStatus.SUCCESS, TaskStatus.ERROR):
            break
        await db.commit()
    if revoke_question:
        assert task.status == TaskStatus.SUCCESS, task.last_error
        assert "denied" in task.get_execution_result().result
        assert await db.scalar(select(func.count()).select_from(Interaction).where(Interaction.agent_id == agent_id)) == 0
        assert await db.scalar(select(func.count()).select_from(Message).where(Message.connection_id == connection_id)) == 0
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.goal_id == goal_id)) == 1
        profile = await db.get(LlmProfile, profile_id)
        profile.decision_llm_id = decision_llm_id
        await db.commit()
        assert await runner.process_terminal_cycle()
        db.expire_all()
        persisted_goal = await db.get(Goal, goal_id)
        assert persisted_goal.status == GoalStatus.ACTIVE
        assert (await goal_service.read_markdown(persisted_goal)).tracking == ""
        cycle = await db.scalar(select(GoalCycle).where(GoalCycle.goal_id == goal_id))
        assert cycle.verdict == GoalVerdict.CONTINUE
        assert await db.scalar(select(func.count()).select_from(Document)) == initial_documents + 1
        assert not await runner.process_terminal_cycle()
        assert not await runner.start_due_cycle()
        assert stages.count("ask") == stages.count("judge") == 1
        assert stages.count("read_tracking") == 1
        return
    assert task.status == TaskStatus.DISPATCH, task.last_error
    assert task_service.is_paused_for(task, task_service.PAUSE_AWAIT)
    interaction = await db.scalar(select(Interaction).where(Interaction.agent_id == agent_id))
    assert interaction is not None and interaction.status == "PENDING"
    reference, interaction_id = interaction.reference, interaction.id
    assert await db.scalar(select(func.count()).select_from(Message).where(
        Message.connection_id == connection_id, Message.direction == "outbound")) == 1
    assert not await runner.process_terminal_cycle()
    await db.commit()

    if failed_cycles:
        failed_task_id = task_id
        transition(task, TaskEvent.FAIL)
        task_service.clear_pauses(task)
        task.last_error = "Synthetic execution failed after the question was sent."
        await task_service.save(task)
        assert await runner.process_terminal_cycle()
        assert not await runner.start_due_cycle()
        # The last reminder from a dead cycle must never pause the Goal.
        reminder_at = datetime.now(timezone.utc) + timedelta(days=1, seconds=1)
        assert await referrer_wait.process_due_referrer_wait(reminder_at)
        assert await referrer_wait.process_due_referrer_wait(reminder_at + timedelta(days=1, seconds=1))
        assert (await db.get(Goal, goal_id)).status == GoalStatus.ACTIVE

    if late_answer:
        wait = await db.scalar(select(Task).where(Task.parent_id == task_id))
        assert wait is not None
        due = datetime.now(timezone.utc) + timedelta(days=1, seconds=1)
        assert await referrer_wait.process_due_referrer_wait(due)
        # Reprocessing the same instant cannot send a second reminder.
        assert not await referrer_wait.process_due_referrer_wait(due)
        assert await referrer_wait.process_due_referrer_wait(due + timedelta(days=1, seconds=1))
        db.expire_all()
        assert (await db.get(Goal, goal_id)).status == GoalStatus.PAUSED
        assert await db.scalar(select(func.count()).select_from(Message).where(
            Message.connection_id == connection_id, Message.direction == "outbound")) == 2
        await db.commit()

    # Membership and the journal remain real: an unrelated user cannot answer.
    assert await publish_internal_message(user_id=outsider_id, room_id=room_id,
        client_message_id=uuid4(), text=f"SYNTHETIC-ANSWER: standard #{reference}") is None
    answer_id = uuid4()
    answer = f"SYNTHETIC-ANSWER: express #{reference}"
    for _ in range(2):
        assert await publish_internal_message(user_id=owner_id, room_id=room_id,
            client_message_id=answer_id, text=answer) is not None
    await db.commit()
    db.expire_all()
    assert (await db.get(Interaction, interaction_id)).status == "RESOLVED"
    assert await db.scalar(select(func.count()).select_from(Message).where(
        Message.connection_id == connection_id, Message.direction == "inbound")) == 1
    outbound = select(Message.text).where(
        Message.connection_id == connection_id, Message.direction == "outbound"
    ).order_by(Message.journal_position)
    receipt_text = "Réponse reçue" if language == "fr" else "Answer received"
    notices = list((await db.scalars(outbound)).all())
    assert sum(text.startswith(receipt_text) for text in notices) == 1
    assert f"#{reference}" in notices[-1]
    if failed_cycles:
        assert await runner.start_due_cycle()
        task_id = await db.scalar(select(GoalCycle.task_id).where(
            GoalCycle.goal_id == goal_id, GoalCycle.sequence == 2))
        assert task_id is not None
        assert (await db.get(Task, failed_task_id)).status == TaskStatus.ERROR
        assert not await runner.start_due_cycle()
    if failed_cycles == 2:
        recovery_task = await db.get(Task, task_id)
        assert "SYNTHETIC-ANSWER: express" in recovery_task.objective
        transition(recovery_task, TaskEvent.FAIL)
        await task_service.save(recovery_task)
        assert await runner.process_terminal_cycle()
        assert await referrer_wait.process_recovered_cycle_feedback()
        assert not await referrer_wait.process_recovered_cycle_feedback()
        assert not await runner.start_due_cycle()

        persisted_goal = await db.get(Goal, goal_id)
        assert persisted_goal.status == GoalStatus.ACTIVE
        persisted_goal.next_cycle_at = datetime.now(timezone.utc)
        await db.commit()
        assert await runner.start_due_cycle()
        task_id = await db.scalar(select(GoalCycle.task_id).where(
            GoalCycle.goal_id == goal_id, GoalCycle.sequence == 3))
        assert task_id is not None

    approvals = 0
    for _ in range(6):
        await asyncio.wait_for(scheduler.run_once(), timeout=40)
        db.expire_all()
        task = await db.get(Task, task_id)
        if task.status in (TaskStatus.SUCCESS, TaskStatus.ERROR):
            break
        if task_service.is_paused_for(task, task_service.PAUSE_APPROVAL):
            assert approval_tool
            authorization = await db.scalar(select(ActionAuthorization).where(
                ActionAuthorization.agent_id == agent_id, ActionAuthorization.status == "pending"))
            assert authorization is not None, [
                (row.capability_name, row.status) for row in await db.scalars(select(ActionAuthorization))]
            assert authorization.capability_name == approval_tool
            assert (await db.get(Goal, goal_id)).status == GoalStatus.ACTIVE
            assert not await runner.process_terminal_cycle()
            assert await db.scalar(select(func.count()).select_from(Message).where(
                Message.connection_id == connection_id, Message.direction == "outbound")) == 2
            assert not await answer_action(authorization.id, user_id=outsider_id, approved=True)
            assert await answer_action(authorization.id, user_id=owner_id, approved=True)
            approvals += 1
            await db.commit()
            await reconcile_authorizations()
        await db.commit()
    assert task.status == TaskStatus.SUCCESS, task.last_error
    if approval_tool == "goal_update_suivi":
        assert "express" in (await goal_service.read_markdown(await db.get(Goal, goal_id))).tracking
    assert "express" in task.get_execution_result().result
    profile = await db.get(LlmProfile, profile_id)
    profile.decision_llm_id = decision_llm_id
    await db.commit()
    assert await runner.process_terminal_cycle()
    db.expire_all()
    persisted_goal = await db.get(Goal, goal_id)
    assert persisted_goal.status == GoalStatus.COMPLETED
    if approval_tool == "goal_update_suivi":
        assert "express" in (await goal_service.read_markdown(persisted_goal)).tracking
    cycle = await db.scalar(select(GoalCycle).where(GoalCycle.task_id == task_id))
    assert cycle.verdict == GoalVerdict.STOP
    assert not await runner.process_terminal_cycle()
    assert not await runner.start_due_cycle()
    if failed_cycles:
        assert await referrer_wait.process_recovered_cycle_feedback()
        assert not await referrer_wait.process_recovered_cycle_feedback()
    assert await db.scalar(select(func.count()).select_from(Document)) == initial_documents + 1
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.goal_id == goal_id)) == 2 + failed_cycles
    notices = list((await db.scalars(outbound)).all())
    assert len(notices) == 3 + int(late_answer) + failed_cycles + int(approval_tool == "messenger_send_message_to_user")
    completed_text = "est terminé" if language == "fr" else "is complete"
    assert completed_text in notices[-1]
    assert f"galaris://goal/{goal_id}" in notices[-1]
    assert approvals == int(approval_tool is not None)
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent_id)))
    assert {"agent.dispatch", "agent.exec", "goal.tracking"} <= {call.purpose for call in calls}
    assert calls and all(call.status == "completed" and call.error is None for call in calls)
    monitoring_calls = [call for call in calls if call.purpose == "goal.tracking"]
    assert len(monitoring_calls) == 1 and monitoring_calls[0].llm_id == decision_llm_id
    assert stages.count("ask") == stages.count("resume") == 1
    assert stages.count("read_tracking") == 1
    assert stages.count("judge") == 1
    assert stages.count("review_read") == stages.count("review_done") == 0
    assert "dispatch" in stages
