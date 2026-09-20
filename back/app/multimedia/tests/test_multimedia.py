from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.llm import MediaArtifact, MediaRequest, MediaResult, available_media_functions
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM, LLMProvider
from app.multimedia.engine import MultimediaEngine
from app.multimedia.models import MediaOutputReceipt
from app.process.interface import engine_checkpoint, ensure_integrated_definition
from app.process.models import ProcessDefinition, ProcessRun
from app.process.schemas import EngineRunReference, ProcessStartPayload
from app.tools import mandatory_tools, mcp_loader
from app.tools.models import Tool


@pytest_asyncio.fixture
async def media_agent(db: AsyncSession):
    suffix = uuid4().hex[:8]
    title = Title(label=f"Media {suffix}", gender="X")
    profile = LlmProfile(label=f"Media {suffix}")
    provider = LLMProvider(name=f"Media {suffix}", catalog_code="elevenlabs", provider_type="elevenlabs",
                           base_url="https://api.elevenlabs.io/v1", api_key="test-key", is_active=True, configuration={})
    db.add_all([title, profile, provider])
    await db.flush()
    agent = Agent(title_id=title.id, code=f"media-{suffix}", first_name="Media", last_name="Test",
                  agent_driver="internal", profile_id=profile.id)
    model = LLM(llm_provider_id=provider.id, code=f"music-{suffix}", llm_name="music_v1", label="Music",
                resource_type="model", primary_capability="music_generation", service_capabilities=["music_generation"], pricing={})
    db.add_all([agent, model])
    await db.flush()
    profile.music_generation_llm_id = model.id
    await db.commit()
    await mandatory_tools.sync_integrated_tool_connections(agent.id)
    await db.commit()
    connection = (await db.scalars(select(Connection).join(Tool).where(
        Connection.agent_id == agent.id, Tool.code == "multimedia"))).one()
    return SimpleNamespace(agent=agent, profile=profile, provider=provider, model=model, connection=connection)


@pytest.mark.asyncio
async def test_live_mcp_catalog_and_execution_follow_profile_and_connection(db, media_agent, monkeypatch):
    from app.multimedia import engine as module

    execute = AsyncMock(side_effect=AssertionError("An unavailable tool reached execution"))
    monkeypatch.setattr(module.MultimediaEngine, "start_run", execute)
    item = media_agent
    # Exercise an explicit operator restriction independently of installation defaults.
    item.connection.active = False
    await db.commit()
    assert await available_media_functions(item.agent.id) == {"music_generate"}
    server = await mcp_loader.build_agent_mcp(item.agent.id, allowed_tool_names={"music_generate"})
    async with Client(server) as client:
        assert not await client.list_tools()
        item.connection.active = True
        await db.commit()
        assert {tool.name for tool in await client.list_tools()} == {"music_generate"}
        item.profile.music_generation_llm_id = None
        await db.commit()
        assert not await client.list_tools()
        with pytest.raises(ToolError):
            await client.call_tool("music_generate", {"prompt": "Piano", "destination": "console:///tmp/"})
        execute.assert_not_awaited()
        assert await db.scalar(
            select(ProcessRun.id).where(ProcessRun.launcher_agent_id == item.agent.id)
        ) is None
    item.connection.active = True
    await db.commit()
    await mandatory_tools.sync_integrated_tool_connections(item.agent.id)
    await db.refresh(item.connection)
    assert item.connection.active is True


@pytest.mark.asyncio
async def test_resource_capability_and_provider_are_required(db, media_agent):
    item = media_agent
    item.profile.audio_llm_id = item.model.id
    await db.commit()
    assert "audio_read" not in await available_media_functions(item.agent.id)
    item.provider.is_active = False
    await db.commit()
    assert not await available_media_functions(item.agent.id)


