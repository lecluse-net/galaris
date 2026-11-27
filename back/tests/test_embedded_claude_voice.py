"""Exercise the voice engine with the bundled SDK, gateway and durable round claims."""

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.agent import Agent, Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundAttempt, ConversationRoundMessage
from app.conversation.checkpoint_journal import read_checkpoint_payload
from app.harness import claude_driver
from app.harnesses.models import AgentHarness
from app.llm import profile_service, transcription_service, tts_service
from app.llm.embedded_runtime import EmbeddedRoundInference
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM
from app.memory import acquisition_service
from app.memory.models import MemoryItem
from app.messenger import Message, MessengerUser, Room, RoomUser
from app.services import ServiceModel
from app.voice import agent_voice_call_available, conversation_service, engine as voice_engine
from app.voice.models import AudioFrame, VoiceConversationStatus
from app.voice.realtime_engine import RealtimeAgentVoiceEngine
from app.voice.tests.test_engine import _Transport
from app.voice.turn_detection import SpeechUtterance
from bridge.openai.realtime import OpenAIRealtime
from core.database import middleware
from core.params import runtime_settings
from core.user.models import User
from core.util import get_encryption_service
from tests.test_embedded_claude_chat_effects import _gateway
from tests.test_inference_lifecycle import runtime  # noqa: F401 - shared provider fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", ["claude_embedded", "codex", "deepseek_harness"])
async def test_native_voice_configuration_depends_on_the_agent_assignment(
    runtime, committed_database, monkeypatch, assignment,
):
    db, model, _, _ = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    managed = assignment != "claude_embedded"
    model.provider.catalog_code = "openai-api"
    model.provider.api_key = get_encryption_service().encrypt("synthetic-openai-key")
    model.service_capabilities = ["realtime_conversation"]
    user = User(email=f"synthetic-native-voice-{uuid4()}@example.test", hashed_password="unused")
    db.add(user)
    await db.flush()
    agent = Agent(
        user_id=user.id, title_id=await db.scalar(select(Title.id).limit(1)),
        code=f"native-voice-{uuid4().hex}", first_name="Synthetic", last_name="Voice",
        agent_driver="openai_messages" if managed else assignment,
        voice=f"realtime:{model.id}:voice%3Amarin",
    )
    db.add(agent)
    await db.flush()
    if managed:
        db.add(AgentHarness(
            agent_id=agent.id, provider_code=assignment, lifecycle_status="ready",
            runtime_base_url="https://unused-managed-runtime.invalid", runtime_model="synthetic",
            runtime_token_encrypted=get_encryption_service().encrypt("synthetic-credential"),
        ))
    await db.commit()
    native_session = AsyncMock(side_effect=AssertionError("provider conversation selected for a Claude call"))
    monkeypatch.setattr(OpenAIRealtime, "create_realtime_session", native_session)
    monkeypatch.setattr(transcription_service, "transcription_available_for_agent", AsyncMock(return_value=False))

    async def create_engine():
        return await RealtimeAgentVoiceEngine.create(
            transport=_Transport(), handle=object(), agent_id=agent.id, session_id=uuid4(),
            room_id="synthetic-room", connection_id=None, language="fr",
            stop_requested=asyncio.Event(),
        )

    if managed:
        assert await agent_voice_call_available(agent.id)
        assert isinstance(await create_engine(), RealtimeAgentVoiceEngine)
    else:
        assert not await agent_voice_call_available(agent.id)
        with pytest.raises(RuntimeError, match="require a configured transcription model"):
            await create_engine()
    native_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", [
    "internal", "claude_embedded", "codex", "deepseek_harness", "interrupted", "interrupted_effect", "native_openai",
    "native_openai_reconnect",
])
async def test_cascaded_voice_uses_the_selected_harness_and_exact_round(
    runtime, committed_database, monkeypatch, tmp_path, assignment,
):
    db, model, requests, mode = runtime
    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(claude_driver, "CLAUDE_WORKSPACE_ROOT", tmp_path)
    mode["concurrent"] = True
    mode["gate"] = asyncio.Event()
    interrupted = assignment.startswith("interrupted")
    interrupted_effect = assignment == "interrupted_effect"
    if assignment != "interrupted":
        mode["gate"].set()
    model.provider.max_concurrent_calls = 4
    user = User(email=f"synthetic-voice-{uuid4()}@example.test", hashed_password="unused")
    profile = LlmProfile(label="Synthetic voice", text_low_llm_id=model.id, text_standard_llm_id=model.id)
    db.add_all([user, profile])
    await db.flush()
    native_openai = assignment.startswith("native_openai")
    reconnect = assignment == "native_openai_reconnect"
    voice_selection = None
    if native_openai:
        model.provider.catalog_code = "openai-api"
        model.provider.api_key = get_encryption_service().encrypt("synthetic-openai-key")
        realtime_model = LLM(code=f"realtime-{uuid4()}", label="Synthetic realtime", provider=model.provider,
                             llm_name="gpt-realtime", service_capabilities=["realtime_conversation"])
        stt = LLM(code=f"stt-{uuid4()}", label="Synthetic STT", provider=model.provider,
                  llm_name="gpt-live-transcribe", service_capabilities=["transcription"])
        db.add_all([realtime_model, stt])
        await db.flush()
        voice_selection = f"realtime:{realtime_model.id}:voice%3Amarin"
        profile.transcription_llm_id = stt.id
    if interrupted_effect:
        assert await profile_service.set_current_profile_id(profile.id)
        monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 1)
    managed = assignment in {"codex", "deepseek_harness"}
    persisted_driver = "openai_messages" if managed else "internal" if assignment == "internal" else "claude_embedded"
    conversation_driver = "internal" if managed else persisted_driver
    agent = Agent(user_id=user.id, title_id=await db.scalar(select(Title.id).limit(1)),
                  code=f"synthetic-voice-{uuid4().hex}", first_name="Synthetic", last_name="Voice",
                  profile_id=profile.id, agent_driver=persisted_driver, voice=voice_selection)
    db.add(agent)
    await db.flush()
    if managed:
        db.add(AgentHarness(agent_id=agent.id, provider_code=assignment, lifecycle_status="ready",
            runtime_base_url="https://unused-managed-runtime.invalid", runtime_model="synthetic",
            runtime_token_encrypted=get_encryption_service().encrypt("synthetic-credential")))
    services = {row.code: row for row in await db.scalars(select(ServiceModel).where(
        ServiceModel.code.in_(("chat", "file_sharing", "memory")),
    ))}
    chat, files = services["chat"], services["file_sharing"]
    connection = Connection(service_id=chat.id, agent_id=agent.id, active=True)
    db.add_all([connection, Connection(service_id=files.id, agent_id=agent.id, active=True)])
    if interrupted_effect:
        db.add(Connection(service_id=services["memory"].id, agent_id=agent.id, active=True))
    caller = MessengerUser(service_id=chat.id, galaris_user_id=user.id, external_id=f"caller-{uuid4()}")
    assistant = MessengerUser(service_id=chat.id, agent_id=agent.id, external_id=f"agent:{agent.id}", is_ai=True)
    db.add_all([caller, assistant])
    await db.flush()
    room = Room(connection_id=connection.id, external_id=str(uuid4()), label="Synthetic Audio",
                kind="direct", conversation_type="audio")
    db.add(room)
    await db.flush()
    db.add_all([RoomUser(room_id=room.id, user_id=member.id) for member in (caller, assistant)])
    await db.commit()
    session = await conversation_service.start_session(
        agent_id=agent.id, connection_id=connection.id, transport_kind="test", room_id=room.external_id,
        language="fr", conversation_room_id=room.id,
    )

    prompt = "Synthetic voice first question"
    successor = "Synthetic clarification after barge-in"
    predicate = "preferred_report_format"

    def choose_tools(body):
        if conversation_driver == "internal" or any(item["role"] == "tool" for item in body["messages"]):
            return []
        if interrupted_effect and successor not in json.dumps(body["messages"]):
            return [("synthetic-voice-memory", "mcp__galaris__memory_remember",
                     {"fact": {"predicate": predicate, "value": "markdown"}})]
        return [("synthetic-voice-read", "mcp__galaris__file_schemes", {})]

    mode["tool_calls_for"] = choose_tools
    spoken = []
    entered = asyncio.Event()
    settle = asyncio.Event()
    acquisitions = []
    if interrupted_effect:
        actual_acquisition = acquisition_service.acquire_memory

        async def delay_acquisition(request, **kwargs):
            if request.fact is not None and request.fact.predicate == predicate:
                acquisitions.append(request.fact.value)
                entered.set()
                await settle.wait()
            return await actual_acquisition(request, **kwargs)

        monkeypatch.setattr(acquisition_service, "acquire_memory", delay_acquisition)

    async def synthesize(agent_id, text, _options):
        assert agent_id == agent.id
        spoken.append(text)
        return tts_service.GeneratedSpeech(b"synthetic", "synthetic", "synthetic")

    async def decode(_audio):
        yield AudioFrame(b"\x00\x00" * 960)

    async def batch_only(*_args, **_kwargs):
        return None

    monkeypatch.setattr(tts_service, "generate_for_agent", synthesize)
    monkeypatch.setattr(tts_service, "create_realtime_speech_stream_for_agent", batch_only)
    monkeypatch.setattr(voice_engine, "encoded_audio_frames", decode)
    transport = _Transport()
    voice = voice_engine.AgentVoiceEngine(
        transport=transport, handle=object(), agent_id=agent.id, session_id=session.id,
        connection_id=connection.id, room_id=room.external_id, conversation_room_id=room.id,
        caller_external_id=caller.external_id, language="fr",
    )
    utterance = SpeechUtterance(pcm=b"synthetic", duration_s=0.4, voiced_s=0.4, reason="silence")
    async def issue_voice(generation, index, text):
        await voice._respond(utterance, generation, index, transcript=text)

    if native_openai:
        native_session = AsyncMock(side_effect=AssertionError("the voice provider cannot run the conversation"))
        monkeypatch.setattr(OpenAIRealtime, "create_realtime_session", native_session)

        async def read_text(url, *, headers, json):
            assert url == f"{model.provider.base_url.rstrip('/')}/audio/speech"
            assert headers["Authorization"] == "Bearer synthetic-openai-key"
            assert json["voice"] == "marin" and json["model"] == "gpt-4o-mini-tts"
            spoken.append(json["input"])
            return b"synthetic"

        from bridge.openai.tests.test_realtime import _Socket

        socket = _Socket()
        socket.received.extend(json.dumps(event) for event in (
            {"type": "input_audio_buffer.committed", "item_id": "user-input"},
            {"type": "conversation.item.input_audio_transcription.delta", "item_id": "user-input", "delta": "Synthetic voice"},
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "user-input", "transcript": prompt},
        ))
        sockets = [socket]
        if reconnect:
            failed_socket = _Socket()
            failed_socket.received.extend(json.dumps(event) for event in (
                {"type": "input_audio_buffer.committed", "item_id": "failed-input"},
                {"type": "conversation.item.input_audio_transcription.failed", "item_id": "failed-input",
                 "error": {"code": "synthetic_asr_failure"}},
            ))
            sockets.insert(0, failed_socket)
        next_socket = iter(sockets)
        fallback = asyncio.Event()

        async def live_only_fallback(_utterance):
            fallback.set()
            raise transcription_service.TranscriptionFailed("Synthetic live-only model has no batch endpoint")

        if reconnect:
            monkeypatch.setattr(voice, "_transcribe", live_only_fallback)

        async def connect_transcription(uri, **kwargs):
            assert uri == "wss://provider.test/v1/realtime?intent=transcription"
            assert kwargs["additional_headers"] == {"Authorization": "Bearer synthetic-openai-key"}
            return next(next_socket)

        async def detect(_frames, *, on_speech_start, on_classified_audio):
            greeting = voice._response_task
            assert greeting is not None
            await greeting
            pcm = b"\x00\x40" * 4_800
            utterance = SpeechUtterance(pcm=pcm, duration_s=0.1, voiced_s=0.1, reason="silence")
            for attempt in range(len(sockets)):
                await on_speech_start()
                await on_classified_audio(pcm, True)
                yield utterance
                if attempt == 0 and reconnect:
                    await fallback.wait()
            while voice._response_task is greeting:
                await asyncio.sleep(0.01)
            await voice._response_task

        monkeypatch.setattr(tts_service, "_post_mp3", read_text)
        monkeypatch.setattr("bridge.openai.transcription.connect", connect_transcription)
        monkeypatch.setattr(voice_engine, "detect_speech_turns", detect)

    def origin_for(round_, attempt):
        return EmbeddedRoundInference(
            round_id=round_.id, run_id=round_.id, attempt_id=attempt.id, agent_id=agent.id,
            driver_code="claude_embedded", model_id=model.id, model_code=model.code, audio=True,
            request_limit=attempt.inference_admission["request_limit"],
        )

    async with _gateway(monkeypatch), asyncio.timeout(40):
        if interrupted:
            first = asyncio.create_task(issue_voice(0, 1, prompt))
            voice._response_task = first
            try:
                if interrupted_effect:
                    await entered.wait()
                else:
                    while not requests:
                        await asyncio.sleep(0.01)
                active = await db.scalar(select(ConversationRound).where(ConversationRound.voice_session_id == session.id))
                attempt = await db.scalar(select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id == active.id))
                origin = origin_for(active, attempt)
                async with AsyncClient() as client:
                    response = await client.get(f"{claude_driver.CLAUDE_GATEWAY}/v1/models", headers={"x-api-key": origin.credential()})
                    assert response.status_code == 200
                    forged = origin.model_copy(update={"audio": False})
                    response = await client.get(f"{claude_driver.CLAUDE_GATEWAY}/v1/models",
                                                headers={"x-api-key": forged.credential()})
                    assert response.status_code == 403
                    forged = origin.model_copy(update={"request_limit": origin.request_limit + 1})
                    response = await client.get(f"{claude_driver.CLAUDE_GATEWAY}/v1/models",
                                                headers={"x-api-key": forged.credential()})
                    assert response.status_code == 403
                await voice._on_speech_start()
                if interrupted_effect:
                    confirming = asyncio.create_task(voice._confirm_interruption())
                    try:
                        await asyncio.sleep(0.15)
                        assert not first.done() and not confirming.done()
                    finally:
                        settle.set()
                        await confirming
                else:
                    await voice._confirm_interruption()
                with pytest.raises(asyncio.CancelledError):
                    await first
            finally:
                mode["gate"].set()
                settle.set()
                if not first.done():
                    first.cancel()
                    await asyncio.gather(first, return_exceptions=True)
            await voice._resume_playback(voice._generation)
            if interrupted_effect:
                monkeypatch.setattr(runtime_settings, "TASK_AGENT_MAX_TOOL_CALLS", 4)
            await issue_voice(voice._response_generation, 2, successor)
        elif native_openai:
            assert await agent_voice_call_available(agent.id)
            await voice.run()
            native_session.assert_not_awaited()
            for opened_socket in sockets:
                assert opened_socket.closed
                assert [item["type"] for item in opened_socket.sent] == [
                    "session.update", "input_audio_buffer.append", "input_audio_buffer.commit",
                ]
                assert opened_socket.sent[0]["session"]["type"] == "transcription"
        else:
            await issue_voice(0, 1, prompt)

        rounds = list(await db.scalars(select(ConversationRound).where(ConversationRound.voice_session_id == session.id)
                                      .order_by(ConversationRound.sequence).execution_options(populate_existing=True)))
        final = rounds[-1]
        assert final.driver_code == conversation_driver
        assert final.status == "COMPLETED" and final.lease_token is None, final.last_error
        assert final.execution_result["result"] == "Bonjour !"
        assert len(spoken) == (2 if native_openai else 1) and "Bonjour" in spoken[-1]
        outputs = list(await db.scalars(select(Message.text).join(
            ConversationRoundMessage, ConversationRoundMessage.message_id == Message.id,
        ).where(ConversationRoundMessage.round_id == final.id, ConversationRoundMessage.role == "output")))
        assert outputs == ["Bonjour !"]
        assert list(tmp_path.iterdir()) == []
        calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id).order_by(LLMCall.started_at)))
        assert len(calls) == len(requests)
        if not interrupted_effect:
            assert len(calls) == (1 if conversation_driver == "internal" else 3 if interrupted else 2)
        assert all(call.purpose == "conversation.audio" and call.task_id is None and call.task_attempt_id is None
                   and call.agent_run_id == call.conversation_round_id for call in calls)
        if conversation_driver == "claude_embedded":
            assert all(call.requester_user_id == user.id for call in calls)
            attempts = {item.round_id: item for item in await db.scalars(
                select(ConversationRoundAttempt).where(ConversationRoundAttempt.round_id.in_([item.id for item in rounds]))
                .execution_options(populate_existing=True),
            )}
            assert all(call.correlation_ref == f"round:{call.conversation_round_id}:attempt:{attempts[call.conversation_round_id].id}"
                       for call in calls)
            assert attempts[final.id].status == "SUCCESS" and attempts[final.id].inference_admission["model_id"] == model.id
            assert any(item["role"] == "tool" and "schemes" in str(item["content"]) for item in requests[-1]["messages"])
            async with AsyncClient() as client:
                response = await client.get(f"{claude_driver.CLAUDE_GATEWAY}/v1/models",
                    headers={"x-api-key": origin_for(final, attempts[final.id]).credential()})
                assert response.status_code == 403
            if interrupted:
                assert rounds[0].status == "INTERRUPTED"
                assert rounds[0].resolved_by_round_id == (None if interrupted_effect else final.id)
                assert attempts[rounds[0].id].status == "INTERRUPTED"
                assert len({call.correlation_ref for call in calls}) == 2
                assert all((successor in json.dumps(call.request_messages)) is (call.conversation_round_id == final.id)
                           for call in calls)
                if interrupted_effect:
                    original = attempts[rounds[0].id].inference_admission
                    following = attempts[final.id].inference_admission
                    assert (original["tool_call_limit"], original["tool_calls_used"]) == (1, 1)
                    assert (following["tool_call_limit"], following["tool_calls_used"]) == (4, 1)
        if interrupted_effect:
            assert acquisitions == ["markdown"]
            memories = list(await db.scalars(select(MemoryItem).where(
                MemoryItem.owner_agent_id == agent.id, MemoryItem.metadata_["atomic_fact"]["predicate"].as_string() == predicate,
            )))
            assert len(memories) == 1
            assert final.effective_objective == successor
            assert rounds[0].encrypted_checkpoint
            effects = read_checkpoint_payload(rounds[0].encrypted_checkpoint)["data"]["effects"]
            assert [effect["status"] for effect in effects] == ["completed"]
        persisted = await db.get(Agent, agent.id, populate_existing=True)
        assert persisted.agent_driver == persisted_driver and persisted.voice == voice_selection
        await conversation_service.finish_session(session.id, VoiceConversationStatus.COMPLETED)
