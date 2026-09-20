"""Documented SunoAPI.org contract, without browser cookies or unofficial endpoints."""

from typing import Any
from urllib.parse import quote

from app.llm import MediaArtifact, MediaOperation, MediaRequest, MediaResult
from app.llm.facade import AICapability, with_capability, LLMModelInfo
from app.llm.facade import GenerationProvider, media_json, MediaRequestRejected
from app.llm import ProviderConnection
from core.util import as_dict, as_list

MODELS = ("V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5", "V5_5")


class SunoApiResources:
    async def list_resources(self, connection: ProviderConnection, capability: AICapability) -> list[LLMModelInfo]:
        models = MODELS if capability == "music_generation" else ("sound:V5",) if capability == "sound_generation" else ()
        return [with_capability(LLMModelInfo(
            id=model, name=f"SunoAPI.org {model}", service_capabilities=[capability],
            resource_type="service" if capability == "sound_generation" else "model",
            metadata_source="provider-catalog",
        ), capability) for model in models]


class SunoApiMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return (operation == "music_generate" and model in MODELS) or (operation == "sound_generate" and model == "sound:V5")

    def validate(self, request: MediaRequest) -> None:
        super().validate(request)
        if request.operation == "sound_generate":
            if len(request.prompt) > 500 or request.duration is not None:
                raise ValueError("SunoAPI sounds accept at most 500 prompt characters and no explicit duration.")
            return
        custom = request.lyrics is not None or bool(request.style)
        if custom and (not request.style or not request.title):
            raise ValueError("Custom music requires a style and title.")
        if custom and not request.instrumental and not request.lyrics:
            raise ValueError("Custom vocal music requires lyrics.")
        if not custom and len(request.prompt) > 3000:
            raise ValueError("SunoAPI descriptive prompts accept at most 3000 characters.")
        if request.model == "V4" and (len(request.lyrics or "") > 3000 or len(request.style) > 200):
            raise ValueError("V4 supports 3000 lyric characters and 200 style characters.")
        if request.model in {"V4", "V4_5ALL"} and len(request.title) > 80:
            raise ValueError("This model supports titles of at most 80 characters.")
        if request.duration is not None and (request.model != "V5_5" or not custom or not 10 <= request.duration <= 360):
            raise ValueError("Explicit duration requires V5_5 custom mode, between 10 and 360 seconds.")

    async def submit(
        self, connection: ProviderConnection, request: MediaRequest, *, callback_url: str,
    ) -> MediaResult:
        self.validate(request)
        if not callback_url.startswith("https://"):
            raise ValueError("SunoAPI requires a public HTTPS callback URL for this Galaris installation.")
        body: dict[str, Any] = {"model": request.model.removeprefix("sound:"), "callBackUrl": callback_url}
        if request.operation == "sound_generate":
            endpoint = "generate/sounds"
            body.update(prompt=request.prompt, soundLoop=request.loop)
        else:
            endpoint = "generate"
            custom = request.lyrics is not None or bool(request.style)
            body.update(customMode=custom, instrumental=request.instrumental,
                        prompt=request.lyrics if custom and not request.instrumental else request.prompt)
            if custom:
                body.update(style=request.style, title=request.title)
            if request.duration is not None:
                body["duration"] = request.duration
        payload = await media_json(connection, "POST", endpoint, body=body)
        if payload.get("code") != 200:
            raise MediaRequestRejected(f"SunoAPI rejected generation (code {payload.get('code')}).")
        external_id = str(as_dict(payload.get("data")).get("taskId") or "")
        if not external_id:
            raise RuntimeError("SunoAPI returned no task identifier.")
        return MediaResult("running", external_id=external_id)

    async def poll(self, connection: ProviderConnection, request: MediaRequest, external_id: str) -> MediaResult:
        payload = await media_json(connection, "GET", f"generate/record-info?taskId={quote(external_id, safe='')}")
        if payload.get("code") != 200:
            raise ValueError(f"SunoAPI status unavailable (code {payload.get('code')}).")
        data = as_dict(payload.get("data"))
        status = str(data.get("status") or "")
        if status in {"CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "SENSITIVE_WORD_ERROR"}:
            return MediaResult("error", external_id=external_id, error=f"SunoAPI status: {status}.")
        if status == "CALLBACK_EXCEPTION":
            return MediaResult("unknown", external_id=external_id)
        if status != "SUCCESS":
            return MediaResult("running", external_id=external_id)
        tracks = as_list(as_dict(data.get("response")).get("sunoData"))
        if not tracks or len(tracks) > 4:
            raise ValueError("SunoAPI returned an invalid number of tracks.")
        artifacts = tuple(MediaArtifact(str(as_dict(track).get("id") or index), "audio/mpeg",
                                        url=str(as_dict(track).get("audioUrl") or as_dict(track).get("audio_url") or ""))
                          for index, track in enumerate(tracks))
        return MediaResult("success", external_id=external_id, artifacts=artifacts)