@pytest.mark.asyncio
async def test_new_invocations_are_distinct_but_explicit_retry_is_deduplicated(db, media_agent, monkeypatch):
    from app.multimedia import engine as module
    from app.multimedia.mcp import music_generate
    item = media_agent
    item.connection.active = True
    await db.commit()
    monkeypatch.setattr(module, "validate_destination", AsyncMock(return_value="console:///tmp/"))
    ctx = mcp_loader.McpToolContext(agent_id=item.agent.id, runtime="internal")
    first = await music_generate(ctx, "Piano", "console:///tmp/", invocation_key="one-invocation")
    retry = await music_generate(ctx, "Piano", "console:///tmp/", invocation_key="one-invocation")
    separate = await music_generate(ctx, "Piano", "console:///tmp/")
    assert retry["run_id"] == first["run_id"]
    assert retry["deduplicated"] is True
    assert separate["run_id"] != first["run_id"]
    item.profile.music_generation_llm_id = None
    await db.commit()
    with pytest.raises(PermissionError):
        await music_generate(ctx, "Piano", "console:///tmp/")


async def _run(db, item):
    workflow = await ensure_integrated_definition(item.agent.id, "multimedia", "music_generate")
    definition = (await db.scalars(select(ProcessDefinition).where(ProcessDefinition.engine_process_id == workflow))).one()
    run = ProcessRun(process_id=definition.id, launcher_agent_id=item.agent.id, engine_code="multimedia",
                     correlation_id=str(uuid4()), callback_token="token", status="running",
                     input={"request": MediaRequest(operation="music_generate", model="music_v1", prompt="Piano").model_dump(),
                            "runtime": "internal", "destination": "console:///tmp/"})
    db.add(run)
    await db.commit()
    return run, EngineRunReference(id=run.id, correlation_id=run.correlation_id, callback_token="token")


@pytest.mark.asyncio
async def test_durable_provider_success_survives_late_error_and_delivery_budget(db, media_agent, monkeypatch):
    from app.multimedia import engine as module
    from core.util import buffered_io_budget
    run, reference = await _run(db, media_agent)
    engine = MultimediaEngine()
    await engine._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),)))
    await engine._receive(run.id, MediaResult("error", error="stale poll"))

    async def upload(*args, **kwargs):
        # Exercise nested adapter admission inside the real engine delivery.
        async with buffered_io_budget.reserve(300_000_000, owner="messenger:test", timeout=0.01):
            return SimpleNamespace(uri="messenger://room/output")

    monkeypatch.setattr(module, "resource_create", upload)
    assert (await engine.get_run(reference)).status == "success"
    assert buffered_io_budget.used == 0


@pytest.mark.asyncio
async def test_100mb_delivery_traverses_resource_messenger_and_whatsapp_budgets(db, media_agent, monkeypatch):
    import asyncio
    from app.file_share import resource_service
    from app.file_share.messenger_transport import MessengerFileTransport
    from app.messenger.facade import MessengerFacade
    from app.messenger.models import MessengerUser, Room, RoomUser
    from bridge.whatsapp.messenger import WhatsAppMessenger
    from bridge.whatsapp.schemas import WhatsAppConnectionConfig
    from core.user.models import User
    from core.util import buffered_io_budget

    recipient = User(
        email=f"media-recipient-{uuid4().hex}@example.test",
        hashed_password="unused",
        is_active=True,
    )
    db.add(recipient)
    await db.flush()
    media_agent.agent.user_id = recipient.id
    media_agent.connection.active = True
    room = Room(
        connection_id=media_agent.connection.id,
        external_id="15551234567",
        label="Media recipient",
        kind="direct",
        conversation_type="text",
    )
    identity = MessengerUser(
        tool_id=media_agent.connection.tool_id,
        external_id="15551234567",
        galaris_user_id=recipient.id,
        display_name="Media recipient",
    )
    db.add_all([room, identity])
    await db.flush()
    db.add(RoomUser(room_id=room.id, user_id=identity.id))
    await db.commit()
    run, reference = await _run(db, media_agent)
    run.input = {**run.input, "destination": "whatsapp://15551234567/"}
    await db.commit()
    sent_sizes = []
    async def upload(content, *_args):
        sent_sizes.append(len(content))
        assert buffered_io_budget.used <= buffered_io_budget.capacity
        return "media-100mb"
    client = SimpleNamespace(upload_media=upload, send_media=AsyncMock(return_value={"messages": [{"id": "message-100mb"}]}))
    bridge = WhatsAppMessenger(client, WhatsAppConnectionConfig(access_token="test", phone_number_id="bot",
        allowed_phone_numbers="15551234567"), tool_id=media_agent.connection.tool_id, connection_id=media_agent.connection.id)
    monkeypatch.setattr(bridge, "_inside_service_window", AsyncMock(return_value=True))
    transport = MessengerFileTransport(MessengerFacade(bridge, media_agent.connection.id))
    monkeypatch.setattr(resource_service, "_connected_transport", AsyncMock(return_value=(transport, "messenger", "", "")))
    engine = MultimediaEngine()
    await engine._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("large-track", "audio/mpeg", content=b"ID3" + b"a" * 99_999_997),)))
    result = await asyncio.wait_for(engine.get_run(reference), 10)
    assert result.status == "success" and sent_sizes == [100_000_000]
    assert buffered_io_budget.used == 0


