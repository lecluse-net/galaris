"""Audio MCP tools operating on resource URIs or public YouTube video URLs."""

from __future__ import annotations

import math
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any

from loguru import logger

from app.file_share import (
    ResourceContext,
    ResourceUri,
    materialize_resource,
    parse_resource_uri,
    preferred_local_resource_uri,
    resource_create,
    resource_write,
)
from app.llm import transcription_service
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from bridge.youtube import transcript_service as youtube_service
from core.i18n import render_prompt, t

from . import audio_service, summary_service


_MAX_AUDIO_RESOURCE_BYTES = 512 * 1024 * 1024


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"audio.{key}", language), **values)


def _default_destination(source: str) -> str:
    path = Path(source)
    if path.suffix.lower() == ".txt":
        return path.with_name(f"{path.stem}.transcript.txt").as_posix()
    if path.suffix:
        return path.with_suffix(".txt").as_posix()
    return path.with_name(f"{path.name}.txt").as_posix()


def _summary_destination(transcript_destination: str) -> str:
    path = Path(transcript_destination)
    if path.suffix:
        return path.with_name(f"{path.stem}.summary.md").as_posix()
    return path.with_name(f"{path.name}.summary.md").as_posix()


def _is_youtube_source(value: str) -> bool:
    try:
        youtube_service.youtube_video_id(value.strip())
    except youtube_service.InvalidYouTubeUrl:
        return False
    return True


def _default_youtube_destination(url: str) -> str:
    return f"youtube-{youtube_service.youtube_video_id(url)}.txt"


def _clock(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


async def _resource_context(ctx: McpToolContext, language: str) -> ResourceContext:
    return ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        console_resource=ctx.resource("console"),
        language=language,
    )


def _destination(
    resource_ctx: ResourceContext,
    value: str,
    default_name: str,
) -> tuple[ResourceUri, str]:
    reference = parse_resource_uri(
        value or preferred_local_resource_uri(resource_ctx, default_name),
        allow_empty=True,
    )
    return reference, default_name if reference.is_collection else ""


async def _store_text_resource(
    resource_ctx: ResourceContext,
    source: Path,
    destination: str,
    *,
    default_name: str,
) -> str:
    reference, name = _destination(resource_ctx, destination, default_name)
    content = source.read_bytes()
    try:
        mutation = await resource_create(resource_ctx, reference, content, name=name)
    except FileExistsError:
        if reference.is_collection:
            raise
        mutation = await resource_write(resource_ctx, reference, content)
    return mutation.uri


def _summary_resource_destination(transcript_uri: str) -> str:
    reference = parse_resource_uri(transcript_uri)
    return str(
        parse_resource_uri(
            f"{reference.scheme}://{_summary_destination(reference.decoded_locator)}"
        )
    )


async def _notify_long_processing(
    ctx: McpToolContext,
    language: str,
    *,
    duration_seconds: float | None,
    chunks: int,
    message_key: str = "long_processing",
) -> None:
    """Warn the room once without marking the task's final answer as delivered."""
    message = _message(
        language,
        message_key,
        duration=_clock(duration_seconds) if duration_seconds is not None else "?",
        chunks=chunks,
        minutes=audio_service.TRANSCRIPTION_CHUNK_SECONDS // 60,
    )
    from app.messenger import current_context, send_task_progress

    messaging = current_context()
    if messaging is not None and messaging.messenger is not None and messaging.room_id:
        try:
            await messaging.messenger.send_to_room(messaging.room_id, message)
            return
        except Exception:
            logger.exception("Could not send in-context long-audio progress message")
    if ctx.task_id is not None:
        await send_task_progress(ctx.agent_id, ctx.task_id, message)


