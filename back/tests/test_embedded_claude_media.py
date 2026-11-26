"""Qualify reopened attachment resources through the real internal harnesses."""

import asyncio
import base64
import json
import random
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app.agent import Agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.chat.tests.test_deep import room_info
from app.conversation import DeepSession, deep
from app.conversation.models import ConversationRoundAttempt
from app.conversation.service import build_turn, claim_next_round, complete_round
from app.file_share import ResourceContext, resource_create, resource_delete
from app.harness import claude_driver
from app.harness.claude_session import ClaudeSession
from app.harness.conversation import HarnessConversationController
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from core.params import runtime_settings
from core.util import get_encryption_service
from tests.test_document_pipeline import pdf
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


def _png() -> bytes:
    data = random.Random(327).randbytes(128 * 128 * 3)
    with Image.frombytes("RGB", (128, 128), data) as image, BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("driver", ["internal", "claude_embedded"], ids=["pydantic", "claude"])
@pytest.mark.parametrize("entry", ["chat", "deep", "chat-budget", "chat-pdf", "chat-pdf-text"])
async def test_current_and_historical_media_require_access(
    attachment_context, runtime, monkeypatch, tmp_path, entry, driver,
):
    db, model, requests, mode = runtime
    context = attachment_context
    room_id, agent_id = context["room_id"], context["agent_id"]
    agent = await db.get(Agent, agent_id)
    assert agent is not None
    workspace = tmp_path / "claude"
    workspace.mkdir()
    monkeypatch.setattr(runtime_settings, "HARNESS_CLAUDE_EMBEDDED_ENABLED", True)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    if entry == "chat-budget":
        monkeypatch.setattr(runtime_settings, "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", 1024)
    receipts = []
    mode.update(concurrent=True, chat_response_ids=receipts)
    document = entry.startswith("chat-pdf")
    model.input_image = not document
    model.input_file = entry == "chat-pdf"
    model.context_length = 131_072
    profile = LlmProfile(label="Synthetic media profile", text_low_llm_id=model.id, text_standard_llm_id=model.id)
    db.add(profile)
    await db.flush()
    agent.agent_driver = driver
    agent.profile_id = profile.id
    if document:
        source = tmp_path / "synthetic-report.pdf"
        pdf(source)
        media = source.read_bytes()
        file_name = source.name
    else:
        media, file_name = _png(), "synthetic-pattern.png"
    encoded = base64.b64encode(media).decode()
    resource_scope = ResourceContext(agent_id, "internal")
    resource = await resource_create(resource_scope, "file://", media, name=file_name)
    await db.commit()

    histories = []

    async def submit(text, *, attach=False):
        if entry == "deep":
            text = f"@deep {text}"
        sent = await context["client"].post(f"/api/chat/rooms/{room_id}/messages", headers=context["headers"], json={
            "text": text, "language": "en", "client_message_id": str(uuid4()),
            "resource_uris": [resource.uri] if attach else [],
        })
        assert sent.status_code == 201, sent.text
        if entry == "deep":
            claim = await deep._claim()
            assert claim is not None
            await deep._run(*claim)
            result = (await room_info(context, room_id))["submissions"][-1]
            assert result["state"] == "completed" and result["response_message_id"], result
            session = await db.get(DeepSession, UUID(result["session_id"]), populate_existing=True)
            assert session is not None and session.native_history is not None
            assert session.driver_code == driver
            history = get_encryption_service().decrypt(session.native_history)
            if driver == "claude_embedded":
                history = ClaudeSession.from_deep_history(history, session.id).transcript
            histories.append(history)
            return UUID(result["id"]), session.id
        round_ = await claim_next_round("attachment-harness-test")
        assert round_ is not None and round_.room_id == room_id and round_.lease_token is not None
        round_.response_only = True
        turn = await build_turn(round_.id, lease_token=round_.lease_token)
        assert turn.driver_code == driver
        await db.commit()
        outcome = await HarnessConversationController().run(turn)
        assert outcome.text == "Bonjour !"
        assert await complete_round(round_.id, outcome, lease_token=round_.lease_token) == "SUCCEEDED"
        return round_.id, None

    async with _gateway(monkeypatch), asyncio.timeout(60):
        first, first_session = await submit("", attach=True)
        second, second_session = await submit("Synthetic later question about the pattern.")
        await resource_delete(resource_scope, resource.uri)
        await db.commit()
        third, third_session = await submit("Synthetic follow-up after access changed.")

    assert len(requests) == 3
    first_wire, second_wire, third_wire = map(json.dumps, requests)
    # Legacy Pydantic Deep carries the canonical URI in its history. Chat and
    # Claude Deep also supply authorized native content to the model.
    supplies_native_media = entry != "deep" or driver == "claude_embedded"
    if entry == "chat-budget":
        assert all(encoded not in item for item in (first_wire, second_wire))
        assert "exceeds the remaining native media byte budget" in first_wire
    elif entry == "chat-pdf-text":
        assert all("Synthetic report sentinel page" in item and encoded not in item for item in (first_wire, second_wire))
        assert "Synthetic report sentinel page" not in third_wire
    elif entry == "chat-pdf":
        for body in requests[:2]:
            parts = [part for item in body["messages"] if isinstance(item["content"], list) for part in item["content"]]
            assert [part["file"]["file_data"] for part in parts if part["type"] == "file"] == [f"data:application/pdf;base64,{encoded}"]
    elif supplies_native_media:
        for body in requests[:2]:
            parts = [part for item in body["messages"] if isinstance(item["content"], list) for part in item["content"]]
            assert [part["image_url"]["url"] for part in parts if part["type"] == "image_url"] == [f"data:image/png;base64,{encoded}"]
        if driver == "claude_embedded":
            assert "Current message attachments" in first_wire and "Historical message attachments" in second_wire
    assert encoded not in third_wire
    if supplies_native_media:
        assert "resource unavailable or access denied" in third_wire
    assert all(resource.uri in wire for wire in (first_wire, second_wire, third_wire))
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent_id)))
    assert len(calls) == 3
    by_receipt = {call.upstream_request_id: call for call in calls}
    assert set(by_receipt) == set(receipts)
    attempts = dict((await db.execute(select(ConversationRoundAttempt.round_id, ConversationRoundAttempt.id)
        .where(ConversationRoundAttempt.round_id.in_((first, second, third))))).tuples().all())
    for receipt, origin, session_id in zip(
        receipts, (first, second, third), (first_session, second_session, third_session), strict=True,
    ):
        call = by_receipt[receipt]
        assert call.task_id is None and call.task_attempt_id is None
        assert call.agent_run_id == origin
        if entry == "deep":
            assert call.deep_session_id == session_id and call.conversation_round_id is None
            if driver == "claude_embedded":
                assert call.deep_submission_id == origin
                assert call.correlation_ref == f"deep:{session_id}:submission:{origin}"
        else:
            assert call.conversation_round_id == origin
            assert call.deep_submission_id is None and call.deep_session_id is None
            if driver == "claude_embedded":
                assert call.correlation_ref == f"round:{origin}:attempt:{attempts[origin]}"
    assert all(encoded not in history and "[Galaris media for this attempt]" not in history for history in histories)
    assert list(workspace.iterdir()) == []
