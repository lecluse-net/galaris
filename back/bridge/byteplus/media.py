"""Seedance LAS generation from text and frame images, and authenticated polling."""

from base64 import b64encode
from typing import Any
from urllib.parse import quote

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult
from app.llm.facade import AICapability, with_capability, LLMModelInfo
from app.llm.facade import GenerationProvider, MediaRequestRejected, VideoFrame, media_json
from app.llm import ProviderConnection
from core.util import as_dict

MODEL_RESOLUTIONS = {
    "dreamina-seedance-2-0-260128": ("480p", "720p", "1080p", "4k"),
    "dreamina-seedance-2-0-fast-260128": ("480p", "720p"),
    "dreamina-seedance-2-0-mini-260615": ("480p", "720p"),
    "dreamina-seedance-2-5-260628": ("480p", "720p", "1080p"),
}


class BytePlusResources:
    async def list_resources(self, connection: ProviderConnection, capability: AICapability) -> list[LLMModelInfo]:
        if capability != "video_generation":
            return []
        return [with_capability(LLMModelInfo(id=name, name=name, service_capabilities=[capability],
                                            metadata_source="provider-catalog"), capability) for name in MODEL_RESOLUTIONS]


class BytePlusMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return operation == "video_generate" and model in MODEL_RESOLUTIONS

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.duration is not None and not 4 <= request.duration <= 15:
            raise ValueError("This Seedance integration supports durations from 4 to 15 seconds.")
        if request.resolution and request.resolution not in MODEL_RESOLUTIONS[request.model]:
            raise ValueError("Unsupported resolution for the selected Seedance model.")
        if request.aspect_ratio and request.aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
            raise ValueError("Unsupported Seedance aspect ratio.")

    async def submit(self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str) -> MediaResult:
        return await self._submit(connection, request, frames=())

    async def submit_with_frames(
        self, connection: ProviderConnection, request: MediaRequest, frames: tuple[VideoFrame, ...],
    ) -> MediaResult:
        if tuple(frame.role for frame in frames) not in {("first_frame",), ("first_frame", "last_frame")}:
            raise MediaRequestRejected("Seedance requires a first frame before an optional last frame.")
        for frame in frames:
            if not (300 <= min(frame.width, frame.height) and max(frame.width, frame.height) <= 6000
                    and 0.4 <= frame.width / frame.height <= 2.5):
                raise MediaRequestRejected("Seedance frame images require 300–6000 pixels per side and an aspect ratio of 0.4–2.5.")
        return await self._submit(connection, request, frames=frames)

    async def _submit(
        self, connection: ProviderConnection, request: MediaRequest, *, frames: tuple[VideoFrame, ...],
    ) -> MediaResult:
        self.validate(request)
        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for frame in frames:
            content.append({
                "type": "image_url", "role": frame.role,
                "image_url": {"url": f"data:{frame.media_type};base64,{b64encode(frame.content).decode('ascii')}"},
            })
        body: dict[str, Any] = {"model": request.model, "content": content}
        for key, value in (("duration", request.duration), ("resolution", request.resolution), ("ratio", request.aspect_ratio)):
            if value is not None:
                body[key] = value
        data = await media_json(connection, "POST", "contents/generations/tasks", body=body)
        external_id = str(data.get("id") or "")
        if not external_id:
            raise RuntimeError("BytePlus returned no task identifier.")
        return MediaResult("running", external_id=external_id)

    async def poll(self, connection: ProviderConnection, request: MediaRequest, external_id: str) -> MediaResult:
        data = await media_json(connection, "GET", f"contents/generations/tasks/{quote(external_id, safe='')}")
        status = data.get("status")
        if status == "cancelled":
            return MediaResult("cancelled", external_id=external_id)
        if status in {"failed", "expired"}:
            return MediaResult("error", external_id=external_id, error=f"BytePlus status: {status}.")
        if status != "succeeded":
            return MediaResult("running", external_id=external_id)
        url = str(as_dict(data.get("content")).get("video_url") or "")
        return MediaResult("success", external_id=external_id,
                           artifacts=(MediaArtifact("0", "video/mp4", url=url),))
