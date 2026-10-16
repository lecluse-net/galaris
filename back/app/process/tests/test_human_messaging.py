"""Human results arrive through scoped conversation requests, including file-only replies."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope, TaskMessage
from app.connection import Connection
from app.conversation import ConversationTurn, ProcessHumanMessenger
from app.conversation.mcp import conversation_process_respond
from app.conversation.process_interactions import PROCESS_HUMAN_INTERACTION
from app.messenger import (Interaction, Message, MessengerUser, Room, File, Attachment,
    list_pending_choices, resolve_from_message)
from app.process import ProcessHumanContact
from app.process import human_directory, process_service
from app.process.bpmn import Actor, Flow, Node, Workflow
from app.process.human_requests import deliver_human_requests
from app.process.models import ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from app.process.native_actors import human_work
from app.process.native_definitions import create
from app.process.values import Variable
from app.tools import McpToolContext
from app.tools.models import Tool
from core.user import UserModel

from .test_native_bpmn import native as native, finish_run


async def setup_wait(db, native, monkeypatch, *, typed=True, file_output=False, sequential=False, decision=False):
    owner, _ = native
    user = UserModel(email=f"human-{uuid4().hex}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add(user)
    await db.flush()
    owner.user_id = user.id
    outputs = [Variable(name="attachment" if file_output else "approved", type="File" if file_output else "bool", nullable=False)] if typed else None
    graph = Workflow(schema_version="galaris.bpmn/v2" if typed else "galaris.bpmn/v1",
        inputs=[] if typed else None, outputs=outputs,
        actors=[Actor(id="reviewer", name="Reviewer", kind="human", user_id=user.id)],
        nodes=[Node(id="start", kind="start"), Node(id="review", kind="human_task", title="Invented approval",
            config={"actor": "reviewer", "prompt": "Review this invented request."},
            inputs=[] if typed else None, outputs=outputs), Node(id="end", kind="end")],
        flows=[Flow(id="a", source="start", target="review"), Flow(id="b", source="review", target="end")])
    if decision:
        graph.outputs = []
        graph.nodes[1] = Node(id="review", kind="if", title="Invented decision", config={"actor": "reviewer", "mode": "human", "prompt": "Is this the requested project?"})
        graph.nodes.append(Node(id="declined", kind="end"))
        graph.flows[1].condition = "decision"
        graph.flows.append(Flow(id="no", source="review", target="declined"))
    if sequential:
        graph.nodes.insert(2, Node(id="confirm", kind="human_task", title="Second synthetic approval",
            config={"actor": "reviewer", "prompt": "Confirm this second invented step."}, inputs=[], outputs=outputs))
        graph.flows = [Flow(id="a", source="start", target="review"), Flow(id="b", source="review", target="confirm"),
            Flow(id="c", source="confirm", target="end")]
    definition = await create(actor_agent_id=owner.id, title="Synthetic human workflow", graph=graph)
    launched = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    await process_service.process_start_jobs(engine_code="galaris")
    for _ in range(4):
        await process_service.refresh_run(launched.run_id)
    monkeypatch.setattr(human_directory, "_directory", SimpleNamespace(list_humans=AsyncMock(return_value=())))
    monkeypatch.setattr(human_directory, "_messenger", ProcessHumanMessenger())
    return owner, user, launched.run_id


@pytest.mark.parametrize("answer", [True, False])
@pytest.mark.asyncio
async def test_human_decision_buttons_complete_the_chosen_branch_without_an_ai_task(db, native, monkeypatch, answer):
    owner, user, run_id = await setup_wait(db, native, monkeypatch, decision=True)
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    db.add(Connection(agent_id=owner.id, tool_id=chat.id, active=True))
    await db.commit()
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == PROCESS_HUMAN_INTERACTION))
    assert choice.metadata_["decision"]
    assert choice.options == [{"id": "true", "label": "True", "aliases": []}, {"id": "false", "label": "False", "aliases": []}]
    room = await db.get(Room, UUID(choice.room_id))
    sender = MessengerUser(id=uuid4(), external_id=choice.user_id, is_ai=False)
    incoming = Message(connection_id=choice.connection_id, tool_id=choice.tool_id,
        remote_message_id="synthetic-decision", direction="inbound", text=f"#{choice.reference} {answer}", platform="internal")
    incoming.room, incoming.sender = room, sender
    resolution = await resolve_from_message(incoming, agent_id=owner.id)
    assert resolution is not None and resolution.option_id == str(answer).lower()
    assert await resolve_from_message(incoming, agent_id=owner.id) is None
    run = await finish_run(db, run_id)
    assert run.status == "success", run.error_message
    nodes = list(await db.scalars(select(ProcessNodeRun.node_key).where(ProcessNodeRun.run_id == run.id)))
    assert sorted(nodes) == sorted(["start", "review", "end" if answer else "declined"])
    assert await db.scalar(select(ProcessNodeAttempt.task_id).join(ProcessNodeRun).where(ProcessNodeRun.run_id == run.id)) is None


@pytest.mark.asyncio
async def test_internal_request_is_durable_scoped_and_does_not_consume_unrelated_messages(db, native, monkeypatch):
    owner, user, run_id = await setup_wait(db, native, monkeypatch)
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    db.add(Connection(agent_id=owner.id, tool_id=chat.id, active=True))
    await db.commit()
    assert await deliver_human_requests() == 1
    assert await deliver_human_requests() == 0
    choice = await db.scalar(select(Interaction).where(Interaction.kind == PROCESS_HUMAN_INTERACTION))
    assert choice is not None and choice.prompt_message_id
    assert choice.user_id == f"user:{user.id}"
    assert choice.metadata_["outputs"][0]["name"] == "approved"
    room = await db.get(Room, UUID(choice.room_id))
    sender = MessengerUser(id=uuid4(), external_id=choice.user_id, is_ai=False)
    incoming = Message(connection_id=choice.connection_id, tool_id=choice.tool_id,
        remote_message_id="synthetic-question", direction="inbound", text="What is the weather?", platform="internal")
    incoming.room, incoming.sender = room, sender
    assert await resolve_from_message(incoming, agent_id=owner.id) is None
    scope = dict(agent_id=owner.id, connection_id=choice.connection_id, tool_id=choice.tool_id,
        room_id=choice.room_id, user_id=choice.user_id)
    assert len(await list_pending_choices(**scope)) == 1
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=owner.id, language="en",
        objective="Yes, approve it", messages=({"text": "Yes, approve it"},),
        messaging_context={"connection_id": choice.connection_id, "tool_id": choice.tool_id,
            "participant_id": choice.user_id, "requester_user_id": user.id})
    ctx = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    from app.tools import RecoverableToolError
    with pytest.raises(RecoverableToolError, match="missing"):
        await conversation_process_respond(ctx, reference=choice.reference, output={})
    assert choice.status == "PENDING"
    unlinked = replace(turn, messaging_context={**turn.messaging_context, "requester_user_id": None})
    with pytest.raises(PermissionError, match="authenticated"):
        await conversation_process_respond(McpToolContext(agent_id=owner.id, runtime="internal",
            resources={"conversation_turn": unlinked}), reference=choice.reference,
            output={"approved": {"type": "bool", "value": True}})
    foreign = replace(turn, messaging_context={**turn.messaging_context, "participant_id": "user:999999"})
    with pytest.raises(PermissionError):
        await conversation_process_respond(McpToolContext(agent_id=owner.id, runtime="internal",
            resources={"conversation_turn": foreign}), reference=choice.reference,
            output={"approved": {"type": "bool", "value": True}})
    output = {"approved": {"type": "bool", "value": False}}
    assert (await conversation_process_respond(ctx, reference=choice.reference, output={"approved": False}))["applied"]
    assert not (await conversation_process_respond(ctx, reference=choice.reference, output=output))["applied"]
    with pytest.raises(ValueError, match="different"):
        await conversation_process_respond(ctx, reference=choice.reference,
            output={"approved": {"type": "bool", "value": True}})
    assert not await list_pending_choices(**scope)
    await finish_run(db, run_id)
    run = await db.get(ProcessRun, run_id)
    assert run.status == "success" and run.output == output
    assert (await human_work(AgentManagementScope(user.id, frozenset()), page=1, page_size=50))["total"] == 0


@pytest.mark.asyncio
async def test_delivery_failure_keeps_wait_and_retry_uses_one_attempt(db, native, monkeypatch):
    owner, user, run_id = await setup_wait(db, native, monkeypatch)
    transport = SimpleNamespace(deliver=AsyncMock(side_effect=RuntimeError("Synthetic unavailable transport")))
    monkeypatch.setattr(human_directory, "_messenger", transport)
    assert await deliver_human_requests() == 1
    pending = (await human_work(AgentManagementScope(user.id, frozenset()), page=1, page_size=50))["items"]
    attempt = await db.get(ProcessNodeAttempt, UUID(pending[0]["attempt_id"]))
    assert attempt.status == "human_waiting"
    node = await db.get(ProcessNodeRun, attempt.node_run_id)
    node.context = {**node.context, "human_request_retry_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    await db.commit()
    transport.deliver.side_effect = None
    assert await deliver_human_requests() == 1
    assert await deliver_human_requests() == 0
    assert transport.deliver.await_count == 2
    assert transport.deliver.call_args.args[0].attempt_id == attempt.id


@pytest.mark.asyncio
async def test_file_only_message_reaches_controller_and_process_with_its_original_uri(db, native, monkeypatch):
    from app.conversation.service import admit_message, build_turn, claim_next_round
    owner, user, run_id = await setup_wait(db, native, monkeypatch, file_output=True)
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    db.add(Connection(agent_id=owner.id, tool_id=chat.id, active=True))
    await db.commit()
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == PROCESS_HUMAN_INTERACTION))
    room = await db.get(Room, UUID(choice.room_id))
    sender = await db.scalar(select(MessengerUser).where(MessengerUser.tool_id == chat.id,
        MessengerUser.external_id == choice.user_id))
    file = File(connection_id=choice.connection_id, name="synthetic-review.pdf",
        mime_type="application/pdf", size_bytes=17, kind="document")
    db.add(file)
    incoming = Message(connection_id=choice.connection_id, tool_id=chat.id, platform="internal",
        remote_message_id=uuid4().hex, direction="inbound", text="", messenger_room_id=room.id,
        messenger_user_id=sender.id, sender_messenger_user_id=sender.id,
        requester_user_id=user.id, room_id=room.external_id, user_id=sender.external_id)
    db.add(incoming)
    await db.flush()
    db.add(Attachment(message_id=incoming.id, file_id=file.id, position=0))
    await db.commit()
    incoming.room, incoming.sender, incoming.files, incoming.tool_code = room, sender, [file], "chat"
    uri = f"chat://{room.external_id}/{file.id}"
    assert await resolve_from_message(incoming, agent_id=owner.id) is None
    await admit_message(incoming, agent_id=owner.id, connection_id=choice.connection_id)
    round_ = await claim_next_round("synthetic-file-round")
    turn = await build_turn(round_.id, lease_token=round_.lease_token)
    message = TaskMessage.model_validate(turn.messages[-1])
    assert message.text == "" and message.attachments[0].uri == uri
    assert turn.pending_interactions[0]["kind"] == PROCESS_HUMAN_INTERACTION
    ctx = McpToolContext(agent_id=owner.id, runtime="internal", resources={"conversation_turn": turn})
    with pytest.raises((PermissionError, LookupError, ValueError)):
        await conversation_process_respond(ctx, reference=choice.reference,
            output={"attachment": {"type": "File", "value": f"chat://{room.external_id}/{uuid4()}"}})
    assert choice.status == "PENDING"
    output = {"attachment": {"type": "File", "value": uri}}
    await conversation_process_respond(ctx, reference=choice.reference, output={"attachment": uri})
    await finish_run(db, run_id)
    run = await db.get(ProcessRun, run_id)
    assert run.status == "success" and run.output == output


@pytest.mark.asyncio
async def test_external_route_is_used_and_cancelled_process_refuses_a_late_chat_reply(db, native, monkeypatch):
    from app.conversation import process_interactions
    owner, user, run_id = await setup_wait(db, native, monkeypatch)
    tool = Tool(code="synthetic-messenger-" + uuid4().hex, label="Synthetic external messenger")
    db.add(tool)
    await db.flush()
    connection = Connection(agent_id=owner.id, tool_id=tool.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(connection_id=connection.id, external_id="external-synthetic-room", label="Synthetic external room", conversation_type="text")
    db.add(room)
    await db.commit()
    contact = ProcessHumanContact(user_id=user.id, display_name="Synthetic peer",
        connection_id=connection.id, external_user="@synthetic:example.invalid")
    monkeypatch.setattr(human_directory, "_directory", SimpleNamespace(list_humans=AsyncMock(return_value=(contact,))))
    transport = SimpleNamespace(connection_id=connection.id, tool_id=tool.id,
        ensure_direct_room=AsyncMock(return_value=room), send_to_room=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(process_interactions, "messenger_for_agent_connection", AsyncMock(return_value=transport))
    await deliver_human_requests()
    choice = await db.scalar(select(Interaction).where(Interaction.kind == PROCESS_HUMAN_INTERACTION))
    assert choice.connection_id == connection.id and choice.user_id == contact.external_user
    transport.ensure_direct_room.assert_awaited_once_with(contact.external_user)
    transport.send_to_room.assert_awaited_once()
    await process_service.cancel_run(run_id)
    turn = ConversationTurn(room_id=room.id, round_id=uuid4(), agent_id=owner.id, language="en",
        objective="Approve", messages=({"text": "Approve"},), messaging_context={
            "connection_id": connection.id, "tool_id": tool.id, "participant_id": contact.external_user,
            "requester_user_id": user.id})
    with pytest.raises(ValueError, match="no longer"):
        await conversation_process_respond(McpToolContext(agent_id=owner.id, runtime="internal",
            resources={"conversation_turn": turn}), reference=choice.reference,
            output={"approved": {"type": "bool", "value": True}})
    attempt = await db.get(ProcessNodeAttempt, UUID(choice.metadata_["attempt_id"]))
    assert attempt.receipt is None
    await deliver_human_requests()
    assert not await list_pending_choices(agent_id=owner.id, connection_id=connection.id, tool_id=tool.id,
        room_id=str(room.id), user_id=contact.external_user)


@pytest.mark.asyncio
async def test_successive_human_steps_send_distinct_requests_and_preserve_their_results(db, native, monkeypatch):
    owner, user, run_id = await setup_wait(db, native, monkeypatch, sequential=True)
    chat = await db.scalar(select(Tool).where(Tool.code == "chat"))
    db.add(Connection(agent_id=owner.id, tool_id=chat.id, active=True))
    await db.commit()
    references = []
    for approved in (True, False):
        assert await deliver_human_requests() == 1
        choice = await db.scalar(select(Interaction).where(Interaction.kind == PROCESS_HUMAN_INTERACTION,
            Interaction.status == "PENDING"))
        references.append(choice.reference)
        turn = ConversationTurn(room_id=UUID(choice.room_id), round_id=uuid4(), agent_id=owner.id, language="en",
            objective="Synthetic answer", messages=({"text": "Synthetic answer"},),
            messaging_context={"connection_id": choice.connection_id, "tool_id": choice.tool_id,
                "participant_id": choice.user_id, "requester_user_id": user.id})
        await conversation_process_respond(McpToolContext(agent_id=owner.id, runtime="internal",
            resources={"conversation_turn": turn}), reference=choice.reference,
            output={"approved": {"type": "bool", "value": approved}})
        for _ in range(6):
            await process_service.refresh_run(run_id)
    await finish_run(db, run_id)
    assert len(set(references)) == 2
    assert (await db.get(ProcessRun, run_id)).output == {"approved": {"type": "bool", "value": False}}
