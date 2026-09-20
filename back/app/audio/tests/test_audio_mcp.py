from pathlib import Path

import pytest
from fastmcp import FastMCP

from app.audio import mcp as audio_mcp
from app.file_share import (
    MaterializedResource,
    ResourceContext,
    parse_resource_uri,
)
from app.messenger import MessagingContext, reset_context, set_context
from app.tools.mcp_loader import McpToolContext, add_galaris_tools


async def _resource_context(
    ctx: McpToolContext,
    language: str,
) -> ResourceContext:
    return ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        language=language,
    )


def _store_recorder(uploaded: dict[str, object]):
    async def store(
        _ctx: ResourceContext,
        source: Path,
        destination: str,
        *,
        default_name: str,
    ) -> str:
        reference = parse_resource_uri(
            destination or f"console://{default_name}",
            allow_empty=True,
        )
        key = reference.decoded_locator or default_name
        uploaded[key] = source.read_text(encoding="utf-8")
        return f"{reference.scheme}://{key}"

    return store


def _materializer(content: bytes, name: str):
    async def materialize(
        _ctx: ResourceContext,
        uri: object,
        destination: Path,
        *,
        max_bytes: int,
    ) -> MaterializedResource:
        assert max_bytes == audio_mcp._MAX_AUDIO_RESOURCE_BYTES
        destination.write_bytes(content)
        return MaterializedResource(
            uri=str(parse_resource_uri(uri)),
            name=name,
            media_type="audio/ogg",
            size=len(content),
        )

    return materialize


def test_default_destination_keeps_source_directory() -> None:
    assert audio_mcp._default_destination("meetings/team-call.m4a") == "meetings/team-call.txt"
    assert audio_mcp._default_destination("recording") == "recording.txt"
    assert audio_mcp._default_destination("notes.txt") == "notes.transcript.txt"
    assert audio_mcp._summary_destination("meetings/team-call.txt") == (
        "meetings/team-call.summary.md"
    )
    assert audio_mcp._default_youtube_destination(
        "https://youtu.be/dQw4w9WgXcQ"
    ) == "youtube-dQw4w9WgXcQ.txt"


def test_transcript_defaults_to_console_or_requires_a_destination() -> None:
    console_context = ResourceContext(
        agent_id=7,
        runtime="internal",
        console_resource=object(),
    )
    provider_only_context = ResourceContext(agent_id=7, runtime="hermes")

    console, _ = audio_mcp._destination(  # pyright: ignore[reportPrivateUsage]
        console_context, "", "meeting.txt"
    )
    assert str(console) == "console://meeting.txt"
    with pytest.raises(RuntimeError, match="No local filesystem"):
        audio_mcp._destination(  # pyright: ignore[reportPrivateUsage]
            provider_only_context, "", "meeting.txt"
        )


@pytest.mark.asyncio
async def test_audio_tool_schema_uses_resource_uri() -> None:
    mcp = FastMCP("test")
    add_galaris_tools(mcp, 1, runtime="internal", enabled_tool_codes={"audio"})

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    schema = tools["audio_transcribe"].parameters

    assert schema["required"] == ["file"]
    assert schema["properties"]["file"]["type"] == "string"
    assert schema["properties"]["destination"]["default"] == ""
    assert schema["properties"]["language"]["default"] == ""
    assert "YouTube" in tools["audio_transcribe"].description