@pytest.mark.asyncio
async def test_checkpoint_claim_is_single_use_and_terminal_is_immutable(db, media_agent):
    run, _ = await _run(db, media_agent)
    assert (await engine_checkpoint(run.id, "multimedia", claim="submission"))["claimed"] is True
    assert (await engine_checkpoint(run.id, "multimedia", claim="submission"))["claimed"] is False
    run.status = "success"
    await db.commit()
    data = await engine_checkpoint(run.id, "multimedia", {"submission": "changed"}, claim="another")
    assert data["metadata"]["submission"] == "started"
    assert data["claimed"] is False


@pytest.mark.asyncio
async def test_lost_submission_response_is_not_submitted_twice(db, media_agent, monkeypatch):
    from app.multimedia import engine as module
    run, reference = await _run(db, media_agent)
    provider = SimpleNamespace(validate=lambda _: None, submit=AsyncMock(side_effect=TimeoutError))
    selected = SimpleNamespace(provider=provider, connection=object())
    engine = MultimediaEngine()
    monkeypatch.setattr(engine, "_selected", AsyncMock(return_value=selected))
    monkeypatch.setattr(module, "authorize", AsyncMock())
    monkeypatch.setattr(module, "start_media_call", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(module, "finish_media_call", AsyncMock())
    await engine.start_run("workflow", reference, ProcessStartPayload())
    await engine.start_run("workflow", reference, ProcessStartPayload())
    assert provider.submit.await_count == 1
    assert (await engine.get_run(reference)).status == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rejected", "error", "success", "waiting"])
async def test_provider_submission_records_outcome_and_never_rebills_on_replay(db, media_agent, monkeypatch, outcome):
    from app.llm import resolve_media_resource
    from app.llm.media_contracts import MediaRequestRejected
    from app.llm.models import LLMCall

    media_agent.connection.active = True
    await db.commit()
    selected = await resolve_media_resource(media_agent.agent.id, "music_generate")
    run, reference = await _run(db, media_agent)
    run.input = {**run.input, "llm_id": selected.llm_id, "provider_id": selected.connection.id,
        "provider_code": selected.connection.catalog_code, "provider_base_url": selected.connection.base_url}
    await db.commit()
    result = MediaResult(outcome if outcome != "rejected" else "error", external_id="remote-generation",
        error="Provider refused this request" if outcome in {"error", "rejected"} else None,
        artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),) if outcome == "success" else (),
        cost=0.25 if outcome == "success" else None)
    submit = AsyncMock(side_effect=MediaRequestRejected(result.error)) if outcome == "rejected" else AsyncMock(return_value=result)
    monkeypatch.setattr(type(selected.provider), "submit", submit)
    engine = MultimediaEngine()
    for _ in range(2):
        assert (await engine.start_run("workflow", reference, ProcessStartPayload())).accepted
    submit.assert_awaited_once()
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.process_run_id == run.id)))
    assert len(calls) == 1 and calls[0].llm_id == selected.llm_id
    assert calls[0].status == ("completed" if outcome == "success" else "running" if outcome == "waiting" else "error")
    data = await engine_checkpoint(run.id, "multimedia")
    assert data["metadata"]["provider_state"] == ("error" if outcome == "rejected" else outcome)
    if outcome == "success":
        receipt = (await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run.id))).one()
        assert receipt.content == b"ID3audio" and data["metadata"]["cost"] == 0.25
    if outcome in {"error", "rejected"}:
        assert (await engine.get_run(reference)).error.message == "Provider refused this request"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["success", "error", "cancelled"])
