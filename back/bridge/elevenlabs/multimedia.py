"""Eleven Music and sound effects; independent from voice synthesis."""

from typing import Any

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult, MusicComposition
from app.llm.facade import GenerationProvider, media_http
from app.llm import ProviderConnection

MUSIC_MODELS = ("music_v1", "music_v2", "music_v2_5")


class ElevenLabsMedia(GenerationProvider):
    supports_composition = True

    def supports(self, operation: MediaOperation, model: str) -> bool:
        return (
            operation == "music_generate" and model in MUSIC_MODELS
        ) or (operation == "sound_generate" and model == "eleven_text_to_sound_v2")

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.composition is not None:
            if request.operation != "music_generate" or request.lyrics is not None or (
                request.style or request.title or request.instrumental or request.duration is not None
            ):
                raise ValueError("Use the composition plan for styles, lyrics, and duration. Do not combine it with other music options.")
            if not request.prompt.strip() or len(request.prompt) > 200:
                raise ValueError("The global direction for an Eleven Music composition must contain 1–200 characters.")
            if sum(section.duration_ms for section in request.composition.sections) > 600_000:
                raise ValueError("An Eleven Music composition is limited to 600 seconds.")
            return
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
            if request.composition is not None:
                body["composition_plan"] = _composition_payload(request.model, request.prompt, request.composition)
            else:
                body.update(prompt="\n".join(filter(None, [request.prompt, request.style])), force_instrumental=request.instrumental)
                if request.duration is not None:
                    body["music_length_ms"] = request.duration * 1000
        content = await media_http(
            connection, "POST", endpoint, body=body, auth_header="xi-api-key", binary=True,
        )
        return MediaResult("success", artifacts=(MediaArtifact("0", "audio/mpeg", content=content),))


def _composition_payload(model: str, prompt: str, plan: MusicComposition) -> dict[str, Any]:
    styles = [prompt, *plan.styles]
    if model == "music_v1":
        return {
            "positive_global_styles": styles,
            "negative_global_styles": plan.avoid_styles,
            "sections": [
                {"section_name": section.name, "duration_ms": section.duration_ms, "lines": section.lyrics,
                 "positive_local_styles": section.styles, "negative_local_styles": section.avoid_styles}
                for section in plan.sections
            ],
        }
    return {"chunks": [
        {"text": "\n".join([f"[{section.name}]", *section.lyrics]), "duration_ms": section.duration_ms,
         "positive_styles": [*styles, *section.styles], "negative_styles": [*plan.avoid_styles, *section.avoid_styles]}
        for section in plan.sections
    ]}
