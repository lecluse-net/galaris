"""Audio/video understanding through Mammouth's documented chat input parts."""

import base64
import asyncio
from dataclasses import replace
from pathlib import Path

from app.llm import MediaOperation, MediaRequest, MediaResult, ProviderConnection
from app.llm.facade import GenerationProvider, media_json
from core.util import as_dict, as_list

from .protocol import MammouthProtocol


class MammouthMedia(GenerationProvider):
    def supports(self, operation: MediaOperation, model: str) -> bool:
        return operation in {"audio_read", "video_read"}

    async def analyze(
        self, connection: ProviderConnection, request: MediaRequest,
        source: Path, media_type: str,
    ) -> MediaResult:
        self.validate(request)
        if not connection.api_key:
            raise ValueError("A Mammouth API key is required.")
        part: dict[str, object]
        if request.operation == "audio_read":
            formats = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}
            if media_type not in formats:
                raise ValueError("Mammouth audio analysis accepts WAV or MP3.")
            part = {"type": "input_audio", "input_audio": {
                "data": await asyncio.to_thread(lambda: base64.b64encode(source.read_bytes()).decode("ascii")), "format": formats[media_type],
            }}
        else:
            if media_type not in {"video/mp4", "video/webm", "video/quicktime"}:
                raise ValueError("Unsupported video type for Mammouth analysis.")
            encoded = await asyncio.to_thread(lambda: base64.b64encode(source.read_bytes()).decode("ascii"))
            part = {"type": "video_url", "video_url": {"url": f"data:{media_type};base64,{encoded}"}}
        normalized = replace(connection, base_url=MammouthProtocol().base_url(connection))
        payload = await media_json(normalized, "POST", "chat/completions", body={
            "model": request.model, "stream": False,
            "messages": [{"role": "user", "content": [{"type": "text", "text": request.prompt}, part]}],
        })
        choices = as_list(payload.get("choices"))
        message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Mammouth returned no media analysis.")
        return MediaResult("success", text=text)