async def test_late_provider_result_cannot_change_terminal_run_or_create_media(db, media_agent, terminal):
    run, _ = await _run(db, media_agent)
    run.status = terminal
    run.output = {"receipt": "original"}
    await db.commit()
    await MultimediaEngine()._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("late", "audio/mpeg", content=b"ID3late"),)))
    await db.refresh(run)
    assert run.status == terminal and run.output == {"receipt": "original"}
    assert await db.scalar(select(MediaOutputReceipt.id).where(MediaOutputReceipt.run_id == run.id)) is None


@pytest.mark.asyncio
async def test_success_requires_canonical_files_and_delivery_is_not_repeated(db, media_agent, monkeypatch):
    from app.multimedia import engine as module
    run, reference = await _run(db, media_agent)
    engine = MultimediaEngine()
    result = MediaResult("success", artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),))
    await engine._receive(run.id, result)
    create = AsyncMock(return_value=SimpleNamespace(uri="console:///tmp/song.mp3"))
    monkeypatch.setattr(module, "resource_create", create)
    first = await engine.get_run(reference)
    second = await engine.get_run(reference)
    assert first.status == second.status == "success"
    assert first.output["files"][0]["uri"] == "console:///tmp/song.mp3"
    assert create.await_count == 1
    receipt = (await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run.id))).one()
    assert receipt.content is None


@pytest.mark.asyncio
async def test_interrupted_file_creation_never_repeats_blindly(db, media_agent, monkeypatch):
    from app.multimedia import engine as module
    run, reference = await _run(db, media_agent)
    engine = MultimediaEngine()
    await engine._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),)))
    create = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr(module, "resource_create", create)
    with pytest.raises(TimeoutError):
        await engine.get_run(reference)
    assert (await engine.get_run(reference)).status == "unknown"
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_provider_error_page_cannot_become_a_successful_audio_file(db, media_agent):
    run, _ = await _run(db, media_agent)
    with pytest.raises(ValueError, match="container"):
        await MultimediaEngine()._receive(run.id, MediaResult("success", artifacts=(
            MediaArtifact("track", "audio/mpeg", content=b"<html>upstream failure</html>"),
        )))


@pytest.mark.asyncio
async def test_analysis_probes_real_audio_and_rejects_it_as_video(monkeypatch):
    import wave
    from app.multimedia import service
    provider = SimpleNamespace(validate=lambda _: None, analyze=AsyncMock(return_value=MediaResult("success", text="Quiet")))
    selected = SimpleNamespace(model="gemini", connection=object(), provider=provider)
    monkeypatch.setattr(service, "authorize", AsyncMock())
    monkeypatch.setattr(service, "resolve_media_resource", AsyncMock(return_value=selected))
    monkeypatch.setattr(service, "start_media_call", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(service, "finish_media_call", AsyncMock())

    async def materialize(ctx, uri, path, *, max_bytes):
        assert uri == "source://sound.wav"
        assert max_bytes == 32_000_000
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 16000)
        return SimpleNamespace(media_type="audio/wav")

    monkeypatch.setattr(service, "materialize_resource", materialize)
    ctx = mcp_loader.McpToolContext(agent_id=1, runtime="internal")
    result = await service.analyze(ctx, "audio_read", "source://sound.wav", "Describe")
    assert result["analysis"] == "Quiet"
    with pytest.raises(ValueError, match="expected track"):
        await service.analyze(ctx, "video_read", "source://sound.wav", "Describe")
    assert provider.analyze.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["attach", "retry_absent"])
async def test_delivery_repair_requires_expired_lease_and_preserves_generation(db, media_agent, monkeypatch, decision):
    from datetime import datetime, timedelta, timezone
    from app.multimedia import engine as module, delivery
    from app.multimedia.models import MediaDeliveryResolution
    run, reference = await _run(db, media_agent)
    engine = MultimediaEngine()
    await engine._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),)))
    create = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr(module, "resource_create", create)
    with pytest.raises(TimeoutError):
        await engine.get_run(reference)
    receipt = (await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run.id))).one()
    request = delivery.DeliveryRepair(attempt_number=1, decision=decision,
        evidence="Destination checked by the operator", uri="console:///tmp/recovered.mp3" if decision == "attach" else None)
    with pytest.raises(ValueError, match="lease"):
        await delivery.repair_delivery(run.id, receipt.id, request, actor_user_id=None)
    receipt.delivery_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    async def materialize(_ctx, _uri, path, **_kwargs):
        path.write_bytes(b"ID3audio")
    monkeypatch.setattr(delivery, "materialize_resource", materialize)
    await delivery.repair_delivery(run.id, receipt.id, request, actor_user_id=None)
    await delivery.repair_delivery(run.id, receipt.id, request, actor_user_id=None)
    create.side_effect = None
    create.return_value = SimpleNamespace(uri="console:///tmp/recovered.mp3")
    result = await engine.get_run(reference)
    assert result.status == "success"
    assert create.await_count == (1 if decision == "attach" else 2)
    assert len(list(await db.scalars(select(MediaDeliveryResolution).where(MediaDeliveryResolution.receipt_id == receipt.id)))) == 1
    assert receipt.content is None