@pytest.mark.asyncio
async def test_audio_transcribe_retrieves_short_youtube_captions_without_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: dict[str, str] = {}
    transcript = audio_mcp.youtube_service.YouTubeTranscript(
        video_id="dQw4w9WgXcQ",
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        language="Français",
        language_code="fr",
        is_generated=False,
        captions=(audio_mcp.youtube_service.YouTubeCaption("Bonjour", 2.0, 3.0),),
    )

    async def fake_language(_ctx: McpToolContext) -> str:
        return "fr"

    async def fake_fetch(url: str, *, language: str) -> object:
        assert url == "https://youtu.be/dQw4w9WgXcQ"
        assert language == "fr"
        return transcript

    monkeypatch.setattr(audio_mcp, "_resource_context", _resource_context)
    monkeypatch.setattr(audio_mcp, "_store_text_resource", _store_recorder(uploaded))
    monkeypatch.setattr(audio_mcp, "context_language", fake_language)
    monkeypatch.setattr(
        audio_mcp.youtube_service,
        "fetch_youtube_transcript",
        fake_fetch,
    )

    result = await audio_mcp.transcribe_audio_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "https://youtu.be/dQw4w9WgXcQ",
    )

    assert "youtube-dQw4w9WgXcQ.txt" in result
    assert "[00:00:02] Bonjour" in uploaded["youtube-dQw4w9WgXcQ.txt"]


@pytest.mark.asyncio
async def test_audio_transcribe_summarizes_long_youtube_captions_as_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: dict[str, str] = {}
    summarized_kinds: list[str] = []
    notifications: list[str] = []
    transcript = audio_mcp.youtube_service.YouTubeTranscript(
        video_id="dQw4w9WgXcQ",
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        language="English",
        language_code="en",
        is_generated=True,
        captions=(
            audio_mcp.youtube_service.YouTubeCaption("Introduction", 1.0, 2.0),
            audio_mcp.youtube_service.YouTubeCaption("Conclusion", 601.0, 2.0),
        ),
    )

    async def fake_language(_ctx: McpToolContext) -> str:
        return "fr"

    async def fake_fetch(_url: str, *, language: str) -> object:
        assert language == "fr"
        return transcript

    async def fake_notify(
        _ctx: McpToolContext,
        _language: str,
        *,
        duration_seconds: float | None,
        chunks: int,
        message_key: str = "long_processing",
    ) -> None:
        assert duration_seconds == 603.0
        assert chunks == 2
        notifications.append(message_key)

    async def fake_resolve(_agent_id: int, _task_id: object) -> object:
        return object()

    async def fake_summarize(_segment: object, **kwargs: object) -> str:
        summarized_kinds.append(str(kwargs["content_kind"]))
        return f"Partial {len(summarized_kinds)}"

    async def fake_synthesize(summaries: list[str], **_kwargs: object) -> str:
        assert summaries == ["Partial 1", "Partial 2"]
        return "# Synthèse\n\nContenu de la vidéo."

    monkeypatch.setattr(audio_mcp, "_resource_context", _resource_context)
    monkeypatch.setattr(audio_mcp, "_store_text_resource", _store_recorder(uploaded))
    monkeypatch.setattr(audio_mcp, "context_language", fake_language)
    monkeypatch.setattr(audio_mcp, "_notify_long_processing", fake_notify)
    monkeypatch.setattr(audio_mcp.youtube_service, "fetch_youtube_transcript", fake_fetch)
    monkeypatch.setattr(audio_mcp.summary_service, "resolve_summary_llm", fake_resolve)
    monkeypatch.setattr(audio_mcp.summary_service, "summarize_segment", fake_summarize)
    monkeypatch.setattr(audio_mcp.summary_service, "synthesize_video", fake_synthesize)

    result = await audio_mcp.transcribe_audio_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        language="fr",
    )

    assert summarized_kinds == ["video", "video"]
    assert notifications == ["youtube_long_processing"]
    assert "youtube-dQw4w9WgXcQ.txt" in uploaded
    assert "youtube-dQw4w9WgXcQ.summary.md" in uploaded
    assert transcript.source_url in uploaded["youtube-dQw4w9WgXcQ.summary.md"]
    assert "youtube-dQw4w9WgXcQ.summary.md" in result


