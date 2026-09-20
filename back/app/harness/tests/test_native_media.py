"""Observable model inputs, with only the resource/provider boundaries replaced."""

from pathlib import Path
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
async def test_current_and_previous_media_reach_model_without_analysis_tool(monkeypatch, mime):
    from app import file_share

    current, previous = attached_message(mime), attached_message(mime, text="Earlier media")
    reads = []
    paths = []

    async def info(ctx, uri):
        assert ctx.agent_id == 7
        return ResourceDescriptor(uri=uri, name="sample", media_type=mime, size=4)

    async def materialize(ctx, uri, path: Path, **kwargs):
        reads.append(uri)
        paths.append(path)
        path.write_bytes(b"test")
        return MaterializedResource(uri, "sample", mime, 4)

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
    monkeypatch.setattr(runtime, "build_model_for_llm", build)
    llm = LLM(input_image=True, input_audio=True, input_video=True, input_file=True,
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
    for part, source in zip(user_parts, (previous, current), strict=True):
        assert not isinstance(part.content, str)
        assert any(isinstance(item, BinaryContent) and item.data == b"test" for item in part.content)
        assert source.attachments[0].uri in str(part.content)
    assert reads == [current.attachments[0].uri, previous.attachments[0].uri]
    assert all(not path.exists() for path in paths)

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
    assert len(binary_parts) == 2
    assert all(item.data == b"test" and item.media_type == mime for item in binary_parts)
    assert len(reads) == 2


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
