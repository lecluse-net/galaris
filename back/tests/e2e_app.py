"""Isolated browser-test composition root. Never imported by production.

The real API, authorization, Socket.IO, journal and schedulers run unchanged.
The conversation controller is scripted at its public port; provider adapters
are covered separately. A barrier, not a sleep, controls stream completion.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import ExitStack, asynccontextmanager
from dataclasses import replace
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException
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
from tests.e2e_tool_admin import router as tool_admin_fixture, remote_app as tool_admin_remote

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
gates: dict[UUID, asyncio.Event] = {}
modes: dict[UUID, str] = {}
quota_fixture = {"used": 2500, "status": 200, "codex_credits": 125.5}


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
    from app.llm.provider_facade import register_provider
    from bridge.elevenlabs import PROFILE as elevenlabs_profile
    from bridge.openrouter import PROFILE as openrouter_profile
    from bridge.fireworks import PROFILE as fireworks_profile
    from bridge.openai import CODEX_PROFILE as codex_profile
    # Run the real quota bridge over HTTP against a synthetic external-service boundary.
    register_provider(replace(elevenlabs_profile, base_url="http://127.0.0.1:8000/api/__test/elevenlabs/v1"))
    register_provider(replace(openrouter_profile, base_url="http://127.0.0.1:8000/api/__test/openrouter/v1"))
    register_provider(replace(fireworks_profile, base_url="http://127.0.0.1:8000/api/__test/fireworks/inference/v1"))
    register_provider(replace(codex_profile, base_url="http://127.0.0.1:8000/api/__test/chatgpt/codex"))

    async def emit(subject, action, data, room=None):
        if subject == "chat" and action == "runtime" and data.get("kind") == "finished":
            if modes.get(UUID(data["room_id"])) == "missing-terminal":
                return
        await original_emit(subject, action, data, room=room)

    with ExitStack() as patches:
        from tests.e2e_agent_admin import portrait_provider
        patches.enter_context(patch("app.image.generate_image_bytes", portrait_provider))
        patches.enter_context(patch("bridge.openai.codex_quota._USAGE_URL",
                                    "http://127.0.0.1:8000/api/__test/chatgpt/usage"))
        patches.enter_context(patch.object(websocket, "emit", emit))
        patches.enter_context(patch("app.conversation.mcp.generate_task_fields", task_fields))
        patches.enter_context(patch("app.agent.facade.resolve_execution_model", task_model))
        patches.enter_context(patch("app.harness.executor.stream", task_stream))
        # External mail boundaries only; approval persistence, Chat and RBAC remain real.
        from bridge.mail.contracts import MailPollBatch
        patches.enter_context(patch("bridge.mail.smtp_client.SmtpClient.send", return_value=(1, 0)))
        patches.enter_context(patch("bridge.mail.imap_client.ImapClient.poll_inbox",
                                    return_value=MailPollBatch(uid_validity=1, latest_uid=0)))
        async with main.app.other_asgi_app.router.lifespan_context(main.app.other_asgi_app):
            async with tool_admin_remote.router.lifespan_context(tool_admin_remote):
                register_controller(ScriptedController())
                yield


app = FastAPI(lifespan=lifespan)
app.include_router(tool_admin_fixture)
app.mount("/api/__test/mcp", tool_admin_remote)


@app.get("/api/__test/ready")
async def ready():
    return {"ready": True}


@app.put("/api/__test/provider-usage")
async def provider_usage(used: int = 2500, status: int = 200, codex_credits: float = 125.5):
    quota_fixture.update(used=used, status=status, codex_credits=codex_credits)
    return {"configured": True}


@app.post("/api/__test/codex-credits/{provider_id}")
async def connect_codex_credits(provider_id: int):
    from app.llm.provider_models import LLMProvider
    from core.util import get_encryption_service

    async with get_db_session() as db:
        provider = await db.get(LLMProvider, provider_id)
        if provider is None or provider.catalog_code != "openai-codex":
            raise HTTPException(404, "Synthetic Codex connection not found")
        provider.oauth_credentials = get_encryption_service().encrypt(json.dumps({
            "access_token": "synthetic-e2e-codex-token", "expires_at": time.time() + 3600,
        }))
        await db.commit()
    return {"connected": True}


@app.get("/api/__test/chatgpt/usage")
async def codex_usage(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-codex-token":
        raise HTTPException(401, "Synthetic unauthorized Codex token")
    if quota_fixture["status"] != 200:
        raise HTTPException(quota_fixture["status"], "Synthetic upstream unavailable")
    return {"rate_limit": {
        "primary_window": {"used_percent": 37, "limit_window_seconds": 18000},
        "secondary_window": {"used_percent": 0, "limit_window_seconds": 604800},
    }, "credits": {"has_credits": quota_fixture["codex_credits"] > 0,
                   "unlimited": False, "balance": str(quota_fixture["codex_credits"])}}


@app.get("/api/__test/chatgpt/codex/models")
async def codex_models(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-codex-token":
        raise HTTPException(401, "Synthetic unauthorized Codex token")
    return {"models": []}


@app.get("/api/__test/fireworks/inference/v1/models")
async def fireworks_models(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-fireworks-key":
        raise HTTPException(401, "Synthetic unauthorized key")
    return {"data": []}


@app.get("/api/__test/elevenlabs/v1/user/subscription")
async def elevenlabs_subscription(xi_api_key: str = Header()):
    if xi_api_key != "synthetic-e2e-quota-key":
        raise HTTPException(401, "Synthetic unauthorized key")
    if quota_fixture["status"] != 200:
        raise HTTPException(quota_fixture["status"], "Synthetic upstream unavailable")
    return {"character_count": quota_fixture["used"], "character_limit": 10000,
            "next_character_count_reset_unix": 2000000000}


@app.get("/api/__test/openrouter/v1/key")
async def openrouter_key(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-inference-key":
        raise HTTPException(401, "Synthetic unauthorized inference key")
    return {"data": {"limit": 10, "limit_remaining": 6, "is_management_key": False}}


@app.get("/api/__test/openrouter/v1/credits")
async def openrouter_credits(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-management-key":
        raise HTTPException(403, "Synthetic unauthorized management key")
    if quota_fixture["status"] != 200:
        raise HTTPException(quota_fixture["status"], "Synthetic upstream unavailable")
    return {"data": {"total_credits": 100, "total_usage": 25}}


@app.get("/api/__test/openrouter/v1/models")
async def openrouter_models(authorization: str = Header()):
    if authorization != "Bearer synthetic-e2e-inference-key":
        raise HTTPException(401, "Synthetic unauthorized inference key")
    return {"data": []}


@app.get("/api/__test/elevenlabs/v1/models")
async def elevenlabs_models():
    return []


@app.get("/api/__test/elevenlabs/v2/voices")
async def elevenlabs_voices():
    return {"voices": [], "has_more": False}


@app.post("/api/__test/seed")
async def seed(mode: str = "normal", mfa: bool = False):
    if mode not in {"normal", "tools", "error", "task", "missing-terminal", "interruptible", "mail"}:
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
        fixture = {"email": owner.email, "password": "Browser-test-password-42!", "rooms": rooms,
                   "agent_id": agent.id}
        if mode == "mail":
            from app.connection.models import ConnectionParam
            from bridge.mail.connection_service import resolve_connection
            from bridge.mail.contracts import OutgoingAttachment, OutgoingMail
            from bridge.mail.service import send_outgoing
            from core.util.encryption import encrypt_value
            mail = await db.scalar(select(Tool).where(Tool.code == "mail"))
            assert mail is not None
            connection = Connection(tool_id=mail.id, agent_id=agent.id, active=True)
            db.add(connection)
            await db.flush()
            params = {
                "email_address": f"agent-{suffix}@example.org",
                "password": encrypt_value("synthetic-mail-secret"),
                "imap_host": "mail.example.test", "smtp_host": "mail.example.test",
                "approval_required": "true", "approver_user_id": str(owner.id),
            }
            db.add_all([ConnectionParam(connection_id=connection.id, param_name=key, param_value=value)
                        for key, value in params.items()])
            await db.commit()
            receipt = await send_outgoing(await resolve_connection(connection.id, require_active=True), OutgoingMail(
                to=("recipient@example.org",), cc=(), bcc=("archive@example.org",),
                subject="Compte rendu synthétique", body="Voici le compte rendu à valider.", html_body=None,
                attachments=(OutgoingAttachment("rapport.txt", "text/plain", b"Synthetic report"),),
            ), idempotency_key=f"e2e-mail:{suffix}")
            fixture["delivery_id"] = str(receipt.delivery_id)
        return fixture


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


from tests.e2e_agent_admin import router as agent_admin_fixture_router
app.include_router(agent_admin_fixture_router)
app.mount("/", main.app)