@pytest.mark.asyncio
async def test_audio_transcribe_materializes_only_bounded_temporary_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.ogg"
    source.write_bytes(b"audio")
    uploaded: dict[str, object] = {}

    async def fake_language(_ctx: McpToolContext) -> str:
        return "en"

    async def fake_duration(path: Path) -> float:
        assert path.read_bytes() == b"audio"
        return 42.0

    async def fake_chunks(path: Path, destination: Path) -> list[audio_mcp.audio_service.AudioChunk]:
        assert path.read_bytes() == b"audio"
        chunk = destination / "chunk-0001.mp3"
        destination.mkdir(parents=True)
        chunk.write_bytes(b"normalized-mp3")
        return [audio_mcp.audio_service.AudioChunk(chunk, 1, 0.0, 42.0)]

    async def fake_transcribe(
        path: Path,
        *,
        filename: str,
        mime_type: str,
        language: str,
    ) -> str:
        assert path.read_bytes() == b"normalized-mp3"
        assert filename == "meeting-part-0001.mp3"
        assert mime_type == "audio/mpeg"
        assert language == "fr"
        return "Compte rendu de réunion"

    async def store(
        _ctx: ResourceContext,
        transcript: Path,
        destination: str,
        *,
        default_name: str,
    ) -> str:
        uploaded.update({
            "destination": destination or default_name,
            "content": transcript.read_text(encoding="utf-8"),
        })
        return f"console://{destination or default_name}"

    monkeypatch.setattr(audio_mcp, "_resource_context", _resource_context)
    monkeypatch.setattr(
        audio_mcp,
        "materialize_resource",
        _materializer(source.read_bytes(), "meeting.ogg"),
    )
    monkeypatch.setattr(audio_mcp, "_store_text_resource", store)
    monkeypatch.setattr(audio_mcp, "context_language", fake_language)
    monkeypatch.setattr(audio_mcp.audio_service, "media_audio_duration", fake_duration)
    monkeypatch.setattr(
        audio_mcp.audio_service,
        "normalize_for_transcription_chunks",
        fake_chunks,
    )
    monkeypatch.setattr(
        audio_mcp.transcription_service,
        "transcribe_audio_file",
        fake_transcribe,
    )

    result = await audio_mcp.transcribe_audio_file(
        McpToolContext(agent_id=7, runtime="hermes"),
        "nextcloud://Recordings/meeting.ogg",
        language="fr",
    )

    assert "console://meeting.txt" in result
    assert uploaded == {
        "destination": "meeting.txt",
        "content": "Compte rendu de réunion",
    }


@pytest.mark.asyncio
async def test_audio_transcribe_reports_missing_transcription_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_language(_ctx: McpToolContext) -> str:
        return "en"

    async def fake_duration(_path: Path) -> float:
        return 42.0

    async def fake_chunks(
        _path: Path, destination: Path
    ) -> list[audio_mcp.audio_service.AudioChunk]:
        chunk = destination / "chunk-0001.mp3"
        destination.mkdir(parents=True)
        chunk.write_bytes(b"normalized-mp3")
        return [audio_mcp.audio_service.AudioChunk(chunk, 1, 0.0, 42.0)]

    async def missing_model(_path: Path, **_kwargs: object) -> str:
        raise audio_mcp.transcription_service.TranscriptionNotConfigured(
            "no transcription resource is configured"
        )

    monkeypatch.setattr(audio_mcp, "_resource_context", _resource_context)
    monkeypatch.setattr(
        audio_mcp,
        "materialize_resource",
        _materializer(b"audio", "meeting.wav"),
    )
    monkeypatch.setattr(audio_mcp, "context_language", fake_language)
    monkeypatch.setattr(audio_mcp.audio_service, "media_audio_duration", fake_duration)
    monkeypatch.setattr(
        audio_mcp.audio_service,
        "normalize_for_transcription_chunks",
        fake_chunks,
    )
    monkeypatch.setattr(
        audio_mcp.transcription_service,
        "transcribe_audio_file",
        missing_model,
    )

    result = await audio_mcp.transcribe_audio_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "nextcloud://Recordings/meeting.wav",
    )

    assert "Audio transcription failed" in result
    assert "no transcription resource is configured" in result


