"""One optional Tool for sound/music/video analysis and durable generation."""

from typing import Any

from app.llm import MediaRequest
from uuid import UUID
from .generation_service import start, read
from app.tools import McpToolContext, mcp_tool
from .service import analyze


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="audio_read", description="Analyze sounds or music from a canonical file URI: environments, instruments, birds, waves and audible events. Voice transcription uses audio_transcribe.", timeout_seconds=660)
async def audio_read(ctx: McpToolContext, uri: str, prompt: str = "Describe the audible sounds and music, with timestamps and uncertainty.") -> dict[str, Any]:
    return await analyze(ctx, "audio_read", uri, prompt)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="video_read", description="Analyze a video from a canonical file URI with the configured video specialist. Ask about scenes, actions and timestamps.", timeout_seconds=660)
async def video_read(ctx: McpToolContext, uri: str, prompt: str = "Describe this video with timestamps, actions and uncertainty.") -> dict[str, Any]:
    return await analyze(ctx, "video_read", uri, prompt)


async def _generate(ctx: McpToolContext, request: MediaRequest, destination: str, invocation_key: str | None) -> dict[str, Any]:
    return await start(ctx, {"request": request.model_dump(mode="json"),
        "destination": destination, "runtime": ctx.runtime}, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="sound_generate", description="Generate sound effects or ambient sounds. destination is a writable collection URI. Returns a durable media generation; use multimedia_get_run for the resulting files. Reuse invocation_key only when retrying the same invocation.")
async def sound_generate(ctx: McpToolContext, prompt: str, destination: str, duration: int | None = None,
                         loop: bool = False, invocation_key: str | None = None) -> dict[str, Any]:
    return await _generate(ctx, MediaRequest(operation="sound_generate", model="configured", prompt=prompt,
                                            duration=duration, loop=loop), destination, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="music_generate", description="Compose music with the profile's music provider. Optional exact lyrics, style and title depend on the provider. instrumental excludes singing. destination is a writable collection URI. Returns a media generation with one or more final files; poll multimedia_get_run. Reuse invocation_key only for a retry.")
async def music_generate(ctx: McpToolContext, prompt: str, destination: str, instrumental: bool = False,
                         lyrics: str | None = None, style: str = "", title: str = "", duration: int | None = None,
                         invocation_key: str | None = None) -> dict[str, Any]:
    return await _generate(ctx, MediaRequest(operation="music_generate", model="configured", prompt=prompt,
        instrumental=instrumental, lyrics=lyrics, style=style, title=title, duration=duration), destination, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Mutation, disclosure, paid processing or execution requires one-action approval", name="video_generate", description="Generate video from a prompt using the configured specialist (including Seedance). destination is a writable collection URI. Duration, resolution and aspect ratio must be supported by the selected provider. Returns a media generation; poll multimedia_get_run for final files.")
async def video_generate(ctx: McpToolContext, prompt: str, destination: str, duration: int | None = None,
                         resolution: str | None = None, aspect_ratio: str | None = None,
                         invocation_key: str | None = None) -> dict[str, Any]:
    return await _generate(ctx, MediaRequest(operation="video_generate", model="configured", prompt=prompt,
        duration=duration, resolution=resolution, aspect_ratio=aspect_ratio), destination, invocation_key)


@mcp_tool("multimedia", approval="ask", approval_reason="Inspect an authorized media generation", name="multimedia_get_run", description="Read a media generation's progress and final file URIs using its run_id. Generation advances in the background.")
async def multimedia_get_run(ctx: McpToolContext, run_id: UUID) -> dict[str, Any]:
    return await read(ctx, run_id)
