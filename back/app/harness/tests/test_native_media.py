"""Observable model inputs, with only the resource/provider boundaries replaced."""

from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from app.agent.contracts import TaskMessage, TaskMessageAttachment
from app.file_share import MaterializedResource, ResourceDescriptor
from app.harness import runtime
from app.llm import LLM
from app.llm.provider_models import LLMProvider


def attached_message(mime: str = "image/png", *, text: str = "Inspect this") -> TaskMessage:
    return TaskMessage(
        text=text,
        attachments=[TaskMessageAttachment(
            id=uuid4(), uri=f"chat://synthetic-room/{uuid4()}",
            name="sample", mime=mime, size=4,
        )],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mime", ["image/png", "audio/ogg", "video/mp4", "application/pdf"])
@pytest.mark.parametrize("source", ["uploaded", "internal"])
@pytest.mark.parametrize("native", [True, False])
async def test_current_and_previous_media_reach_model_without_analysis_tool(monkeypatch, mime, source, native):
    from app import file_share
    from app.llm import transcription_service
    from app.llm import facade as llm_facade
    from app.image import image_service
    from app.llm import llm_service

    current, previous = attached_message(mime), attached_message(mime, text="Earlier media")
    uris = [message.attachments[0].uri for message in (current, previous)]
    if source == "internal":
        uris = ["console://synthetic-current", "console://synthetic-earlier"]
        current, previous = [TaskMessage.model_validate({"text": message.text, "resource_uris": [uri]})
                             for message, uri in zip((current, previous), uris, strict=True)]
    reads = []
    paths = []
    analyses = []

    async def info(ctx, uri):
        assert ctx.agent_id == 7
        return ResourceDescriptor(uri=uri, name="sample", media_type=mime, size=4)

    async def materialize(ctx, uri, path: Path, **kwargs):
        reads.append(uri)
        paths.append(path)
        path.write_bytes(b"test")
        return MaterializedResource(uri, "sample", mime, 4)

    async def analyze(*args, **kwargs):
        analyses.append(mime)
        return "Synthetic media transcript"

    async def vision_completion(body, selected_model, kind, language, **kwargs):
        assert selected_model == "synthetic-vision-model" and kind == "vision"
        assert body["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,dGVzdA=="
        assert kwargs["agent_id"] == 7
        analyses.append(mime)
        return {"choices": [{"message": {"content": "Synthetic media transcript"}}]}

    @asynccontextmanager
    async def prepared(ctx, uri):
        reads.append(uri)
        analyses.append(mime)
        yield SimpleNamespace(text=lambda: "Synthetic media transcript", pages=[]), Path("unused-synthetic-preparation")

    model = TestModel(call_tools=[], custom_output_text="I can inspect both images")
    captured = []
    original = model.request_stream

    def capture(messages, *args, **kwargs):
        captured.append(list(messages))
        return original(messages, *args, **kwargs)

    monkeypatch.setattr(model, "request_stream", capture)
    async def count(*args, **kwargs):
        return RequestUsage(input_tokens=1)
    monkeypatch.setattr(model, "count_tokens", count)
    async def build(*args, **kwargs):
        return model

    monkeypatch.setattr(file_share, "resource_info", info)
    monkeypatch.setattr(file_share, "materialize_resource", materialize)
    monkeypatch.setattr(file_share, "prepared_resource", prepared)
    monkeypatch.setattr(llm_service, "get_vision_llm", AsyncMock(return_value=LLM(code="synthetic-vision", llm_name="synthetic-vision-model")))
    monkeypatch.setattr(image_service, "_proxy_completion_json", vision_completion)
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", analyze)
    monkeypatch.setattr(llm_facade, "analyze_input_video", analyze)
    monkeypatch.setattr(runtime, "build_model_for_llm", build)
    llm = LLM(input_image=native, input_audio=native, input_video=native, input_file=native,
              provider=LLMProvider(catalog_code="openrouter", provider_type="openai_compatible",
                                   base_url="https://openrouter.ai/api/v1"))
    agent = runtime.Agent(llm, agent_id=7)
    await agent.init()
    output = [item async for item in agent.run(
        current.text, message_history=[previous], current_messages=[current],
    )]
    assert output and not agent.error
    user_parts = [part for message in captured[0] if isinstance(message, ModelRequest)
                  for part in message.parts if isinstance(part, UserPromptPart)]
    assert len(user_parts) == 2
    for part, uri in zip(user_parts, reversed(uris), strict=True):
        assert not isinstance(part.content, str)
        binary = [item for item in part.content if isinstance(item, BinaryContent)]
        if native:
            assert len(binary) == 1 and binary[0].data == b"test"
        else:
            assert not binary
            assert "Synthetic media transcript" in str(part.content)
        assert uri in str(part.content)
    assert reads == uris
    assert all(not path.exists() for path in paths)
    assert analyses == ([] if native else [mime, mime])

    # A durable resume must retain the media already supplied, without downloading or
    # appending it again when the triggering message is still present in the Task.
    from app.harness.checkpoint import HarnessRunCheckpoint
    from .test_checkpoint import _request

    save = AsyncMock()
    checkpoint = HarnessRunCheckpoint(_request(save_checkpoint=save))
    await checkpoint.interrupted(captured[0])
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
    output = [item async for item in agent.run(
        current.text, message_history=[previous], current_messages=[current], checkpoint=resumed,
    )]
    assert output and not agent.error
    binary_parts = [item for message in captured[1] if isinstance(message, ModelRequest)
                    for part in message.parts if isinstance(part, UserPromptPart)
                    and not isinstance(part.content, str)
                    for item in part.content if isinstance(item, BinaryContent)]
    assert len(binary_parts) == (2 if native else 0)
    assert all(item.data == b"test" and item.media_type == mime for item in binary_parts)
    assert len(reads) == 2
    assert analyses == ([] if native else [mime, mime])


@pytest.mark.asyncio
async def test_native_chat_attachment_uses_real_resource_access_and_storage(db, tmp_path, monkeypatch):
    from app.chat.tests.test_native_facade import _scope
    from app.file_share import ResourceContext
    from app.harness.media import prepare_native_inputs
    from app.messenger import create_internal_room, get_messenger
    from core.settings import settings

    monkeypatch.setattr(type(settings), "GALARIS_INTERNAL_MESSENGER_ROOT", str(tmp_path))
    agent, owner, _ = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    messenger = await get_messenger(room.connection_id)
    sent = await messenger.upload_file(room.id, b"synthetic image bytes", name="sample.png")
    message = TaskMessage.from_messenger(sent)
    uri = message.attachments[0].uri
    llm = LLM(input_image=True)
    prepared = await prepare_native_inputs(llm, ResourceContext(agent.id, "internal"), [message], [])
    assert prepared[uri].content is not None
    assert prepared[uri].content.data == b"synthetic image bytes"

    stranger, _, _ = await _scope(db)
    denied = await prepare_native_inputs(llm, ResourceContext(stranger.id, "internal"), [message], [])
    assert denied[uri].content is None
    assert "access denied" in denied[uri].reason


@pytest.mark.asyncio
async def test_pdf_without_file_or_vision_support_supplies_text_and_visual_transcription(tmp_path, monkeypatch):
    from app import agent as agent_facade, file_share
    from app.file_share import ResourceContext
    from app.harness.media import prepare_native_inputs, message_native_parts
    from core.document import PreparedDocument, DocumentPage

    uri = "console://synthetic-scanned-report.pdf"
    image = tmp_path / "page.png"
    image.write_bytes(b"synthetic page image")
    document = PreparedDocument(name="report.pdf", sha256="synthetic", media_type="application/pdf",
        pages=[DocumentPage(number=1, text="OCR source text", image="page.png")])
    @asynccontextmanager
    async def prepared(ctx, selected_uri):
        assert selected_uri == uri and ctx.agent_id == 7
        yield document, tmp_path
    analyze = AsyncMock(return_value="Synthetic diagram description and readable labels")
    monkeypatch.setattr(file_share, "resource_info", AsyncMock(return_value=ResourceDescriptor(
        uri=uri, name="report.pdf", media_type="application/pdf", size=10)))
    monkeypatch.setattr(file_share, "prepared_resource", prepared)
    monkeypatch.setattr(agent_facade, "describe_input_image", analyze)
    message = TaskMessage(resource_uris=[uri])
    inputs = await prepare_native_inputs(LLM(input_image=False, input_file=False), ResourceContext(7, "internal"), [message], [])
    parts = message_native_parts(message, inputs)
    assert all(isinstance(part, str) for part in parts)
    assert "OCR source text" in str(parts) and "Synthetic diagram description" in str(parts)
    analyze.assert_awaited_once()
    assert analyze.await_args.args == (b"synthetic page image", "image/png")
