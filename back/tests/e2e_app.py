"""Isolated browser-test composition root. Never imported by production.

The real API, authorization, Socket.IO, journal and schedulers run unchanged.
The conversation controller is scripted at its public port; provider adapters
are covered separately. A barrier, not a sleep, controls stream completion.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from sqlalchemy import select

from core.settings import settings

if (
    settings.APP_ENV != "test"
    or settings.POSTGRES_DB != "test_db"
    or settings.POSTGRES_HOST != "db-e2e"
):
    raise RuntimeError("Browser fixtures require the isolated compose.e2e.yaml database")

import pydantic_ai.models
from tests.runtime_isolation import isolated_api_import

with isolated_api_import():
    import main

from core.rate_limit import limiter

# Browser scenarios share one loopback address; quota behavior has HTTP tests.
limiter.enabled = False
from app.agent import AIMessage, AIResult, AgentEvent, ExecutionResult, ResolvedModel
from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation import ConversationOutcome, ConversationTurn, register_controller
from app.conversation.contracts import ConversationExecutionError
from app.conversation.models import ConversationRound
from app.messenger import create_internal_room
from app.tools.models import Tool
from core.authorize.models import Assignment, Role
from core.database import get_db_session
from core import websocket
from core.user.models import User
from core.user.user_service import encrypt_password

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
gates: dict[UUID, asyncio.Event] = {}
modes: dict[UUID, str] = {}


class ScriptedController:
    async def run(self, turn: ConversationTurn) -> ConversationOutcome:
        assert turn.publish_progress is not None
        messages = [AIMessage(type="text", content="Réponse progressive")]
        await turn.publish_progress(messages[0])
        if modes.get(turn.room_id) == "tools":
            message = AIMessage(
                type="tool", tool_name="fixture_lookup", content="Résultat vérifié",
                tool_call_external_id="lookup-1", tool_result={"value": 42},
            )
            messages.append(message)
            await turn.publish_progress(message)
        if modes.get(turn.room_id) == "interruptible":
            async with asyncio.timeout(45):
                while not gates[turn.room_id].is_set():
                    assert turn.should_interrupt is not None
                    if await turn.should_interrupt():
                        return ConversationOutcome(text="", metadata={"interrupted": True},
                            execution_result=AIResult(prompt="", messages=messages))
                    try:
                        await asyncio.wait_for(gates[turn.room_id].wait(), timeout=0.05)
                    except TimeoutError:
                        pass
        else:
            await asyncio.wait_for(gates[turn.room_id].wait(), timeout=45)
        if modes.get(turn.room_id) == "task":
            assert turn.admit_background_task is not None
            async with get_db_session():
                await turn.admit_background_task(
                    "Produire le résultat de la tâche de test",
                    forced_route="EXEC", forced_effort="standard", auto_approve=True,
                )
        if modes.get(turn.room_id) == "error":
            raise ConversationExecutionError(
                "fixture provider interrupted",
                execution_result=AIResult(prompt="", messages=messages, success=False),
            )
        final = AIMessage(type="text", content=" terminée.")
        messages.append(final)
        await turn.publish_progress(final)
        result = AIResult(prompt="", result="Réponse progressive terminée.")
        for message in messages:
            result.add_message(message.model_copy(deep=True))
        return ConversationOutcome(
            text="Réponse progressive terminée.",
            execution_result=result,
        )


async def task_fields(_turn, *, label_hint, objective_hint):
    return label_hint, objective_hint, 0.0


async def task_model(_agent, effort, _language, _reasoning):
    return ResolvedModel(id=1, code="fixture", model_name="fixture", label="Fixture", requested_effort=effort)


async def task_stream(request):
    yield AgentEvent.from_message(AIMessage(type="text", content="Résultat durable de la tâche."))
    yield AgentEvent.from_result(ExecutionResult(prompt=request.objective, result="Résultat durable de la tâche."))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    original_emit = websocket.emit

    async def emit(subject, action, data, room=None):
        if subject == "chat" and action == "runtime" and data.get("kind") == "finished":
            if modes.get(UUID(data["room_id"])) == "missing-terminal":
                return
        await original_emit(subject, action, data, room=room)

    with ExitStack() as patches:
        patches.enter_context(patch.object(websocket, "emit", emit))
        patches.enter_context(patch("app.conversation.mcp.generate_task_fields", task_fields))
        patches.enter_context(patch("app.agent.facade.resolve_execution_model", task_model))
        patches.enter_context(patch("app.harness.executor.stream", task_stream))
        async with main.app.other_asgi_app.router.lifespan_context(main.app.other_asgi_app):
            register_controller(ScriptedController())
            yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/__test/ready")
async def ready():
    return {"ready": True}


@app.post("/api/__test/seed")
async def seed(mode: str = "normal", mfa: bool = False):
    if mode not in {"normal", "tools", "error", "task", "missing-terminal", "interruptible"}:
        raise HTTPException(400, "Unknown scenario")
    suffix = uuid4().hex[:12]
    async with get_db_session() as db:
        owner = User(
            email=f"e2e-{suffix}@example.com", display_name="Browser Tester",
            hashed_password=encrypt_password("Browser-test-password-42!"),
            is_active=True, language="fr",
        )
        if mfa:
            from core.util.encryption import encrypt_value
            owner.totp_enabled = True
            owner.totp_secret_encrypted = encrypt_value("JBSWY3DPEHPK3PXP")
        title = Title(label=f"Browser {suffix}", gender="M")
        db.add_all([owner, title])
        await db.flush()
        role = await db.scalar(select(Role).where(Role.code == "admin"))
        assert role is not None
        db.add(Assignment(user_id=owner.id, role_id=role.id, is_default=True))
        agent = Agent(
            user_id=owner.id, title_id=title.id, first_name="Browser", last_name=suffix,
            code=f"browser-{suffix}", agent_driver="internal",
        )
        db.add(agent)
        await db.flush()
        tool = await db.scalar(select(Tool).where(Tool.code == "chat"))
        assert tool is not None
        db.add(Connection(tool_id=tool.id, agent_id=agent.id, active=True))
        await db.commit()
        rooms = []
        for _ in range(2):
            room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
            assert room is not None
            gates[room.id] = asyncio.Event()
            modes[room.id] = mode
            rooms.append(str(room.id))
        return {"email": owner.email, "password": "Browser-test-password-42!", "rooms": rooms,
                "agent_id": agent.id}


@app.get("/api/__test/otp")
async def otp():
    from core.user.mfa_service import _totp
    return {"code": _totp("JBSWY3DPEHPK3PXP", int(time.time()) // 30)}


@app.post("/api/__test/notifications/{round_id}")
async def unknown_notifications(round_id: UUID):
    from app.conversation.models import ConversationTaskLink, ConversationProcessLink
    from app.messenger.models import Room
    from app.process.models import ProcessDefinition, ProcessRun
    from app.task.models import Task, TaskStatus

    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        if round_ is None or round_.status != "SUCCEEDED":
            raise HTTPException(409, "A completed round is required")
        room = await db.get(Room, round_.room_id)
        assert room is not None
        connection = await db.get(Connection, room.connection_id)
        assert connection is not None
        task = Task(agent_id=connection.agent_id, label="Notification E2E", status=TaskStatus.SUCCESS)
        definition = ProcessDefinition(agent_id=connection.agent_id, tool_id=connection.tool_id,
                                       engine_process_id=uuid4().hex, label="Notification E2E")
        db.add_all([task, definition])
        await db.flush()
        process = ProcessRun(process_id=definition.id, launcher_agent_id=connection.agent_id,
                             engine_code="test", correlation_id=uuid4().hex, callback_token=uuid4().hex,
                             status="error", input={}, engine_metadata={}, error_message="Preserved")
        db.add(process)
        await db.flush()
        links = [ConversationTaskLink(round_id=round_id, task_id=task.id, action_key="e2e-task"),
                 ConversationProcessLink(round_id=round_id, process_run_id=process.id, action_key="e2e-process")]
        for link in links:
            link.notification_state = "UNKNOWN"
            link.notification_attempt_count = 1
        db.add_all(links)
        await db.commit()
        return {"task_id": str(task.id), "process_id": str(process.id)}


@app.get("/api/__test/notification-resolutions/{round_id}")
async def notification_resolutions(round_id: UUID):
    from app.conversation.models import (
        ConversationTaskLink, ConversationProcessLink, ConversationNotificationResolution,
    )
    from app.messenger.models import Message
    from app.task.models import Task
    from app.process.models import ProcessRun
    from sqlalchemy import func, or_

    async with get_db_session() as db:
        round_ = await db.get(ConversationRound, round_id)
        assert round_ is not None
        task = (await db.execute(select(ConversationTaskLink, Task).join(Task).where(
            ConversationTaskLink.round_id == round_id))).one()
        process = (await db.execute(select(ConversationProcessLink, ProcessRun).join(ProcessRun).where(
            ConversationProcessLink.round_id == round_id))).one()
        receipts = list(await db.scalars(select(ConversationNotificationResolution).where(or_(
            ConversationNotificationResolution.task_link_id == task[0].id,
            ConversationNotificationResolution.process_link_id == process[0].id,
        ))))
        return {
            "states": [task[0].notification_state, process[0].notification_state],
            "work_states": [task[1].status.value, process[1].status],
            "evidence": [receipt.evidence for receipt in receipts],
            "messages": await db.scalar(select(func.count(Message.id)).where(Message.messenger_room_id == round_.room_id)),
        }


@app.post("/api/__test/release/{room_id}")
async def release(room_id: UUID):
    if room_id not in gates:
        raise HTTPException(404)
    gates[room_id].set()
    return {"released": True}


@app.get("/api/__test/rounds/{room_id}")
async def rounds(room_id: UUID):
    async with get_db_session() as db:
        rows = list(await db.scalars(select(ConversationRound).where(ConversationRound.room_id == room_id)))
        return [{"id": str(row.id), "status": row.status, "delivery_state": row.delivery_state} for row in rows]


@app.get("/api/__test/tasks")
async def pending_tasks():
    return [
        {"name": task.get_name(), "stack": [f"{frame.f_code.co_name}:{frame.f_lineno}" for frame in task.get_stack()]}
        for task in asyncio.all_tasks()
        if "conversation" in task.get_name()
    ]


@app.get("/api/__test/subscription/{room_id}")
async def subscription(room_id: UUID):
    server = websocket._sio
    return {
        "joined": bool(server and list(server.manager.get_participants("/", f"ChatRoom:{room_id}"))),
        "rooms": [key for key in server.manager.rooms.get("/", {}) if key and key.startswith("ChatRoom:")] if server else [],
    }


app.mount("/", main.app)
