"""OpenRouter native audio/video analysis and asynchronous video generation."""

import base64
import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult
from app.llm.facade import GenerationProvider, media_http, media_json
from app.llm import ProviderConnection
from core.util import as_dict, as_list


class OpenRouterMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return operation in {"audio_read", "video_read", "video_generate"} or (
            operation == "music_generate" and model in {"google/lyria-3-pro-preview", "google/lyria-3-clip-preview"}
        )

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.operation == "music_generate" and request.duration is not None:
            limit = 30 if "clip" in request.model else 180
            if request.duration > limit:
                raise ValueError(f"This Lyria model supports at most {limit} seconds.")

    async def analyze(
        self, connection: ProviderConnection, request: MediaRequest,
        source: Path, media_type: str,
    ) -> MediaResult:
        self.validate(request)
        encoded = await asyncio.to_thread(lambda: base64.b64encode(source.read_bytes()).decode("ascii"))
        part: dict[str, Any]
        if request.operation == "audio_read":
            formats = {"audio/mpeg": "mp3", "audio/x-wav": "wav", "audio/wav": "wav",
                       "audio/flac": "flac", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/webm": "webm"}
            if media_type not in formats:
                raise ValueError("Unsupported audio type for OpenRouter analysis.")
            part = {"type": "input_audio", "input_audio": {"data": encoded, "format": formats[media_type]}}
        else:
            part = {"type": "video_url", "video_url": {"url": f"data:{media_type};base64,{encoded}"}}
        payload = await media_json(connection, "POST", "chat/completions", body={
            "model": request.model, "stream": False,
            "messages": [{"role": "user", "content": [{"type": "text", "text": request.prompt}, part]}],
        })
        choices = as_list(payload.get("choices"))
        message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("The media model returned no analysis.")
        cost = as_dict(payload.get("usage")).get("cost")
        return MediaResult("success", text=text, cost=float(cost) if isinstance(cost, (float, int)) else None)

    async def submit(
        self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str,
    ) -> MediaResult:
        self.validate(request)
        if request.operation == "music_generate":
            return await self._music(connection, request)
        # Validate against the live provider catalog before submitting a billable request.
        catalog = await media_json(connection, "GET", "videos/models")
        model = next((as_dict(item) for item in as_list(catalog.get("data"))
                      if as_dict(item).get("id") == request.model), None)
        if model is None:
            raise ValueError("The selected video model is unavailable in the provider catalog.")
        body: dict[str, Any] = {"model": request.model, "prompt": request.prompt}
        for key, plural in (("duration", "durations"), ("resolution", "resolutions"), ("aspect_ratio", "aspect_ratios")):
            value = getattr(request, key)
            if value is not None:
                supported = as_list(model.get(f"supported_{plural}"))
                if supported and value not in supported:
                    raise ValueError(f"Unsupported {key}: {value}; supported values: {supported}.")
                body[key] = value
        payload = await media_json(connection, "POST", "videos", body=body)
        external_id = str(payload.get("id") or "")
        if not external_id:
            raise RuntimeError("The provider accepted no identifiable video job.")
        return MediaResult("running", external_id=external_id)

    async def _music(self, connection: ProviderConnection, request: MediaRequest) -> MediaResult:
        instructions = [request.prompt, request.style]
        if request.instrumental:
            instructions.append("Create instrumental music without singing or speech.")
        elif request.lyrics:
            instructions.append(f"Sing these lyrics:\n{request.lyrics}")
        if request.duration:
            instructions.append(f"Target duration: {request.duration} seconds.")
        raw = await media_http(connection, "POST", "chat/completions", binary=True, body={
            "model": request.model, "stream": True, "modalities": ["text", "audio"],
            "audio": {"format": "wav"},
            "messages": [{"role": "user", "content": "\n".join(instructions)}],
        })
        pieces: list[str] = []
        cost: float | None = None
        complete = False
        for line in raw.decode("utf-8").splitlines():
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if value == "[DONE]":
                complete = True
                break
            if not value:
                continue
            payload = as_dict(json.loads(value))
            if payload.get("error"):
                raise ValueError("OpenRouter music stream reported a provider error.")
            usage_cost = as_dict(payload.get("usage")).get("cost")
            if isinstance(usage_cost, (float, int)):
                cost = float(usage_cost)
            for choice in as_list(payload.get("choices"))[:1]:
                audio = as_dict(as_dict(as_dict(choice).get("delta")).get("audio"))
                data = audio.get("data")
                if isinstance(data, str):
                    pieces.append(data)
        if not complete or not pieces:
            raise ValueError("OpenRouter music stream ended without a complete audio output.")
        content = base64.b64decode("".join(pieces), validate=True)
        return MediaResult("success", artifacts=(MediaArtifact("0", "audio/wav", content=content),), cost=cost)

    async def poll(
        self, connection: ProviderConnection, request: MediaRequest, external_id: str,
    ) -> MediaResult:
        path = f"videos/{quote(external_id, safe='')}"
        payload = await media_json(connection, "GET", path)
        status = payload.get("status")
        if status in {"failed", "expired", "cancelled"}:
            return MediaResult("error", external_id=external_id, error=f"Provider video status: {status}.")
        if status != "completed":
            return MediaResult("running", external_id=external_id)
        count = len(as_list(payload.get("unsigned_urls"))) or 1
        if count > 4:
            raise ValueError("Too many generated video outputs.")
        artifacts: list[MediaArtifact] = []
        for index in range(count):
            content = await media_http(connection, "GET", f"{path}/content?index={index}", binary=True)
            artifacts.append(MediaArtifact(str(index), "video/mp4", content=content))
        cost = as_dict(payload.get("usage")).get("cost")
        return MediaResult("success", external_id=external_id, artifacts=tuple(artifacts),
                           cost=float(cost) if isinstance(cost, (int, float)) else None)
