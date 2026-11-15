"""Video analysis preserves spoken content as well as visual evidence."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.llm import MediaResult, transcription_service
from app.multimedia import mcp, service
from app.services import McpToolContext


async def _command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, error = await process.communicate()
    assert process.returncode == 0, error.decode()


async def _video(directory: Path, *, subtitles: bool = False, audio: bool = True) -> Path:
    path = directory / "meeting.mkv"
    args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=32x32:r=1"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000"]
    if subtitles:
        captions = directory / "captions.srt"
        captions.write_text("1\n00:00:00,000 --> 00:00:00,900\nSynthetic meeting decision: approve the prototype.\n", encoding="utf-8")
        args += ["-i", str(captions)]
    args += ["-t", "1", "-c:v", "mpeg4"]
    if audio:
        args += ["-c:a", "pcm_s16le"]  # No encoder delay shifts the synthetic caption timestamps.
    if subtitles:
        args += ["-c:s", "srt", "-metadata:s:s:0", "language=eng"]
    await _command(*args, str(path))
    return path


@pytest.fixture
def analysis(monkeypatch):
    provider = SimpleNamespace(validate=Mock(), analyze=AsyncMock(return_value=MediaResult("success", text="Blue slide.")))
    monkeypatch.setattr(service, "authorize", AsyncMock())
    monkeypatch.setattr(service, "resolve_media_resource", AsyncMock(return_value=SimpleNamespace(
        model="synthetic-video", connection=object(), provider=provider,
    )))
    monkeypatch.setattr(service, "start_media_call", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(service, "finish_media_call", AsyncMock())
    return provider


def _source(monkeypatch, video: Path, captions: Path | None = None):
    paths = []

    async def materialize(ctx, uri, path, *, max_bytes):
        if uri == "source://captions.vtt":
            assert captions is not None
            assert max_bytes == 1_000_000
            original = captions
        else:
            assert uri == "source://meeting.mkv"
            original = video
        path.write_bytes(original.read_bytes())
        paths.append(path)
        return SimpleNamespace(media_type="video/x-matroska", name=original.name)

    monkeypatch.setattr(service, "materialize_resource", materialize)
    return paths


@pytest.mark.asyncio
async def test_video_read_transcribes_real_audio_and_supplies_both_models(tmp_path, monkeypatch, analysis):
    video = await _video(tmp_path)
    paths = _source(monkeypatch, video)
    decoded = []

    async def transcribe(path, **kwargs):
        import av
        with av.open(str(path)) as container:
            assert len(container.streams.audio) == 1
            assert not container.streams.video
            assert next(container.decode(audio=0)).samples > 0
        assert kwargs["agent_id"] == 7
        decoded.append(path)
        return "Synthetic decision: approve the prototype."

    monkeypatch.setattr(transcription_service, "transcribe_audio_file", transcribe)
    result = await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    assert result["analysis"] == "Blue slide."
    assert "approve the prototype" in result["transcript"]["text"]
    assert result["transcript"]["source"] == "speech_to_text"
    assert "approve the prototype" in analysis.analyze.call_args.args[1].prompt
    assert decoded and all(not p.exists() for p in [*paths, *decoded])


@pytest.mark.asyncio
async def test_embedded_captions_preserve_timestamps_and_skip_paid_transcription(tmp_path, monkeypatch, analysis):
    paths = _source(monkeypatch, await _video(tmp_path, subtitles=True))
    stt = AsyncMock(side_effect=AssertionError("Captions must avoid speech-to-text"))
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", stt)
    result = await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    transcript = result["transcript"]
    assert transcript["source"] == "embedded_subtitles"
    assert transcript["status"] == "available"
    assert transcript["language"] == "eng"
    assert "00:00:00,000 --> 00:00:00,900" in transcript["text"]
    assert "approve the prototype" in analysis.analyze.call_args.args[1].prompt
    stt.assert_not_awaited()
    assert all(not p.exists() for p in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("embedded", [True, False])
async def test_supplied_vtt_takes_priority_and_invalid_captions_fall_back(tmp_path, monkeypatch, analysis, valid, embedded):
    video = await _video(tmp_path, subtitles=embedded)
    captions = tmp_path / "captions.vtt"
    captions.write_text("WEBVTT\n\n00:00.000 --> 00:00.800\nSynthetic corrected decision: postpone.\n" if valid else "not subtitles", encoding="utf-8")
    paths = _source(monkeypatch, video, captions)
    stt = AsyncMock(return_value="Synthetic spoken decision: continue.")
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", stt)
    result = await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv",
                                  subtitles_uri="source://captions.vtt")
    transcript = result["transcript"]
    if valid:
        assert transcript["source"] == "external_subtitles"
        assert transcript["uri"] == "source://captions.vtt"
        assert "postpone" in transcript["text"]
        assert "approve the prototype" not in analysis.analyze.call_args.args[1].prompt
    elif embedded:
        assert transcript["source"] == "embedded_subtitles"
        assert "approve the prototype" in transcript["text"]
        assert transcript["warnings"]
    else:
        assert transcript["source"] == "speech_to_text"
        assert transcript["status"] == "available"
        assert "continue" in transcript["text"]
        assert transcript["warnings"]
    if valid or embedded:
        stt.assert_not_awaited()
    else:
        stt.assert_awaited_once()
    assert all(not p.exists() for p in paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["no_audio", "unconfigured", "provider_error", "empty"])
async def test_missing_speech_is_explicit_without_losing_visual_analysis(tmp_path, monkeypatch, analysis, condition):
    _source(monkeypatch, await _video(tmp_path, audio=condition != "no_audio"))
    stt = AsyncMock(return_value="")
    if condition == "unconfigured":
        stt.side_effect = transcription_service.TranscriptionNotConfigured("secret endpoint")
    if condition == "provider_error":
        stt.side_effect = RuntimeError("secret provider token")
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", stt)
    result = await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    assert result["analysis"] == "Blue slide."
    assert result["transcript"]["status"] == ("no_audio" if condition == "no_audio" else "unavailable")
    assert result["transcript"]["text"] == ""
    assert "secret" not in str(result)
    if condition == "no_audio":
        stt.assert_not_awaited()
    else:
        assert result["transcript"]["warnings"]


@pytest.mark.asyncio
async def test_supplied_subtitle_acl_denial_prevents_model_calls(tmp_path, monkeypatch, analysis):
    video = await _video(tmp_path)
    paths = _source(monkeypatch, video)
    materialize = service.materialize_resource

    async def denied(ctx, uri, path, **kwargs):
        if uri == "private://captions.vtt":
            raise PermissionError("Not authorized")
        return await materialize(ctx, uri, path, **kwargs)

    monkeypatch.setattr(service, "materialize_resource", denied)
    stt = AsyncMock()
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", stt)
    with pytest.raises(PermissionError):
        await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv",
                             subtitles_uri="private://captions.vtt")
    stt.assert_not_awaited()
    analysis.analyze.assert_not_awaited()
    assert all(not p.exists() for p in paths)


@pytest.mark.asyncio
async def test_transcription_cancellation_propagates_and_cleans_temporary_media(tmp_path, monkeypatch, analysis):
    paths = _source(monkeypatch, await _video(tmp_path))
    decoded = []

    async def cancelled(path, **kwargs):
        decoded.append(path)
        raise asyncio.CancelledError

    monkeypatch.setattr(transcription_service, "transcribe_audio_file", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    analysis.analyze.assert_not_awaited()
    assert decoded and all(not p.exists() for p in [*paths, *decoded])


@pytest.mark.asyncio
async def test_large_transcript_reports_both_output_and_specialist_limits(tmp_path, monkeypatch, analysis):
    _source(monkeypatch, await _video(tmp_path))
    text = "Synthetic discussion. " * 7_000
    monkeypatch.setattr(transcription_service, "transcribe_audio_file", AsyncMock(return_value=text))
    result = await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    transcript = result["transcript"]
    assert transcript["status"] == "partial"
    assert transcript["truncated"]
    assert len(transcript["text"]) <= 120_000
    assert transcript["specialist_context_truncated"]
    assert len(analysis.analyze.call_args.args[1].prompt) <= 10_000


@pytest.mark.asyncio
async def test_disabled_video_tool_never_reads_media_or_transcribes(monkeypatch):
    monkeypatch.setattr(service, "authorize", AsyncMock(side_effect=PermissionError))
    materialize = AsyncMock()
    monkeypatch.setattr(service, "materialize_resource", materialize)
    with pytest.raises(PermissionError):
        await mcp.video_read(McpToolContext(agent_id=7, runtime="internal"), "source://meeting.mkv")
    materialize.assert_not_awaited()
