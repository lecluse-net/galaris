"""Seedance LAS text-to-video requests and authenticated task polling."""

from typing import Any
from urllib.parse import quote

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult
from app.llm.facade import AICapability, with_capability, LLMModelInfo
from app.llm.facade import GenerationProvider, media_json
from app.llm import ProviderConnection
from core.util import as_dict

MODELS = ("dreamina-seedance-2-0-260128", "dreamina-seedance-2-0-fast-260128",
          "dreamina-seedance-2-0-mini-260615", "dreamina-seedance-2-5-260628")


class BytePlusResources:
    async def list_resources(self, connection: ProviderConnection, capability: AICapability) -> list[LLMModelInfo]:
        if capability != "video_generation":
            return []
        return [with_capability(LLMModelInfo(id=name, name=name, service_capabilities=[capability],
                                            metadata_source="provider-catalog"), capability) for name in MODELS]


class BytePlusMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return operation == "video_generate" and model in MODELS

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.duration is not None and not 4 <= request.duration <= 15:
            raise ValueError("This Seedance integration supports durations from 4 to 15 seconds.")
        if request.resolution and request.resolution not in {"480p", "720p", "1080p", "4k"}:
            raise ValueError("Unsupported Seedance resolution.")
        if request.aspect_ratio and request.aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
            raise ValueError("Unsupported Seedance aspect ratio.")

    async def submit(self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str) -> MediaResult:
        self.validate(request)
        body: dict[str, Any] = {"model": request.model, "content": [{"type": "text", "text": request.prompt}]}
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
        if status in {"failed", "expired", "cancelled"}:
            return MediaResult("error", external_id=external_id, error=f"BytePlus status: {status}.")
        if status != "succeeded":
            return MediaResult("running", external_id=external_id)
        url = str(as_dict(data.get("content")).get("video_url") or "")
        return MediaResult("success", external_id=external_id,
                           artifacts=(MediaArtifact("0", "video/mp4", url=url),))