async def _transcribe_youtube_url(
    ctx: McpToolContext,
    url: str,
    destination: str,
    language: str,
    tool_language: str,
) -> str:
    """Retrieve public captions and store them through the resource facade."""
    try:
        resource_ctx = await _resource_context(ctx, tool_language)
        default_name = _default_youtube_destination(url)
        transcript = await youtube_service.fetch_youtube_transcript(
            url,
            language=language or tool_language,
        )
        segments = youtube_service.segment_youtube_transcript(transcript)
        transcript_characters = sum(len(segment.transcript) for segment in segments)
        is_long = (
            len(segments) > 1
            or transcript.duration_seconds > audio_service.TRANSCRIPTION_CHUNK_SECONDS
        )

        with TemporaryDirectory(prefix="galaris_youtube_") as temporary_dir:
            temp_root = Path(temporary_dir)
            output_path = temp_root / "transcript.txt"
            summary_path = temp_root / "summary.md"
            output_path.write_text(
                youtube_service.render_youtube_transcript(transcript, segments),
                encoding="utf-8",
            )

            if not is_long:
                location = await _store_text_resource(
                    resource_ctx,
                    output_path,
                    destination,
                    default_name=default_name,
                )
                return _message(
                    tool_language,
                    "youtube_transcribed",
                    size=transcript_characters,
                    caption_language=transcript.language_code,
                    location=location,
                )

            await _notify_long_processing(
                ctx,
                tool_language,
                duration_seconds=transcript.duration_seconds,
                chunks=len(segments),
                message_key="youtube_long_processing",
            )
            summary_llm = await summary_service.resolve_summary_llm(ctx.agent_id, ctx.task_id)
            summaries: list[str] = []
            for segment in segments:
                summaries.append(
                    await summary_service.summarize_segment(
                        summary_service.TranscriptSegment(
                            index=segment.index,
                            start_seconds=segment.start_seconds,
                            end_seconds=segment.end_seconds,
                            transcript=segment.transcript,
                        ),
                        llm=summary_llm,
                        language=language or tool_language,
                        task_id=ctx.task_id,
                        agent_id=ctx.agent_id,
                        content_kind="video",
                    )
                )

            summary = await summary_service.synthesize_video(
                summaries,
                llm=summary_llm,
                language=language or tool_language,
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
            )
            summary_path.write_text(
                f"# YouTube summary — {transcript.video_id}\n\n"
                f"- Source: {transcript.source_url}\n"
                f"- Caption language: {transcript.language} "
                f"({transcript.language_code})\n\n"
                f"{summary.rstrip()}\n",
                encoding="utf-8",
            )
            location = await _store_text_resource(
                resource_ctx,
                output_path,
                destination,
                default_name=default_name,
            )
            summary_location = await _store_text_resource(
                resource_ctx,
                summary_path,
                _summary_resource_destination(location),
                default_name=_summary_destination(default_name),
            )
            return _message(
                tool_language,
                "youtube_long_transcribed",
                chunks=len(segments),
                size=transcript_characters,
                caption_language=transcript.language_code,
                transcript=location,
                summary=summary_location,
            )
    except youtube_service.InvalidYouTubeUrl:
        return _message(tool_language, "youtube_invalid_url")
    except youtube_service.YouTubeCaptionsUnavailable:
        return _message(tool_language, "youtube_captions_unavailable")
    except youtube_service.YouTubeVideoUnavailable:
        return _message(tool_language, "youtube_video_unavailable")
    except youtube_service.YouTubeAccessBlocked:
        return _message(tool_language, "youtube_access_blocked")
    except youtube_service.YouTubeTranscriptFetchFailed:
        logger.exception("MCP audio_transcribe could not retrieve YouTube captions")
        return _message(tool_language, "youtube_fetch_failed")
    except Exception:
        logger.exception("MCP audio_transcribe failed for a YouTube URL")
        return _message(tool_language, "youtube_fetch_failed")


