"""Owner fairness through the real queue, gateway, PostgreSQL and synthetic HTTP."""

import asyncio
from contextlib import nullcontext
from uuid import uuid4

import pytest

from app.llm import llm_call_service, llm_provider_service, provider_scheduler
from app.llm.facade import run_text_inference, start_inference, stream_inference
from app.llm.provider_schemas import LLMProviderUpdate
from app.llm.subscription_policy import llm_execution_scope
from core.database import get_db_session
from core.user import user_identity_context
from tests.test_inference_lifecycle import runtime  # noqa: F401
from tests.test_text_inference import request_for


async def conversation_round(db, *, voice=False):
    from datetime import datetime, timezone

    from app.agent.models import Agent, Title
    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.messenger import Room
    from app.tools.models import Tool
    from app.voice.models import VoiceConversationSession
    from core.user.models import User

    title = Title(label="Synthetic admission", gender="X")
    tool = Tool(code=f"admission-{uuid4()}", label="Synthetic transport", connection_schema={})
    user = User(email=f"admission-{uuid4()}@example.test", hashed_password="unused-synthetic-hash")
    db.add_all([title, tool, user])
    await db.flush()
    agent = Agent(code=f"admission-{uuid4()}", first_name="Synthetic", last_name="Agent",
                  title_id=title.id, user_id=user.id)
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(connection_id=connection.id, external_id="synthetic-admission", kind="direct",
                label="Synthetic admission", conversation_type="audio" if voice else "text")
    db.add(room)
    await db.flush()
    session = None
    if voice:
        session = VoiceConversationSession(messenger_room_id=room.id, started_at=datetime.now(timezone.utc))
        db.add(session)
        await db.flush()
    round_ = ConversationRound(room_id=room.id, status="RUNNING", voice_session_id=session.id if session else None)
    db.add(round_)
    await db.commit()
    return round_, agent


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("owner_kind", ["task", "run", "source", "requester", "user", "agent", "process"])
async def test_independent_owners_get_capacity_before_another_call_from_the_active_owner(
    runtime, monkeypatch, durable, owner_kind,
):
    db, llm, requests, mode = runtime
    first_owner, second_owner = uuid4(), uuid4()
    shared_round = None
    requesting_users = {}
    if owner_kind == "task":
        from app.task.models import Task

        round_, agent = await conversation_round(db)
        shared_round = round_.id
        db.add_all([
            Task(id=key, label="Synthetic work", objective="<p>Independent work</p>",
                 agent_id=agent.id, data={"conversation_round_id": str(shared_round)})
            for key in (first_owner, second_owner)
        ])
        await db.commit()
    elif owner_kind in {"requester", "user"}:
        from core.user.models import User

        users = [User(email=f"admission-{uuid4()}@example.test", hashed_password="unused-synthetic-hash")
                 for _ in range(2)]
        db.add_all(users)
        await db.commit()
        first_owner, second_owner = (user.id for user in users)
        requesting_users = {user.id: user for user in users}
    elif owner_kind == "agent":
        agents = [(await conversation_round(db))[1] for _ in range(2)]
        first_owner, second_owner = (agent.id for agent in agents)
    elif owner_kind == "process":
        from app.process.models import ProcessDefinition, ProcessRun
        from app.tools.models import Tool

        _, agent = await conversation_round(db)
        tool = Tool(code=f"admission-workflow-{uuid4()}", label="Synthetic workflow engine", connection_schema={})
        db.add(tool)
        await db.flush()
        definition = ProcessDefinition(tool_id=tool.id, engine_process_id="synthetic-workflow", label="Synthetic workflow")
        db.add(definition)
        await db.flush()
        db.add_all([ProcessRun(id=key, process_id=definition.id, launcher_agent_id=agent.id,
                              engine_code="synthetic", correlation_id=str(key), callback_token=uuid4().hex)
                    for key in (first_owner, second_owner)])
        await db.commit()

    await llm_provider_service.update_provider(llm.llm_provider_id, LLMProviderUpdate(max_concurrent_calls=1))
    mode.update(gate=asyncio.Event(), concurrent=True)
    scheduler = provider_scheduler.get_scheduler()
    enqueued = asyncio.Queue()
    created = asyncio.Queue()
    real_enqueue = scheduler.enqueue
    real_emit = llm_call_service.websocket.emit

    def observe_enqueue(*args, **kwargs):
        ticket = real_enqueue(*args, **kwargs)
        enqueued.put_nowait(ticket)
        return ticket

    async def observe_create(subject, action, data, room):
        if subject == "llm_call" and action == "create":
            created.put_nowait(data["prompt"])
        await real_emit(subject, action, data, room)

    monkeypatch.setattr(scheduler, "enqueue", observe_enqueue)
    monkeypatch.setattr(llm_call_service.websocket, "emit", observe_create)

    async def run(owner, prompt):
        request = request_for(llm).model_copy(update={
            "prompt": prompt,
            "task_id": owner if owner_kind == "task" else None,
            "conversation_round_id": shared_round,
            "agent_run_id": owner if owner_kind == "run" else None,
            "process_run_id": owner if owner_kind == "process" else None,
            "agent_id": owner if owner_kind == "agent" else None,
        })
        with llm_execution_scope(
            # A background operation derived from a round never becomes a
            # direct dialogue simply because its authority retains that source.
            source_kind="conversation_round" if owner_kind == "source" else None,
            source_id=str(owner) if owner_kind == "source" else None,
            requester_user_id=owner if owner_kind == "requester" else None,
        ), user_identity_context(requesting_users[owner]) if owner_kind == "user" else nullcontext():
            if durable:
                key = await start_inference(request)
                events = [event async for event in stream_inference(key)]
                assert events[-1].result.success, events[-1].result.metadata
            else:
                async with get_db_session():
                    result = await run_text_inference(request)
                    assert result.success, result.metadata

    running = []

    async def observed(queue):
        # Surface a caller's original failure instead of hiding it behind a
        # timeout waiting for an admission event it can no longer produce.
        event = asyncio.create_task(queue.get())
        try:
            done, _ = await asyncio.wait([event, *running], return_when=asyncio.FIRST_COMPLETED)
            for caller in done - {event}:
                caller.result()
                pytest.fail("Caller finished before its expected admission event.")
            return event.result()
        finally:
            event.cancel()
            await asyncio.gather(event, return_exceptions=True)

    try:
        async with asyncio.timeout(10):
            running.append(asyncio.create_task(run(first_owner, "Synthetic active call")))
            await observed(enqueued)
            assert await observed(created) == "Synthetic active call"
            running.append(asyncio.create_task(run(first_owner, "Synthetic repeated owner")))
            repeated = await observed(enqueued)
            running.append(asyncio.create_task(run(second_owner, "Synthetic independent owner")))
            independent = await observed(enqueued)
            assert not repeated.future.done() and not independent.future.done()
            # At four slots, two background calls can run. The unused owner
            # gets the second slot even though its request arrived last.
            await llm_provider_service.update_provider(llm.llm_provider_id, LLMProviderUpdate(max_concurrent_calls=4))
            assert await observed(created) == "Synthetic independent owner"
            assert not repeated.future.done()
            mode["gate"].set()
            await asyncio.gather(*running)
            assert len(requests) == 3
            if owner_kind in {"requester", "user"}:
                from sqlalchemy import select
                from app.llm.models import LLMCall

                async with get_db_session() as reader:
                    requesters = list(await reader.scalars(
                        select(LLMCall.requester_user_id).where(LLMCall.llm_id == llm.id)
                    ))
                assert sorted(requesters) == sorted([first_owner, first_owner, second_owner])
    finally:
        mode["gate"].set()
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("voice", [False, True])
async def test_direct_dialogue_keeps_its_round_run_and_protected_capacity(runtime, durable, voice):
    from sqlalchemy import select

    from app.llm.models import LLMCall

    db, llm, requests, mode = runtime
    round_, agent = await conversation_round(db, voice=voice)
    run = uuid4()
    await llm_provider_service.update_provider(llm.llm_provider_id, LLMProviderUpdate(max_concurrent_calls=3))
    mode["concurrent"] = True
    scheduler = provider_scheduler.get_scheduler()
    # Only the tested medium's protected place is free. A wrong class cannot
    # pass unnoticed because the other dialogue class and background are full.
    background = await scheduler.acquire(llm.llm_provider_id, 3, 2)
    opposite = await scheduler.acquire(llm.llm_provider_id, 3, 1 if voice else 0)
    request = request_for(llm).model_copy(update={
        "conversation_round_id": round_.id, "agent_run_id": run, "agent_id": agent.id,
        # Legacy execution purposes rely on the durable round for the medium.
        "purpose": "agent.exec",
    })
    try:
        async with asyncio.timeout(10):
            if durable:
                key = await start_inference(request)
                events = [event async for event in stream_inference(key)]
                assert events[-1].result.success
            else:
                async with get_db_session():
                    assert (await run_text_inference(request)).success
        async with get_db_session() as reader:
            call = await reader.scalar(select(LLMCall).where(LLMCall.llm_id == llm.id))
            assert call.conversation_round_id == round_.id and call.agent_run_id == run
            assert call.task_id is None and call.status == "completed"
        assert len(requests) == 1
    finally:
        background.release()
        opposite.release()
