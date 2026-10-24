"""Isolated browser-test composition root. Never imported by production.

The real API, authorization, Socket.IO, journal and schedulers run. Only the
conversation recovery poll is accelerated in this isolated composition root.
The conversation controller is scripted at its public port; provider adapters
are covered separately. A barrier, not a sleep, controls stream completion.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import ExitStack, asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
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
from app.conversation.task_objective import PreparedTaskFields
from app.conversation.models import ConversationRound
from app.messenger import create_internal_room
from app.tools.models import Tool
from core.authorize.models import Assignment, Role
from core.database import get_db_session
from core import websocket
from core.user.models import User
from core.user.user_service import encrypt_password
from tests.e2e_tool_admin import router as tool_admin_fixture, remote_app as tool_admin_remote
from tests import e2e_call_recovery
from tests import e2e_conversation_control
from tests import e2e_process_conversations
from app.harness.executor import stream as internal_task_stream
from app.harness.runtime import build_model_for_llm as original_model_builder

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
gates: dict[UUID, asyncio.Event] = {}
modes: dict[UUID, str] = {}
first_mission_agents: set[int] = set()
tool_trace_gates: dict[int, asyncio.Event] = {}
quota_fixture = {"used": 2500, "status": 200, "codex_credits": 125.5}


class ScriptedController:
    async def run(self, turn: ConversationTurn) -> ConversationOutcome:
        if turn.agent_id in first_mission_agents or modes.get(turn.room_id) in {"conversation-control", "process-human"}:
            from app.harness.conversation import HarnessConversationController
            return await HarnessConversationController().run(turn)
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
        if modes.get(turn.room_id) in {"task", "task-tools", "call-recovery"}:
            assert turn.admit_background_task is not None
            async with get_db_session():
                await turn.admit_background_task(
                    "Produire le résultat de la tâche de test",
                    forced_route="EXEC", forced_effort="standard",
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
    return PreparedTaskFields(label_hint, objective_hint, 0.0)


async def task_model(_agent, effort, _language, _reasoning):
    return ResolvedModel(id=1, code="fixture", model_name="fixture", label="Fixture", requested_effort=effort)


async def task_stream(request):
    if request.agent.id in e2e_call_recovery.states:
        async for event in internal_task_stream(request):
            yield event
        return
    messages = []
    if request.agent.id in first_mission_agents:
        # Script the model boundary; creation, provenance, persistence and access stay real.
        from app.document import resource_service, DocumentItemCreate, DocumentPayload, DocumentSourceCreate
        async with get_db_session():
            document, _ = await resource_service.create_item(DocumentItemCreate(
                owner_agent_id=request.agent.id, title="Synthetic first mission summary",
                payload=DocumentPayload(text="<h1>Workshop summary</h1><p>The venue is booked.</p><p>Confirm speakers and invitations.</p>"),
                media_type="text/html", source=DocumentSourceCreate(
                    source_kind="task", source_ref=f"task:{request.task_id}",
                ),
            ), actor_task_id=request.task_id, deduplicate=False)
            uri = f"document://{document.id}"
        yield AgentEvent.from_result(ExecutionResult(prompt=request.objective, result=f"Saved: {uri}"))
        return
    if request.agent.id in tool_trace_gates:
        for name, success in (("fixture_lookup", True), ("fixture_denied", False)):
            message = AIMessage(type="tool", tool_name=name, tool_call_external_id=f"{name}-1",
                tool_arguments={"query": "Synthetic Task query", "secret": "synthetic-task-secret"},
                tool_result={"value": 42} if success else {"error": "Synthetic denial"},
                content="Synthetic lookup complete" if success else "Synthetic denial", success=success)
            messages.append(message)
            yield AgentEvent.from_message(message)
        await asyncio.wait_for(tool_trace_gates[request.agent.id].wait(), timeout=60)
    yield AgentEvent.from_message(AIMessage(type="text", content="Résultat durable de la tâche."))
    yield AgentEvent.from_result(ExecutionResult(prompt=request.objective, messages=messages, result="Résultat durable de la tâche."))


async def harness_model(llm, **kwargs):
    if kwargs.get("agent_id") in e2e_process_conversations.agents:
        return await e2e_process_conversations.build_model(llm, **kwargs)
    if kwargs.get("agent_id") in e2e_conversation_control.states:
        return await e2e_conversation_control.build_model(llm, **kwargs)
    if kwargs.get("agent_id") in e2e_call_recovery.states:
        return await e2e_call_recovery.build_model(llm, **kwargs)
    return await original_model_builder(llm, **kwargs)


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
        from tests.e2e_file_catalogue import BrowserFileTransport
        file_root = Path(patches.enter_context(TemporaryDirectory(prefix='e2e-catalogue-')))
        async def console_transport(ctx):
            return BrowserFileTransport(file_root / str(ctx.agent_id))
        patches.enter_context(patch('app.file_share.resource_service._console_transport', console_transport))
        from app.console import ConsoleRunResource
        from app.console.contracts import SshConnectionConfig
        async def console_resource(agent_id):
            resource = ConsoleRunResource(SshConnectionConfig(connection_id=1, host='synthetic.invalid',
                username='synthetic', private_key='synthetic', known_host_key='synthetic'))
            resource.files = BrowserFileTransport(file_root / str(agent_id))
            return resource
        patches.enter_context(patch('app.console.build_run_resource', console_resource))
        _app.state.file_catalogue_root = file_root
        from tests.e2e_agent_admin import portrait_provider
        # Exercise the real lock/lease recovery without spending 30 seconds on
        # each room-lock collision. Production keeps its own recovery cadence.
        patches.enter_context(patch("app.conversation.scheduler._POLL_SECONDS", 1.0))
        patches.enter_context(patch("app.image.generate_image_bytes", portrait_provider))
        patches.enter_context(patch("bridge.openai.codex_quota._USAGE_URL",
                                    "http://127.0.0.1:8000/api/__test/chatgpt/usage"))
        patches.enter_context(patch.object(websocket, "emit", emit))
        patches.enter_context(patch("app.conversation.mcp.generate_task_fields", task_fields))
        patches.enter_context(patch("app.agent.facade.resolve_execution_model", task_model))
        patches.enter_context(patch("app.harness.executor.stream", task_stream))
        patches.enter_context(patch("app.harness.runtime.build_model_for_llm", harness_model))
        patches.enter_context(patch("app.llm.structured_service.build_model_for_llm", harness_model))
        # External mail boundaries only; approval persistence, Chat and RBAC remain real.
        from bridge.mail.contracts import MailPollBatch
        from tests.e2e_mail import synthetic_inbound_message
        patches.enter_context(patch("bridge.mail.smtp_client.SmtpClient.send", return_value=(1, 0)))
        patches.enter_context(patch("bridge.mail.imap_client.ImapClient.store_sent_message", return_value="Sent"))
        patches.enter_context(patch("bridge.mail.imap_client.ImapClient.get_message", synthetic_inbound_message))
        patches.enter_context(patch("bridge.mail.imap_client.ImapClient.poll_inbox",
                                    return_value=MailPollBatch(uid_validity=1, latest_uid=0)))
        async with main.app.other_asgi_app.router.lifespan_context(main.app.other_asgi_app):
            async with tool_admin_remote.router.lifespan_context(tool_admin_remote):
                # Keep durable approval/outbox behavior, with a short isolated-test
                # cadence instead of the production maintenance interval.
                from app.task import scheduler as task_scheduler
                from app.tools.authorization_notifications import reconcile_authorizations
                task_scheduler.register_periodic_job("action-authorization-reconciliation", reconcile_authorizations, interval=.5)
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
async def seed(mode: str = "normal", mfa: bool = False, llm_configured: bool = True):
    if mode not in {"normal", "tools", "error", "task", "task-tools", "call-recovery", "conversation-control", "process-human", "first-mission", "missing-terminal", "interruptible", "mail", "mail-common", "mail-inbound", "file-catalogue", "personal-skills"}:
        raise HTTPException(400, "Unknown scenario")
    suffix = uuid4().hex[:12]
    async with get_db_session() as db:
        from app.llm import LLMProvider
        from app.llm.facade import resolve_provider_profile
        from core.util.encryption import get_encryption_service

        # Ready journeys need credentials as well as the installation's models.
        # Keep this provider on the synthetic loopback service in every scenario.
        provider = await db.scalar(select(LLMProvider).where(LLMProvider.catalog_code == "openrouter"))
        assert provider is not None
        profile = resolve_provider_profile(catalog_code=provider.catalog_code, base_url=provider.base_url)
        assert profile is not None
        provider.base_url = profile.base_url
        provider.is_active = True
        provider.api_key = (
            get_encryption_service().encrypt("synthetic-e2e-inference-key")
            if llm_configured else None
        )
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
        if mode == "first-mission":
            first_mission_agents.add(agent.id)
        if mode == "process-human":
            from app.tools import sync_integrated_tool_connections
            await sync_integrated_tool_connections(agent.id)
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
        if mode == "personal-skills":
            from app.connection import ConnectionParam
            from app.skill.interface import create_package
            from app.skill.contracts import SkillPackageCreate
            recipient = Agent(user_id=owner.id, title_id=title.id, first_name="Recipient", last_name=suffix,
                              code=f"recipient-{suffix}", agent_driver="internal")
            db.add(recipient)
            await db.flush()
            fixture.update({"recipient_id": recipient.id, "recipient_label": f"Recipient {suffix}"})
            skill_tool = await db.scalar(select(Tool).where(Tool.code == "skills"))
            connection = Connection(tool_id=skill_tool.id, agent_id=agent.id, active=True)
            db.add(connection)
            await db.flush()
            db.add(ConnectionParam(connection_id=connection.id, param_name="tools.management_scope", param_value="personal"))
            await db.commit()
            packages = []
            for label in ("A Synthetic private guide", "B Synthetic disposable guide"):
                label = f"{label} {suffix}"
                code = f"private-{uuid4().hex[:12]}"
                package = await create_package(SkillPackageCreate(code=code, label=label,
                    markdown=f"---\nname: {code}\ndescription: Synthetic private instructions.\n---\nOriginal private procedure\n"), actor_agent_id=agent.id)
                packages.append({**package.model_dump(mode="json"), "label": label})
            fixture.update({"personal_skills": packages, "agent_label": f"Browser {suffix}"})
        if mode == "task-tools":
            tool_trace_gates[agent.id] = asyncio.Event()
        if mode == "call-recovery":
            e2e_call_recovery.register(agent.id)
        if mode in {"conversation-control", "process-human"}:
            # Other journeys can select an image-only installation profile.
            # This real-harness scenario owns its text configuration.
            from app.llm import LLM, LlmProfile
            model = LLM(llm_provider_id=provider.id, code=f"control-{suffix}",
                        llm_name=f"synthetic-control-{suffix}", label="Synthetic conversation control")
            db.add(model)
            await db.flush()
            control_profile = LlmProfile(code=f"control-{suffix}", label="Synthetic conversation control",
                                         text_low_llm_id=model.id, text_standard_llm_id=model.id)
            db.add(control_profile)
            await db.flush()
            agent.profile_id = control_profile.id
            await db.commit()
            e2e_conversation_control.register(agent.id)
            if mode == "process-human":
                e2e_process_conversations.agents.add(agent.id)
        if mode == 'file-catalogue':
            from tests.e2e_file_catalogue import seed_catalogue
            fixture.update(await seed_catalogue(agent.id, app.state.file_catalogue_root))
        if mode in ("mail", "mail-common", "mail-inbound"):
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
                "approver_user_id": str(owner.id),
            }
            db.add_all([ConnectionParam(connection_id=connection.id, param_name=key, param_value=value)
                        for key, value in params.items()])
            await db.commit()
            # Exercise a historical pending delivery after the common policy
            # migration. New connection configuration no longer owns this flag.
            historical_config = (await resolve_connection(connection.id, require_active=True)).model_copy(
                update={"approval_required": True},
            )
            outgoing = OutgoingMail(
                to=("recipient@example.org",), cc=(), bcc=("archive@example.org",),
                subject="Compte rendu synthétique", body="Voici le compte rendu à valider.", html_body=None,
                attachments=(OutgoingAttachment("rapport.txt", "text/plain", b"Synthetic report"),),
            )
            if mode == "mail-inbound":
                from tests.e2e_mail import seed_inbound_mail
                fixture.update(await seed_inbound_mail(historical_config.model_copy(update={"approval_required": False})))
            elif mode == "mail-common":
                from tests.e2e_mail import seed_common_mail
                fixture.update(await seed_common_mail(historical_config.model_copy(update={"approval_required": False}),
                    outgoing, f"e2e-mail:{suffix}"))
            else:
                receipt = await send_outgoing(historical_config, outgoing, idempotency_key=f"e2e-mail:{suffix}")
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
    async with get_db_session() as db:
        from app.messenger import Room
        room = await db.get(Room, room_id)
        connection = await db.get(Connection, room.connection_id)
        if connection.agent_id in e2e_conversation_control.states:
            e2e_conversation_control.states[connection.agent_id]["gate"].set()
    return {"released": True}


@app.get("/api/__test/rounds/{room_id}")
async def rounds(room_id: UUID):
    async with get_db_session() as db:
        rows = list(await db.scalars(select(ConversationRound).where(ConversationRound.room_id == room_id)))
        return [{"id": str(row.id), "status": row.status, "delivery_state": row.delivery_state} for row in rows]


@app.post("/api/__test/task-tools/{agent_id}/release")
async def release_tool_trace(agent_id: int):
    tool_trace_gates[agent_id].set()
    return {"released": True}


@app.get("/api/__test/tasks")
async def pending_tasks():
    return [
        {"name": task.get_name(), "stack": [f"{frame.f_code.co_name}:{frame.f_lineno}" for frame in task.get_stack()]}
        for task in asyncio.all_tasks()
        if "conversation" in task.get_name() or task.get_name().startswith("task-")
    ]


@app.get("/api/__test/call-recovery/{agent_id}")
async def call_recovery_state(agent_id: int):
    from app.task.models import Task, TaskAttempt
    from core.params import runtime_settings
    from app.harness.run_control import is_active
    async with get_db_session() as db:
        task = await db.scalar(select(Task).where(Task.agent_id == agent_id))
        attempt = await db.scalar(select(TaskAttempt).where(TaskAttempt.task_id == task.id)
            .order_by(TaskAttempt.attempt_number.desc()).limit(1)) if task else None
        return {**e2e_call_recovery.states[agent_id], "task_id": str(task.id) if task else None,
                "status": task.status.value if task else None,
                "attempts": task.attempt_count if task else 0,
                "cancel_requested": task.cancel_requested if task else False,
                "debug": {"lease_seconds": runtime_settings.TASK_SCHEDULER_LEASE_SECONDS,
                    "lease_expires_at": str(task.lease_expires_at) if task else None,
                    "recovery": (attempt.data or {}).get("call_recovery") if attempt else None,
                    "runtime_active": is_active(UUID(task.data["_agent_run_identity"]["request_run_id"]))
                        if task and (task.data or {}).get("_agent_run_identity") else False}}


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
