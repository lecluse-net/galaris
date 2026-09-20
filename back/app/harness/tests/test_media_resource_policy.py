"""Native inputs replace the former blanket audio/video prohibition (decision 0126)."""

import asyncio
from pathlib import Path

import pytest

from app.agent.contracts import TaskMessage, TaskMessageAttachment
from app.file_share import MaterializedResource, ResourceContext, ResourceDescriptor
from app.harness.media import AgentInputFile, prepare_native_inputs, message_native_parts
from app.harness.runtime import Agent
from app.llm import LLM
from .test_native_media import attached_message


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unsupported", "oversized", "underreported", "denied", "download", "changed", "cancelled"])
async def test_unavailable_media_preserves_reference_and_cleans_temporary(monkeypatch, failure):
    from app import file_share
    from core.params import runtime_settings

    monkeypatch.setattr(runtime_settings, "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", 1024)
    message = attached_message()
    uri = message.attachments[0].uri
    paths = []

    async def info(ctx, source):
        assert ctx.agent_id == 7 and source == uri
        if failure == "denied":
            raise PermissionError("private diagnostic must not reach model")
        return ResourceDescriptor(uri=uri, name="sample.png", media_type="image/png",
                                  size=2048 if failure == "oversized" else 4)

    async def materialize(ctx, source, path, **kwargs):
        paths.append(path)
        path.write_bytes(b"x" * 2048 if failure == "underreported" else b"test")
        if failure == "cancelled":
            raise asyncio.CancelledError()
        if failure == "download":
            raise OSError("private diagnostic must not reach model")
        return MaterializedResource(uri, "sample.png", "image/png", 4) if failure == "underreported" else MaterializedResource(uri, "video.mp4", "video/mp4", 4)

    monkeypatch.setattr(file_share, "resource_info", info)
    monkeypatch.setattr(file_share, "materialize_resource", materialize)
    call = prepare_native_inputs(LLM(input_image=failure != "unsupported"),
                                 ResourceContext(7, "internal"), [message], [])
    if failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        inputs = await call
        assert inputs[uri].content is None
        notice = str(message_native_parts(message, inputs))
        assert uri in notice
        assert "private diagnostic" not in notice
    if failure in {"unsupported", "oversized", "denied"}:
        assert not paths
    assert all(not path.exists() for path in paths)


@pytest.mark.asyncio
async def test_current_media_has_priority_and_reopening_rechecks_access(monkeypatch):
    from app import file_share
    from core.params import runtime_settings

    monkeypatch.setattr(runtime_settings, "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", 1024)
    current, earlier = attached_message(), attached_message()
    duplicate = current.model_copy(deep=True)
    orphan = TaskMessage(attachments=[TaskMessageAttachment(id=current.attachments[0].id)])
    reads = []
    denied = False

    async def info(ctx, uri):
        if denied:
            raise PermissionError()
        return ResourceDescriptor(uri=uri, media_type="image/png", size=800)

    async def materialize(ctx, uri, path, **kwargs):
        reads.append(uri)
        assert kwargs["max_bytes"] == 1024
        path.write_bytes(b"x" * 800)
        return MaterializedResource(uri, "sample.png", "image/png", 800)

    monkeypatch.setattr(file_share, "resource_info", info)
    monkeypatch.setattr(file_share, "materialize_resource", materialize)
    ctx = ResourceContext(7, "internal")
    llm = LLM(input_image=True)
    inputs = await prepare_native_inputs(llm, ctx, [current, orphan], [earlier, duplicate])
    assert reads == [current.attachments[0].uri]
    assert inputs[earlier.attachments[0].uri].content is None
    assert len(message_native_parts(current, inputs)) == 2
    assert not message_native_parts(duplicate, inputs)
    denied = True
    reopened = await prepare_native_inputs(llm, ctx, [current], [])
    assert reopened[current.attachments[0].uri].content is None
    assert len(reads) == 1


@pytest.mark.asyncio
async def test_existing_runtime_applies_current_binary_file_limit(tmp_path: Path, monkeypatch):
    from core.params import runtime_settings

    source = tmp_path / "document.pdf"
    content = b"x" * 2048
    source.write_bytes(content)
    media = AgentInputFile(path=source, media_type="application/pdf", display_name="document.pdf",
                           agent_path="document://test/attachments/file", kind="document")
    runtime = Agent(LLM(input_file=True))
    for limit, accepted in [(1024, False), (2048, True), (1024, False)]:
        monkeypatch.setattr(runtime_settings, "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", limit)
        part = await runtime._build_file_input_part(media)
        assert (part is not None) is accepted
        if part is not None:
            assert part.data == content
        assert source.read_bytes() == content
