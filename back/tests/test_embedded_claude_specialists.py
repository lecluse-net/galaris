"""Qualify specialist media calls and their originating embedded attempt."""

import asyncio
import json
import wave
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.chat.tests.test_attachment_http import attachment_context as attachment_context
from app.chat.tests.test_deep import room_info
from app.conversation import ConversationExecutionError, ConversationRoundAttempt, deep
from app.conversation.service import build_turn, claim_next_round, complete_round
from app.file_share import ResourceContext, resource_create
from app.harness import claude_driver
from app.harness.conversation import HarnessConversationController
from app.llm import LLM, llm_call_service, media_facade, provider_scheduler, transcription_service
from app.llm.media_contracts import MediaResult
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from app.llm.provider_facade import TranscriptionResult
from app.task import Task, TaskStatus, scheduler
from app.task.models import TaskAttempt
from core.database import get_db_session
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_embedded_claude_media import _png
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


def _wav() -> bytes:
    with BytesIO() as target:
        with wave.open(target, "wb") as stream:
            stream.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\x00\x00" * 1600)
        return target.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(("entry", "kind"), [
    ("chat", "image"), ("deep", "audio"), ("task", "video"), ("chat-stale", "audio"),
])
async def test_specialist_media_keeps_the_origin_even_with_a_different_model(
    attachment_context, runtime, monkeypatch, tmp_path, entry, kind,
):
    db, model, requests, mode = runtime
    context = attachment_context
    agent_id, room_id = context["agent_id"], context["room_id"]
    agent = await db.get(Agent, agent_id)
    assert agent is not None
    workspace = tmp_path / "claude"
    workspace.mkdir()
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", workspace)
    mode["concurrent"] = True
    specialist = LLM(
        llm_provider_id=model.llm_provider_id, code=f"synthetic-specialist-{uuid4()}", label="Synthetic specialist",
        llm_name=f"specialist-{kind}", output_text=True, input_image=kind == "image", input_audio=kind == "audio",
        input_video=kind == "video", primary_capability="video_understanding" if kind == "video" else "chat",
    )
    db.add(specialist)
    await db.flush()
    profile = LlmProfile(label="Synthetic specialist profile", text_low_llm_id=model.id, text_standard_llm_id=model.id,
                         vision_llm_id=specialist.id, transcription_llm_id=specialist.id, video_llm_id=specialist.id)
    db.add(profile)
    await db.flush()
    agent.agent_driver, agent.profile_id = "claude_embedded", profile.id
    model.input_image = model.input_audio = model.input_video = False

    sentinel = f"Synthetic specialist result for {kind}."
    purpose = {"image": "image.analysis", "audio": "audio.transcription", "video": "multimedia.video_read"}[kind]
    provider_calls = []

    async def check_admission(path):
        assert path.is_file() and path.read_bytes() == data
        async with get_db_session() as reader:
            call = await reader.scalar(select(LLMCall).where(LLMCall.agent_id == agent_id, LLMCall.purpose == purpose))
            assert call is not None and call.status == "running" and call.llm_id == specialist.id
            assert call.agent_run_id is not None and call.requester_user_id == context["user_id"]
            provider_calls.append(path)

    if kind == "image":
        data, name = _png(), "specialist-image.png"
        mode["chat_json"] = sentinel
    elif kind == "audio":
        data, name = _wav(), "specialist-audio.wav"

        async def transcribe(_connection, *, model, source, **_kwargs):
            assert model == specialist.llm_name
            await check_admission(source)
            return TranscriptionResult(text=sentinel)

        monkeypatch.setattr(transcription_service, "transcription_provider_for", lambda _connection: SimpleNamespace(transcribe=transcribe))
    else:
        name = "specialist-video.mp4"
        source = tmp_path / name
        ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:size=32x32:rate=8", "-t", "0.5",
            "-threads", "1", "-c:v", "mpeg4", str(source), stderr=asyncio.subprocess.PIPE,
        )
        _, error = await ffmpeg.communicate()
        assert ffmpeg.returncode == 0, error.decode()
        data = source.read_bytes()
        monkeypatch.setattr(media_facade.llm_provider_service, "decrypt_api_key", lambda _key: "synthetic-provider-key")

        async def analyze(_connection, request, path, media_type):
            assert request.model == specialist.llm_name and media_type == "video/mp4"
            await check_admission(path)
            return MediaResult("success", text=sentinel, cost=0.01)

        provider = SimpleNamespace(analyze=analyze, supports=lambda *_args: True, validate=lambda _request: None)
        monkeypatch.setattr(media_facade, "media_provider_for", lambda _connection: provider)

    resource = await resource_create(ResourceContext(agent_id, "internal"), "file://", data, name=name)
    await db.commit()
    async with _gateway(monkeypatch), asyncio.timeout(60):
        if entry == "task":
            task = Task(label="Synthetic media task", objective="Read the attached synthetic video.", status=TaskStatus.CREATE,
                        agent_id=agent_id, requester_user_id=context["user_id"], ai=True, forced_route="EXEC",
                        forced_effort="standard", data={"resource_uris": [resource.uri]})
            db.add(task)
            await db.commit()
            assert await scheduler.run_once()
            await db.refresh(task)
            if task.status != TaskStatus.SUCCESS:
                assert await scheduler.run_once()
                await db.refresh(task)
            assert task.status == TaskStatus.SUCCESS and task.get_execution_result().result == "Bonjour !"
            owner_id = task.id
        else:
            sent = await context["client"].post(f"/api/chat/rooms/{room_id}/messages", headers=context["headers"], json={
                "text": "@deep Read this clip" if entry == "deep" else "Read this picture", "language": "en",
                "client_message_id": str(uuid4()), "resource_uris": [resource.uri],
            })
            assert sent.status_code == 201, sent.text
            if entry == "deep":
                claim = await deep._claim()
                assert claim is not None
                await deep._run(*claim)
                [submission] = (await room_info(context, room_id))["submissions"]
                assert submission["state"] == "completed", submission
                owner_id = UUID(submission["id"])
            else:
                round_ = await claim_next_round("claude-specialist-test")
                assert round_ is not None and round_.lease_token is not None and round_.room_id == room_id
                round_.response_only = True
                turn = await build_turn(round_.id, lease_token=round_.lease_token)
                await db.commit()
                if entry == "chat-stale":
                    queued, released = asyncio.Event(), asyncio.Event()
                    acquire = provider_scheduler.acquire_call

                    async def pause_after_acquiring(*args, **kwargs):
                        permit = await acquire(*args, **kwargs)
                        queued.set()
                        try:
                            await released.wait()
                            return permit
                        except BaseException:
                            permit.release()
                            raise

                    monkeypatch.setattr(provider_scheduler, "acquire_call", pause_after_acquiring)

                    async def run_turn():
                        async with get_db_session():
                            return await HarnessConversationController().run(turn)

                    run = asyncio.create_task(run_turn())
                    try:
                        while not queued.is_set() and not run.done():
                            await asyncio.sleep(0.025)
                        assert queued.is_set()
                        round_.lease_token = uuid4()
                        await db.commit()
                    finally:
                        released.set()
                    with pytest.raises((PermissionError, ConversationExecutionError)):
                        await run
                    assert not provider_calls and not requests
                    assert not list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent_id)))
                    assert list(workspace.iterdir()) == []
                    return
                outcome = await HarnessConversationController().run(turn)
                assert outcome.text == "Bonjour !"
                await complete_round(round_.id, outcome, lease_token=round_.lease_token)
                owner_id = round_.id

    assert sentinel in json.dumps(requests[-1]["messages"])
    assert all(not path.exists() for path in provider_calls)
    assert len(provider_calls) == int(kind != "image")
    main_purpose = {"chat": "conversation.text", "deep": "conversation.deep", "task": "agent.exec"}[entry]
    calls = {call.purpose: call for call in await db.scalars(select(LLMCall).where(
        LLMCall.agent_id == agent_id, LLMCall.purpose.in_((purpose, main_purpose)),
    ))}
    assert calls.keys() == {purpose, main_purpose}
    fallback, main = calls[purpose], calls[main_purpose]
    assert fallback.status == main.status == "completed" and fallback.llm_id == specialist.id and main.llm_id == model.id
    assert fallback.requester_user_id == main.requester_user_id == context["user_id"]
    assert fallback.agent_run_id == main.agent_run_id and fallback.correlation_ref == main.correlation_ref
    if entry == "task":
        assert fallback.task_id == main.task_id == owner_id and fallback.task_attempt_id == main.task_attempt_id
        attempt = await db.get(TaskAttempt, fallback.task_attempt_id)
        assert attempt is not None and attempt.task_id == owner_id
        assert {call.id for call in await llm_call_service.list_calls(task_id=owner_id)} >= {fallback.id, main.id}
        assert await llm_call_service.cost_for_task(owner_id) >= 0.01
    elif entry == "chat":
        assert fallback.conversation_round_id == main.conversation_round_id == owner_id
        attempt_id = await db.scalar(select(ConversationRoundAttempt.id).where(ConversationRoundAttempt.round_id == owner_id))
        assert fallback.correlation_ref == f"round:{owner_id}:attempt:{attempt_id}"
    else:
        assert fallback.deep_submission_id == main.deep_submission_id == owner_id
        assert fallback.deep_session_id == main.deep_session_id and fallback.deep_session_id is not None
    assert list(workspace.iterdir()) == []