@pytest.mark.asyncio
async def test_unknown_checkpoint_version_cannot_submit(db, media_agent, monkeypatch):
    run, reference = await _run(db, media_agent)
    run.engine_metadata = {"multimedia_version": 2}
    await db.commit()
    engine = MultimediaEngine()
    selected = AsyncMock()
    monkeypatch.setattr(engine, "_selected", selected)
    with pytest.raises(ValueError):
        await engine.start_run("workflow", reference, ProcessStartPayload())
    selected.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["no_outputs", "too_many", "empty", "wrong_container"])
async def test_invalid_provider_outputs_never_produce_delivered_success(db, media_agent, fault):
    run, reference = await _run(db, media_agent)
    artifacts = {
        "no_outputs": (),
        "too_many": tuple(MediaArtifact(str(index), "audio/mpeg", content=b"ID3audio") for index in range(5)),
        "empty": (MediaArtifact("track", "audio/mpeg", content=b""),),
        "wrong_container": (MediaArtifact("track", "video/mp4", content=b"ID3audio"),),
    }[fault]
    engine = MultimediaEngine()
    with pytest.raises(ValueError):
        await engine._receive(run.id, MediaResult("success", artifacts=artifacts))
    assert await db.scalar(select(MediaOutputReceipt.id).where(MediaOutputReceipt.run_id == run.id)) is None
    checkpoint = await engine_checkpoint(run.id, "multimedia")
    assert checkpoint["metadata"].get("provider_state") != "success"
    assert (await engine.get_run(reference)).status == "unknown"


@pytest.mark.asyncio
async def test_remote_output_recovery_resumes_downloads_without_duplicating_saved_receipts(db, media_agent, monkeypatch):
    from app.multimedia import provider_results, engine as module
    run, reference = await _run(db, media_agent)
    calls = []
    failed = True
    async def download(url, *, max_bytes):
        calls.append(url)
        assert max_bytes == 100_000_000
        if url.endswith("two") and failed:
            raise TimeoutError("download interrupted")
        return SimpleNamespace(content=b"ID3audio")
    monkeypatch.setattr(provider_results, "read_public_https_bytes", download)
    result = MediaResult("success", external_id="generation", cost=0.25, artifacts=(
        MediaArtifact("one", "audio/mpeg", url="https://media.test/one"),
        MediaArtifact("two", "audio/mpeg", url="https://media.test/two"),
    ))
    engine = MultimediaEngine()
    with pytest.raises(TimeoutError):
        await engine._receive(run.id, result)
    assert len(list(await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run.id)))) == 1
    failed = False
    await engine._receive(run.id, result)
    await engine._receive(run.id, result)
    assert calls == ["https://media.test/one", "https://media.test/two", "https://media.test/two"]
    create = AsyncMock(side_effect=[SimpleNamespace(uri="console://one.mp3"), SimpleNamespace(uri="console://two.mp3")])
    monkeypatch.setattr(module, "resource_create", create)
    delivered = await engine.get_run(reference)
    assert delivered.status == "success"
    assert delivered.output["cost"] == 0.25 and delivered.output["cost_quality"] == "exact"
    assert [item["external_id"] for item in delivered.output["files"]] == ["one", "two"]
    assert create.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["running", "waiting", "error"])
