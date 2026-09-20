"""Eleven Music and sound effects; independent from voice synthesis."""

from typing import Any

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult
from app.llm.facade import GenerationProvider, media_http
from app.llm import ProviderConnection


class ElevenLabsMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return (
            operation == "music_generate" and model in {"music_v1", "music_v2"}
        ) or (operation == "sound_generate" and model == "eleven_text_to_sound_v2")

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.lyrics is not None:
            raise ValueError("Exact lyrics require an Eleven Music composition plan; use a descriptive prompt.")
        if request.operation == "sound_generate" and request.duration and request.duration > 30:
            raise ValueError("ElevenLabs sound effects support at most 30 seconds.")
        if request.operation == "music_generate":
            if len("\n".join(filter(None, [request.prompt, request.style]))) > 4100 or (request.duration and request.duration < 3):
                raise ValueError("Eleven Music requires a prompt of at most 4100 characters and duration >= 3 seconds.")

    async def submit(
        self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str,
    ) -> MediaResult:
        self.validate(request)
        body: dict[str, Any] = {"model_id": request.model}
        if request.operation == "sound_generate":
            endpoint = "sound-generation"
            body.update(text=request.prompt, loop=request.loop)
            if request.duration is not None:
                body["duration_seconds"] = request.duration
        else:
            endpoint = "music"
            body.update(prompt="\n".join(filter(None, [request.prompt, request.style])), force_instrumental=request.instrumental)
            if request.duration is not None:
                body["music_length_ms"] = request.duration * 1000
        content = await media_http(
            connection, "POST", endpoint, body=body, auth_header="xi-api-key", binary=True,
        )
        return MediaResult("success", artifacts=(MediaArtifact("0", "audio/mpeg", content=content),))
