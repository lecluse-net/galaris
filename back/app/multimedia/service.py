"""Authorization and canonical file operations for multimedia tools."""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from app.file_share import ResourceContext, materialize_resource, parse_resource_uri, resource_info
from app.llm import MediaOperation, MediaRequest, MediaResult, resolve_media_resource
from app.llm.facade import start_media_call, finish_media_call
from app.services import McpToolContext, list_enabled_native_mcp_definitions
from core.util import buffered_io_budget
from .transcripts import MAX_SUBTITLE_BYTES, SubtitleTrack, prepare_video_transcript


async def authorize(agent_id: int, operation: MediaOperation | Literal["multimedia_get_run"]) -> None:
    definitions = await list_enabled_native_mcp_definitions(agent_id, runtime="internal")
    if not any(item.name == operation for item in definitions):
        raise PermissionError(f"Multimedia function {operation} is not enabled for this agent.")


async def validate_destination(ctx: ResourceContext, destination: str) -> str:
    reference = parse_resource_uri(destination, allow_empty=True)
    if not reference.is_collection:
        raise ValueError("Multimedia destination must be a writable collection URI ending with '/'.")
    if reference.scheme == "galaris" or (reference.scheme == "document" and not reference.locator.rstrip("/").endswith("/attachments")):
        raise ValueError("Multimedia requires a binary-file collection, not a text-document collection.")
    info = await resource_info(ctx, reference)
    if "create" not in info.capabilities:
        raise ValueError("The destination does not support file creation.")
    return reference.uri


async def analyze(ctx: McpToolContext, operation: MediaOperation, uri: str, prompt: str, *,
                  subtitles_uri: str = "", language: str = "") -> dict[str, Any]:
    async with buffered_io_budget.reserve(160_000_000, owner=f"media:{ctx.agent_id}"):
        return await _analyze(ctx, operation, uri, prompt, subtitles_uri=subtitles_uri, language=language)


async def _analyze(ctx: McpToolContext, operation: MediaOperation, uri: str, prompt: str, *,
                   subtitles_uri: str = "", language: str = "") -> dict[str, Any]:
    await authorize(ctx.agent_id, operation)
    selected = await resolve_media_resource(ctx.agent_id, operation)
    request = MediaRequest(operation=operation, model=selected.model, prompt=prompt)
    selected.provider.validate(request)
    resource_ctx = ResourceContext(ctx.agent_id, ctx.runtime, ctx.task_id, ctx.resource("console"))
    with TemporaryDirectory(prefix="galaris-media-") as directory:
        path = Path(directory) / "source"
        materialized = await materialize_resource(resource_ctx, uri, path, max_bytes=32_000_000)
        # Probe the actual container and bound duration before encoding or inference.
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-max_alloc", "64000000", "-show_entries", "format=duration:stream=index,codec_type,codec_name:stream_tags=language:stream_disposition=default",
            "-of", "json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        probe = json.loads(stdout)
        duration = float(probe.get("format", {}).get("duration", 0))
        expected = "video" if operation == "video_read" else "audio"
        if process.returncode or not 0 < duration <= 1200 or not any(
            stream.get("codec_type") == expected for stream in probe.get("streams", [])
        ):
            raise ValueError("Media must contain the expected track and last at most 20 minutes.")
        media_type = materialized.media_type
        if not media_type.startswith(f"{expected}/"):
            raise ValueError("Media type does not match the requested analysis.")
        transcript_result: dict[str, Any] = {}
        if operation == "video_read":
            subtitles_path: Path | None = None
            subtitles_format = ""
            if subtitles_uri:
                subtitles_path = Path(directory) / "supplied-subtitles"
                # Preserve ACL failures rather than silently ignoring a supplied resource.
                captions = await materialize_resource(resource_ctx, subtitles_uri, subtitles_path, max_bytes=MAX_SUBTITLE_BYTES)
                extension = Path(captions.name).suffix.lower()
                if extension not in {".srt", ".vtt"}:
                    raise ValueError("Supplied subtitles must be an SRT or WebVTT file.")
                subtitles_format = "srt" if extension == ".srt" else "webvtt"
            transcript = await prepare_video_transcript(
                path, Path(directory), agent_id=ctx.agent_id, task_id=ctx.task_id,
                has_audio=any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])),
                tracks=[SubtitleTrack(int(stream["index"]), str(stream.get("codec_name", "")),
                                      str(stream.get("tags", {}).get("language", "")),
                                      bool(stream.get("disposition", {}).get("default", 0)))
                        for stream in probe.get("streams", []) if stream.get("codec_type") == "subtitle"],
                subtitles_path=subtitles_path, subtitles_format=subtitles_format, language=language,
            )
            enriched_prompt, context_truncated = transcript.specialist_prompt(prompt)
            request = MediaRequest(operation=operation, model=selected.model, prompt=enriched_prompt)
            selected.provider.validate(request)
            transcript_result = {"transcript": {**asdict(transcript), "specialist_context_truncated": context_truncated,
                                                "uri": subtitles_uri if transcript.source == "external_subtitles" else uri}}
        call_id = await start_media_call(selected, request, agent_id=ctx.agent_id, task_id=ctx.task_id)
        try:
            result = await selected.provider.analyze(selected.connection, request, path, media_type)
        except Exception:
            await finish_media_call(call_id, MediaResult("error", error="Media analysis failed."))
            raise
        await finish_media_call(call_id, result)
    return {"uri": uri, "analysis": result.text, "model": selected.model, **transcript_result,
            "cost": result.cost, "cost_quality": "exact" if result.cost is not None else "unknown",
            "cost_scope": "media_analysis_only; speech-to-text calls are accounted separately"}