async def test_provider_poll_updates_durable_observation_without_new_submission(db, media_agent, monkeypatch, state):
    from app.llm import resolve_media_resource
    selected = await resolve_media_resource(media_agent.agent.id, "music_generate")
    run, reference = await _run(db, media_agent)
    run.input = {**run.input, "llm_id": selected.llm_id, "provider_id": selected.connection.id,
                 "provider_code": selected.connection.catalog_code, "provider_base_url": selected.connection.base_url}
    await db.commit()
    await engine_checkpoint(run.id, "multimedia", {"external_id": "remote", "provider_state": "running"})
    poll = AsyncMock(return_value=MediaResult(state, external_id="remote", error="remote failed" if state == "error" else None))
    monkeypatch.setattr(type(selected.provider), "poll", poll)
    snapshot = await MultimediaEngine().get_run(reference)
    assert snapshot.status == state
    assert (await engine_checkpoint(run.id, "multimedia"))["metadata"]["provider_state"] == state
    poll.assert_awaited_once()
    if state == "error":
        assert snapshot.error.message == "remote failed"
        again = await MultimediaEngine().get_run(reference)
        assert again.status == "error"
        poll.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["provider_id", "provider_code", "provider_base_url", "model"])
async def test_admitted_media_resource_cannot_silently_switch_provider_or_model(db, media_agent, changed):
    from app.llm import resolve_media_resource
    selected = await resolve_media_resource(media_agent.agent.id, "music_generate")
    run, reference = await _run(db, media_agent)
    frozen = {**run.input, "llm_id": selected.llm_id, "provider_id": selected.connection.id,
              "provider_code": selected.connection.catalog_code, "provider_base_url": selected.connection.base_url}
    if changed == "model":
        frozen["request"] = {**frozen["request"], "model": "replacement"}
    else:
        frozen[changed] = "changed"
    run.input = frozen
    await db.commit()
    await engine_checkpoint(run.id, "multimedia", {"external_id": "remote", "provider_state": "running"})
    with pytest.raises(ValueError, match="substitution"):
        await MultimediaEngine().get_run(reference)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["terminal", "missing", "attempt", "not_started", "delivered", "content", "mismatch", "absence_uri"])
async def test_delivery_repair_refuses_unproven_or_wrong_attempt_without_changing_receipt(db, media_agent, monkeypatch, fault):
    from app.multimedia import delivery
    from app.multimedia.models import MediaDeliveryResolution
    run, _ = await _run(db, media_agent)
    await MultimediaEngine()._receive(run.id, MediaResult("success", artifacts=(MediaArtifact("track", "audio/mpeg", content=b"ID3audio"),)))
    receipt = (await db.scalars(select(MediaOutputReceipt).where(MediaOutputReceipt.run_id == run.id))).one()
    receipt.delivery_started, receipt.delivery_attempts = True, 1
    if fault == "terminal":
        run.status = "success"
    elif fault == "not_started":
        receipt.delivery_started = False
    elif fault == "delivered":
        receipt.uri = "console://already.mp3"
    elif fault == "content":
        receipt.content = None
    await db.commit()
    original = (receipt.uri, receipt.content, receipt.delivery_started, receipt.delivery_attempts)
    async def different(_ctx, _uri, path, **kwargs):
        path.write_bytes(b"ID3different")
    monkeypatch.setattr(delivery, "materialize_resource", different)
    request = delivery.DeliveryRepair(attempt_number=2 if fault == "attempt" else 1,
        decision="attach" if fault == "mismatch" else "retry_absent", evidence="Checked destination manually",
        uri="console://candidate.mp3" if fault in {"mismatch", "absence_uri"} else None)
    with pytest.raises(LookupError if fault == "missing" else ValueError):
        await delivery.repair_delivery(run.id, uuid4() if fault == "missing" else receipt.id, request, actor_user_id=None)
    await db.refresh(receipt)
    assert (receipt.uri, receipt.content, receipt.delivery_started, receipt.delivery_attempts) == original
    assert list(await db.scalars(select(MediaDeliveryResolution))) == []


@pytest.mark.asyncio
async def test_media_cancellation_never_claims_provider_stopped(db, media_agent):
    from app.process import process_service, ProcessEngineError
    run, reference = await _run(db, media_agent)
    with pytest.raises(ProcessEngineError, match="cancel"):
        await process_service.cancel_run(run.id)
    await db.refresh(run)
    assert run.status == "running"
    with pytest.raises(ProcessEngineError, match="cancel"):
        await MultimediaEngine().cancel_run(reference)
