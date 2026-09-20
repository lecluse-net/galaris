"""Real authorization boundaries with equally privileged, distinct managers."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.models import Agent, Title
from app.task.models import Task, TaskStatus
from core import websocket
from core.authorize.models import Assignment, Role, Privilege
from core.user import auth_service, refresh_session_service, token_service
from core.user.models import User


@pytest.mark.asyncio
@pytest.mark.parametrize("subscribed", [False, True])
async def test_task_events_and_run_rooms_obey_manager_scope(db, monkeypatch, subscribed):
    suffix = uuid4().hex
    users = [User(email=f"{i}-{suffix}@example.test", hashed_password="unused") for i in range(2)]
    title = Title(label=suffix, gender="X")
    role = Role(code=suffix, display_name="Scoped task reader")
    from sqlalchemy import select
    role.privileges = list((await db.scalars(select(Privilege).where(Privilege.code.in_(
        ["TASK_ACCESS", "GOAL_ACCESS", "MEMORY_ACCESS", "PROCESS_READ"],
    )))).all())
    db.add_all([*users, title, role])
    await db.flush()
    agents = [Agent(user_id=u.id, title_id=title.id, code=f"{i}-{suffix}", first_name="Scoped", last_name="Agent") for i, u in enumerate(users)]
    db.add_all(agents)
    db.add_all([Assignment(user_id=u.id, role_id=role.id) for u in users])
    await db.flush()
    task = Task(agent_id=agents[0].id, label="private", objective="Private objective", status=TaskStatus.DISPATCH)
    db.add(task)
    await db.commit()
    identities = {str(i): websocket._SocketIdentity(u.id, role.id, auth_service.create_access_token(
        {"sub": u.email, "user_id": u.id, "role_id": role.id}
    )) for i, u in enumerate(users)}
    server = AsyncMock()
    monkeypatch.setattr(websocket, "_sio", server)
    monkeypatch.setattr(websocket, "_connected_identities", identities)
    monkeypatch.setattr(websocket, "_event_subscriptions", {
        sid: frozenset(f"{subject}.{action}" for subject in (
            "task", "llm_call", "goal", "memory", "process_run", "voice_conversation",
        ) for action in ("update", "delete"))
        for sid in identities
    } if subscribed else {})
    await websocket.emit("task", "update", {"id": str(task.id), "agent_id": agents[0].id, "objective": task.objective})
    assert [call.kwargs["room"] for call in server.emit.await_args_list] == ["0"]
    assert await websocket._handle_room_join("0", {"room": f"TaskRunRoom:{task.id}"})
    assert not await websocket._handle_room_join("1", {"room": f"TaskRunRoom:{task.id}"})
    # The publishing worker's role cannot grant a recipient global management.
    assert await websocket._resource_room_is_authorized("1", f"TaskRunRoom:{task.id}") is False

    from datetime import datetime, timezone
    from app.connection.models import Connection
    from app.goal.models import Goal
    from app.llm.models import LLMCall
    from app.llm import llm_call_service
    from app.memory.models import MemoryItem, MemoryItemGrant
    from app.messenger.models import Room
    from app.process.models import ProcessDefinition, ProcessRun
    from app.tools.models import Tool
    from app.voice.models import VoiceConversationSession
    from core.authorize import role_id_ctx
    from core.user import user_service

    documents = [MemoryItem(owner_agent_id=agents[0].id, resource_id=f"test/{suffix}/{i}", content_hash="0" * 64, title=f"Private {i}", memory_type="working", node_kind="document") for i in range(2)]
    tool = Tool(code=suffix, label="Private tool")
    call = LLMCall(task_id=task.id, prompt="Private prompt")  # Visibility inherited from the Task.
    db.add_all([*documents, tool, call])
    await db.flush()
    goal = Goal(agent_id=agents[0].id, title="Private goal", description_document_id=documents[0].id, tracking_document_id=documents[1].id)
    connection = Connection(agent_id=agents[0].id, tool_id=tool.id, active=True)
    definition = ProcessDefinition(agent_id=agents[0].id, tool_id=tool.id, engine_process_id=suffix, label="Private process")
    db.add_all([goal, connection, definition])
    await db.flush()
    room = Room(connection_id=connection.id, external_id=suffix, label="Private call", conversation_type="audio")
    run = ProcessRun(process_id=definition.id, launcher_agent_id=agents[0].id, engine_code="test", correlation_id=suffix, callback_token="test-token")
    db.add_all([room, run])
    await db.flush()
    voice = VoiceConversationSession(messenger_room_id=room.id, started_at=datetime.now(timezone.utc))
    db.add(voice)
    await db.commit()
    user_service.set_current_user(users[1])
    # A publisher's unrelated active role must neither authorize nor suppress recipients.
    role_token = role_id_ctx.set(-1)
    try:
        for subject, resource in [("llm_call", call), ("goal", goal), ("memory", documents[0]), ("process_run", run), ("voice_conversation", voice)]:
            server.emit.reset_mock()
            await websocket.emit(subject, "update", {"id": str(resource.id)})
            assert [c.kwargs["room"] for c in server.emit.await_args_list] == ["0"], subject
        assert user_service.get_current_user_id() == users[1].id
        assert role_id_ctx.get() == -1
    finally:
        role_id_ctx.reset(role_token)
        user_service.set_current_user(None)

    # Deletion still refreshes the owner's screen after the trace row is gone.
    server.emit.reset_mock()
    assert await llm_call_service.delete_call(call.id)
    assert [c.kwargs["room"] for c in server.emit.await_args_list] == ["0"]

    grant = MemoryItemGrant(item_id=documents[0].id, agent_id=agents[1].id, can_write=False)
    db.add(grant)
    await db.commit()
    server.emit.reset_mock()
    await websocket.emit("memory", "update", {"id": str(documents[0].id)})
    assert {c.kwargs["room"] for c in server.emit.await_args_list} == {"0", "1"}
    await db.delete(grant)
    await db.commit()
    server.emit.reset_mock()
    await websocket.emit("memory", "update", {"id": str(documents[0].id)})
    assert [c.kwargs["room"] for c in server.emit.await_args_list] == ["0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidation", ["expiry", "logout", "password", "disabled", "api_token"])
async def test_open_socket_is_closed_when_credential_stops_being_valid(db, monkeypatch, invalidation):
    user = User(email=f"{uuid4().hex}@example.test", hashed_password="unused")
    db.add(user)
    await db.commit()
    refresh = await refresh_session_service.create_refresh_session(user.id)
    family = await refresh_session_service.family_for_token(refresh)
    token = await auth_service.create_access_token_for_user(user, session_family=family)
    if invalidation == "api_token":
        from core.user.schemas import UserTokenCreate
        record, token = await token_service.create_token_for_user(user.id, UserTokenCreate(label="socket"))
    identity = await websocket._authenticate_socket_token(token)
    assert identity is not None
    if invalidation == "expiry":
        token = auth_service.create_access_token({"sub": user.email, "user_id": user.id}, timedelta(seconds=-1))
        identity = websocket._SocketIdentity(user.id, None, token)
    elif invalidation == "logout":
        await refresh_session_service.revoke_refresh_token(refresh)
    elif invalidation == "password":
        user.auth_version += 1
        await db.commit()
    elif invalidation == "disabled":
        user.is_active = False
        await db.commit()
    else:
        record.enabled = False
        await db.commit()
    server = AsyncMock()
    monkeypatch.setattr(websocket, "_sio", server)
    monkeypatch.setattr(websocket, "_connected_identities", {"victim": identity})
    await websocket.check_sessions()
    assert not websocket._connected_identities
    server.disconnect.assert_awaited_once_with("victim")
