"""Exercise a live routing rollback through the authenticated application APIs."""

import asyncio
from uuid import UUID, uuid4

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from app.agent import Agent, Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundAttempt, ConversationRoundMessage
from app.conversation.service import build_turn, claim_next_round, complete_round
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.harnesses.models import AgentHarness
from app.llm import profile_service
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from app.services import ServiceModel
from core.authorize import Assignment, Role
from core.database import get_db_session, middleware
from core.params import Param, Params, runtime_settings
from core.user.auth_service import create_access_token_for_user
from core.user.models import User
from core.util import get_encryption_service
from main import app
from tests.test_embedded_claude_chat_effects import _http_server
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", ["claude_embedded", "codex", "deepseek_harness"])
async def test_conversation_rollback_preserves_admitted_rounds_and_task_assignment(
    runtime, committed_database, monkeypatch, tmp_path, assignment,
):
    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", False)
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED", True)
    mode["concurrent"] = True
    gate = mode["gate"] = asyncio.Event()
    model.provider.max_concurrent_calls = 3

    user = User(email=f"rollback-{uuid4().hex}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic rollback", text_low_llm_id=model.id, text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    role = await db.scalar(select(Role).where(Role.code == "admin"))
    title = await db.scalar(select(Title.id).limit(1))
    service = await db.scalar(select(ServiceModel).where(ServiceModel.code == "chat"))
    assert role is not None and title is not None and service is not None
    db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    managed = assignment != "claude_embedded"
    task_driver = "openai_messages" if managed else assignment
    agent = Agent(user_id=user.id, title_id=title, code=f"rollback-{uuid4().hex}",
                  first_name="Synthetic", last_name="Rollback", profile_id=profile.id, agent_driver=task_driver)
    db.add(agent)
    await db.flush()
    db.add(Connection(service_id=service.id, agent_id=agent.id, active=True))
    if managed:
        assignment_record = AgentHarness(
            agent_id=agent.id, provider_code=assignment, lifecycle_status="ready",
            runtime_base_url="https://unused-managed-runtime.invalid", runtime_model="synthetic-task-model",
            runtime_token_encrypted=get_encryption_service().encrypt("synthetic-rollback-credential"),
        )
        db.add(assignment_record)
    await db.commit()
    assert await profile_service.set_current_profile_id(profile.id)
    token = await create_access_token_for_user(user, db, role_id=role.id)
    await db.commit()

    async with _http_server(app) as origin, AsyncClient(
        base_url=origin, headers={"Authorization": f"Bearer {token}"}, timeout=15, trust_env=False,
    ) as client, asyncio.timeout(40):
        monkeypatch.setattr(claude_driver, "CLAUDE_GATEWAY", f"{origin}/api/llm/anthropic")

        async def set_parameter(name, value):
            response = await client.put(f"/api/params/{name}", json={"value": value})
            assert response.status_code == 200, response.text

        async def submit(label):
            room = await client.post("/api/chat/rooms", json={"agent_id": agent.id, "label": label})
            assert room.status_code == 201, room.text
            response = await client.post(f"/api/chat/rooms/{room.json()['id']}/messages", json={
                "client_message_id": str(uuid4()), "text": label, "language": "en",
            })
            assert response.status_code == 201, response.text
            round_ = await db.scalar(select(ConversationRound).join(
                ConversationRoundMessage, ConversationRoundMessage.round_id == ConversationRound.id,
            ).where(ConversationRoundMessage.message_id == UUID(response.json()["id"])))
            assert round_ is not None
            return round_

        async def run_next(round_id, expected_driver):
            async with get_db_session():
                round_ = await claim_next_round("claude-rollback-test")
                assert round_ is not None and round_.id == round_id and round_.lease_token is not None
                lease_token = round_.lease_token
                turn = await build_turn(round_id, lease_token=lease_token)
            assert turn.driver_code == expected_driver
            outcome = await HarnessConversationController().run(turn)
            assert outcome.execution_result is not None
            assert outcome.execution_result.metadata["driver_code"] == expected_driver
            async with get_db_session():
                assert await complete_round(round_id, outcome, lease_token=lease_token) == "SUCCEEDED"

        await set_parameter(Params.HARNESS_CLAUDE_EMBEDDED_ENABLED, "true")
        first = await submit("Synthetic Claude in-flight")
        queued = await submit("Synthetic Claude queued")
        assert first.driver_code == queued.driver_code == "claude_embedded"
        assignment_before = (await client.get(f"/api/harnesses/agents/{agent.id}")).raise_for_status().json()
        first_worker = asyncio.create_task(run_next(first.id, "claude_embedded"))
        try:
            while not requests:
                if first_worker.done():
                    await first_worker
                    pytest.fail("Claude finished without visiting the provider")
                await asyncio.sleep(0.01)
            await set_parameter(Params.HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED, "false")
            assert runtime_settings.HARNESS_CLAUDE_EMBEDDED_ENABLED is True
            assert not first_worker.done()
            new = await submit("Synthetic Pydantic after rollback")
            assert new.driver_code == "internal"
            gate.set()
            await first_worker
        finally:
            gate.set()
            if not first_worker.done():
                first_worker.cancel()
                await asyncio.gather(first_worker, return_exceptions=True)

        await run_next(queued.id, "claude_embedded")
        await run_next(new.id, "internal")
        assert await db.scalar(select(Param.value).where(
            Param.name == Params.HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED,
        )) == "false"
        assignment_after = (await client.get(f"/api/harnesses/agents/{agent.id}")).raise_for_status().json()
        assert assignment_after == assignment_before and assignment_after["driver_code"] == task_driver
        if managed:
            saved = await db.get(AgentHarness, assignment_record.id, populate_existing=True)
            assert saved is not None and saved.revision == 1
            assert get_encryption_service().decrypt(saved.runtime_token_encrypted) == "synthetic-rollback-credential"

        for round_, expected_driver in ((first, "claude_embedded"), (queued, "claude_embedded"), (new, "internal")):
            await db.refresh(round_)
            assert round_.driver_code == expected_driver and round_.status == "SUCCEEDED"
            call = await db.scalar(select(LLMCall).where(
                LLMCall.conversation_round_id == round_.id, LLMCall.purpose == "conversation.text",
            ))
            assert call is not None and call.agent_run_id == round_.id and call.task_id is None
            if expected_driver == "claude_embedded":
                attempt = await db.scalar(select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id == round_.id))
                assert attempt is not None and call.correlation_ref == f"round:{round_.id}:attempt:{attempt.id}"
            else:
                assert call.correlation_ref is None

        await set_parameter(Params.HARNESS_CLAUDE_EMBEDDED_CONVERSATIONS_ENABLED, "true")
        reenabled = await submit("Synthetic Claude after reactivation")
        assert reenabled.driver_code == "claude_embedded"
        await run_next(reenabled.id, "claude_embedded")