@pytest.mark.asyncio
async def test_long_audio_is_chunked_notified_and_hierarchically_summarized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: dict[str, str] = {}
    notifications: list[tuple[float | None, int]] = []

    async def fake_language(_ctx: McpToolContext) -> str:
        return "fr"

    async def fake_duration(_path: Path) -> float:
        return 1_201.0

    async def fake_chunks(
        _path: Path, destination: Path
    ) -> list[audio_mcp.audio_service.AudioChunk]:
        destination.mkdir(parents=True)
        result: list[audio_mcp.audio_service.AudioChunk] = []
        for index, (start, end) in enumerate(
            ((0.0, 600.0), (600.0, 1_200.0), (1_200.0, 1_201.0)),
            start=1,
        ):
            path = destination / f"chunk-{index:04d}.mp3"
            path.write_bytes(f"chunk-{index}".encode())
            result.append(audio_mcp.audio_service.AudioChunk(path, index, start, end))
        return result

    async def fake_notify(
        _ctx: McpToolContext,
        _language: str,
        *,
        duration_seconds: float | None,
        chunks: int,
    ) -> None:
        notifications.append((duration_seconds, chunks))

    async def fake_transcribe(path: Path, **_kwargs: object) -> str:
        return f"Transcript for {path.read_text()}"

    async def fake_resolve(_agent_id: int, _task_id: object) -> object:
        return object()

    async def fake_summarize(segment: object, **_kwargs: object) -> str:
        return f"Summary {getattr(segment, 'index')}"

    async def fake_synthesize(summaries: list[str], **_kwargs: object) -> str:
        assert summaries == ["Summary 1", "Summary 2", "Summary 3"]
        return "# Synthèse finale\n\nDécisions et actions."

    monkeypatch.setattr(audio_mcp, "_resource_context", _resource_context)
    monkeypatch.setattr(
        audio_mcp,
        "materialize_resource",
        _materializer(b"long-audio", "long.mkv"),
    )
    monkeypatch.setattr(audio_mcp, "_store_text_resource", _store_recorder(uploaded))
    monkeypatch.setattr(audio_mcp, "context_language", fake_language)
    monkeypatch.setattr(audio_mcp, "_notify_long_processing", fake_notify)
    monkeypatch.setattr(audio_mcp.audio_service, "media_audio_duration", fake_duration)
    monkeypatch.setattr(
        audio_mcp.audio_service,
        "normalize_for_transcription_chunks",
        fake_chunks,
    )
    monkeypatch.setattr(
        audio_mcp.transcription_service,
        "transcribe_audio_file",
        fake_transcribe,
    )
    monkeypatch.setattr(audio_mcp.summary_service, "resolve_summary_llm", fake_resolve)
    monkeypatch.setattr(audio_mcp.summary_service, "summarize_segment", fake_summarize)
    monkeypatch.setattr(audio_mcp.summary_service, "synthesize_meeting", fake_synthesize)

    result = await audio_mcp.transcribe_audio_file(
        McpToolContext(agent_id=7, runtime="internal"),
        "nextcloud://Recordings/long.mkv",
        language="fr",
    )

    assert notifications == [(1_201.0, 3)]
    assert "long.txt" in uploaded
    assert "Transcript for chunk-1" in uploaded["long.txt"]
    assert "Segment 3" in uploaded["long.txt"]
    assert uploaded["long.summary.md"].startswith("# Synthèse finale")
    assert "console://long.summary.md" in result
    assert "uniquement la synthèse" in result


@pytest.mark.asyncio
async def test_long_audio_progress_is_sent_to_the_current_room() -> None:
    sent: list[tuple[str, str]] = []

    class FakeMessenger:
        async def send_to_room(self, room_id: str, message: str) -> None:
            sent.append((room_id, message))

    token = set_context(
        MessagingContext(
            messenger=FakeMessenger(),  # type: ignore[arg-type]
            room_id="room-42",
            agent_id=7,
        )
    )
    try:
        await audio_mcp._notify_long_processing(
            McpToolContext(agent_id=7, runtime="internal"),
            "fr",
            duration_seconds=3_661.0,
            chunks=7,
        )
    finally:
        reset_context(token)

    assert sent[0][0] == "room-42"
    assert "01:01:01" in sent[0][1]
    assert "7 segments" in sent[0][1]