@mcp_tool(
    "audio",
    name="audio_transcribe",
    description=(
        "Transcribe an audio/video resource from any canonical file_schemes URI, or retrieve "
        "the available captions from a public "
        "YouTube video URL. Use this whenever a user asks to read, transcribe, summarize, or "
        "analyze spoken content from an audio file, video file, or YouTube link. Galaris "
        "materializes provider media into a bounded temporary file and sends it to the dedicated "
        "speech-to-text model; YouTube manual or automatic "
        "captions are retrieved without downloading the video. Sources over about 10 minutes are "
        "split into bounded text segments and hierarchically summarized without placing the full "
        "transcript in executor context. destination accepts any writable resource URI; it may "
        "be omitted only when console:// is advertised."
    ),
)
async def transcribe_audio_file(
    ctx: McpToolContext,
    file: str,
    destination: str = "",
    language: str = "",
) -> str:
    """Transcribe resource media or retrieve captions from a public YouTube URL."""
    tool_language = await context_language(ctx)
    if _is_youtube_source(file):
        return await _transcribe_youtube_url(
            ctx,
            file.strip(),
            destination,
            language,
            tool_language,
        )

    with TemporaryDirectory(prefix="galaris_audio_") as temporary_dir:
        temp_root = Path(temporary_dir)
        input_path = temp_root / "source-media"
        chunks_dir = temp_root / "chunks"
        output_path = temp_root / "transcript.txt"
        summary_path = temp_root / "summary.md"
        try:
            resource_ctx = await _resource_context(ctx, tool_language)
            materialized = await materialize_resource(
                resource_ctx,
                file,
                input_path,
                max_bytes=_MAX_AUDIO_RESOURCE_BYTES,
            )
            default_name = _default_destination(materialized.name)
            duration = await audio_service.media_audio_duration(input_path)
            notified = False
            if (
                duration is not None
                and duration > audio_service.TRANSCRIPTION_CHUNK_SECONDS
            ):
                estimated_chunks = math.ceil(
                    duration / audio_service.TRANSCRIPTION_CHUNK_SECONDS
                )
                await _notify_long_processing(
                    ctx,
                    tool_language,
                    duration_seconds=duration,
                    chunks=estimated_chunks,
                )
                notified = True

            chunks = await audio_service.normalize_for_transcription_chunks(
                input_path,
                chunks_dir,
            )
            is_long = len(chunks) > 1
            if is_long and not notified:
                await _notify_long_processing(
                    ctx,
                    tool_language,
                    duration_seconds=chunks[-1].end_seconds,
                    chunks=len(chunks),
                )

            summary_llm = (
                await summary_service.resolve_summary_llm(ctx.agent_id, ctx.task_id)
                if is_long
                else None
            )
            summaries: list[str] = []
            transcript_characters = 0
            source_stem = Path(materialized.name).stem or "audio"
            with output_path.open("w", encoding="utf-8") as transcript_file:
                if is_long:
                    transcript_file.write(
                        f"# Transcript — {source_stem}\n\n"
                        f"Segments: {len(chunks)} × approximately "
                        f"{audio_service.TRANSCRIPTION_CHUNK_SECONDS // 60} minutes\n\n"
                    )
                for chunk in chunks:
                    transcript = await transcription_service.transcribe_audio_file(
                        chunk.path,
                        filename=f"{source_stem}-part-{chunk.index:04d}.mp3",
                        mime_type="audio/mpeg",
                        language=language,
                    )
                    transcript_characters += len(transcript)
                    if is_long:
                        transcript_file.write(
                            f"## Segment {chunk.index} — {_clock(chunk.start_seconds)}–"
                            f"{_clock(chunk.end_seconds)}\n\n"
                        )
                        transcript_file.write(transcript.strip() + "\n\n")
                    else:
                        transcript_file.write(transcript.strip())
                    if summary_llm is not None:
                        summaries.append(
                            await summary_service.summarize_segment(
                                summary_service.TranscriptSegment(
                                    index=chunk.index,
                                    start_seconds=chunk.start_seconds,
                                    end_seconds=chunk.end_seconds,
                                    transcript=transcript,
                                ),
                                llm=summary_llm,
                                language=language or tool_language,
                                task_id=ctx.task_id,
                                agent_id=ctx.agent_id,
                            )
                        )

            location = await _store_text_resource(
                resource_ctx,
                output_path,
                destination,
                default_name=default_name,
            )
            if not is_long or summary_llm is None:
                return _message(
                    tool_language,
                    "transcribed",
                    size=transcript_characters,
                    location=location,
                )

            summary = await summary_service.synthesize_meeting(
                summaries,
                llm=summary_llm,
                language=language or tool_language,
                task_id=ctx.task_id,
                agent_id=ctx.agent_id,
            )
            summary_path.write_text(summary.rstrip() + "\n", encoding="utf-8")
            summary_location = await _store_text_resource(
                resource_ctx,
                summary_path,
                _summary_resource_destination(location),
                default_name=_summary_destination(default_name),
            )
            return _message(
                tool_language,
                "long_transcribed",
                chunks=len(chunks),
                size=transcript_characters,
                transcript=location,
                summary=summary_location,
            )
        except Exception as exc:
            logger.exception("MCP audio_transcribe failed")
            return _message(tool_language, "transcription_failed", error=exc)
