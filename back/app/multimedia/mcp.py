"""One optional Tool for sound/music/video analysis and durable generation."""

from typing import Any

from app.llm import MediaRequest, MusicComposition
from uuid import UUID
from .generation_service import start, read
from app.services import McpToolContext, mcp_tool
from .service import analyze
from .video_frames import FrameInput


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="audio_read", description="Analyze sounds or music from a canonical file URI: environments, instruments, birds, waves and audible events. Voice transcription uses audio_transcribe.", timeout_seconds=660)
async def audio_read(ctx: McpToolContext, uri: str, prompt: str = "Describe the audible sounds and music, with timestamps and uncertainty.") -> dict[str, Any]:
    return await analyze(ctx, "audio_read", uri, prompt)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="video_read", description="Analyze scenes, actions and spoken content from a canonical video file URI (up to 32 MB and 20 minutes). Uses supplied SRT/WebVTT subtitles_uri, then embedded text subtitles, otherwise the agent's configured speech-to-text model. Returns visual analysis and a separate transcript with provenance and coverage warnings. A bounded transcript excerpt also goes to the video specialist. language is optional; omit it for automatic speech detection. Use audio_transcribe for longer recordings or a full saved transcript. Public YouTube page URLs use audio_transcribe for captions; uri here must resolve to a media file.", timeout_seconds=660)
async def video_read(ctx: McpToolContext, uri: str, prompt: str = "Describe this video with timestamps, actions and uncertainty.",
                     subtitles_uri: str = "", language: str = "") -> dict[str, Any]:
    return await analyze(ctx, "video_read", uri, prompt, subtitles_uri=subtitles_uri, language=language)


async def _generate(
    ctx: McpToolContext, request: MediaRequest, destination: str, invocation_key: str | None, *,
    frames: tuple[FrameInput, ...] = (),
) -> dict[str, Any]:
    # Preserve fingerprints for retries made before structured composition was added.
    excluded = {"composition"} if request.composition is None else None
    return await start(ctx, {"request": request.model_dump(mode="json", exclude=excluded),
        "destination": destination, "runtime": ctx.runtime,
        **({"frames": [frame.model_dump(mode="json") for frame in frames]} if frames else {})}, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="sound_generate", description="Generate sound effects or ambient sounds. destination is a writable collection URI. Returns a durable media generation; use multimedia_get_run for the resulting files. Reuse invocation_key only when retrying the same invocation.")
async def sound_generate(ctx: McpToolContext, prompt: str, destination: str, duration: int | None = None,
                         loop: bool = False, invocation_key: str | None = None) -> dict[str, Any]:
    return await _generate(ctx, MediaRequest(operation="sound_generate", model="configured", prompt=prompt,
                                            duration=duration, loop=loop), destination, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="music_generate", description="Compose music with the profile's music provider. Optional exact lyrics, style and title depend on the provider. instrumental excludes singing. Eleven Music supports an optional composition plan with section names, durations in milliseconds, lyrics and styles. With a plan, use prompt for global direction and put lyrics, styles and timings in the plan. destination is a writable collection URI. Returns a media generation; poll multimedia_get_run for the final files. Reuse invocation_key only for a retry.")
async def music_generate(ctx: McpToolContext, prompt: str, destination: str, instrumental: bool = False,
                         lyrics: str | None = None, style: str = "", title: str = "", duration: int | None = None,
                         invocation_key: str | None = None, composition: MusicComposition | None = None) -> dict[str, Any]:
    return await _generate(ctx, MediaRequest(operation="music_generate", model="configured", prompt=prompt,
        instrumental=instrumental, lyrics=lyrics, style=style, title=title, duration=duration,
        composition=composition), destination, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="video_generate", description="Generate video with the configured specialist. With BytePlus Seedance, use first_frame_uri and optionally last_frame_uri to supply readable JPEG or PNG files by canonical URI. destination is a writable collection URI. Duration, resolution and aspect ratio depend on the selected model. Poll multimedia_get_run for the final files.")
async def video_generate(ctx: McpToolContext, prompt: str, destination: str, duration: int | None = None,
                         resolution: str | None = None, aspect_ratio: str | None = None,
                         invocation_key: str | None = None, first_frame_uri: str | None = None,
                         last_frame_uri: str | None = None) -> dict[str, Any]:
    request = MediaRequest(operation="video_generate", model="configured", prompt=prompt,
                           duration=duration, resolution=resolution, aspect_ratio=aspect_ratio)
    frames: list[FrameInput] = []
    if first_frame_uri is not None:
        frames.append(FrameInput(role="first_frame", uri=first_frame_uri))
    if last_frame_uri is not None:
        frames.append(FrameInput(role="last_frame", uri=last_frame_uri))
    return await _generate(ctx, request, destination, invocation_key, frames=tuple(frames))


@mcp_tool("multimedia", approval="ask", approval_reason="Inspect an authorized media generation", name="multimedia_get_run", description="Read a media generation's progress and final file URIs using its run_id. Generation advances in the background.")
async def multimedia_get_run(ctx: McpToolContext, run_id: UUID) -> dict[str, Any]:
    return await read(ctx, run_id)
