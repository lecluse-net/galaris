"""Native Hugging Face task protocols, routed with the existing HF token."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.llm.facade import (
    ImageGenerationResult, NativeImageSize, ProviderConnection,
    ProviderTranscriptionError, RealtimeSpeechStream, SpeechOptions, SpeechResult,
    TranscriptionResult,
)
from core.util import (
    as_dict, as_list, buffered_io_budget, complete_io,
    post_buffered, post_multipart_file, read_buffered_file, read_response,
)

from .resources import ROUTER, headers, resolve_route, split_model


class HuggingFaceEmbeddings:
    async def embed(
        self, connection: ProviderConnection, *, model: str, texts: list[str],
        dimensions: int | None, timeout: float,
    ) -> dict[str, Any]:
        route = await resolve_route(connection, model, "embedding", timeout=timeout)
        if route.provider == "hf-inference":
            if dimensions is not None:
                raise ValueError("HF Inference embeddings do not support selecting dimensions.")
            body: dict[str, Any] = {"inputs": texts}
        else:
            body = {"input": texts, "model": route.model, "encoding_format": "float"}
            if dimensions is not None:
                body["dimensions"] = dimensions
        raw = await post_buffered(
            route.url("feature-extraction"), headers=headers(connection), json=body,
            timeout=timeout, max_bytes=32_000_000,
        )
        payload: Any = json.loads(raw)
        if route.provider == "deepinfra":
            if not isinstance(payload, dict):
                raise ValueError("Hugging Face returned invalid embeddings.")
            return as_dict(payload)
        if not isinstance(payload, list) or any(not isinstance(vector, list) for vector in as_list(payload)):
            raise ValueError("Hugging Face returned invalid embedding vectors.")
        return {"model": model, "data": [
            {"index": index, "embedding": vector} for index, vector in enumerate(as_list(payload))
        ]}


class HuggingFaceTranscription:
    async def transcribe(
        self, connection: ProviderConnection, *, model: str, source: bytes | Path,
        filename: str, mime_type: str, language: str, timeout: float,
    ) -> TranscriptionResult:
        raw = ""
        try:
            route = await resolve_route(connection, model, "transcription", timeout=timeout)
            language_code = language.strip().lower().split("-", 1)[0]
            if route.provider == "deepinfra":
                data = {"model": route.model}
                if language_code:
                    data["language"] = language_code
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    response = await post_multipart_file(
                        client, route.url("automatic-speech-recognition"), source,
                        filename=filename, mime_type=mime_type, data=data, headers=headers(connection),
                    )
                    raw = response.content.decode("utf-8", errors="replace")
                    response.raise_for_status()
                    payload: Any = response.json()
                    request_id = response.headers.get("x-request-id")
            else:
                size = source.stat().st_size if isinstance(source, Path) else len(source)
                if size > 100_000_000:
                    raise ValueError("HF Inference audio exceeds the 100 MB upload limit.")
                async with buffered_io_budget.reserve(
                    6 * size + 12_000_000, owner=f"hf-asr:{uuid4()}",
                ):
                    content = await read_buffered_file(source, max_bytes=size) if isinstance(source, Path) else source
                    body: dict[str, Any] | None = None
                    if language_code:
                        body = {
                            "inputs": await complete_io(lambda: base64.b64encode(content).decode("ascii")),
                            "parameters": {"generation_parameters": {"language": language_code}},
                        }
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                        async with client.stream(
                            "POST", route.url("automatic-speech-recognition"),
                            headers={**headers(connection), "Content-Type": "application/json" if body else mime_type},
                            json=body, content=None if body else content,
                        ) as response:
                            raw = (await read_response(response, max_bytes=4_000_000)).decode("utf-8", errors="replace")
                            response.raise_for_status()
                            request_id = response.headers.get("x-request-id")
                payload = json.loads(raw)
            result = as_dict(payload)
            text = result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Hugging Face returned no transcription text.")
            return TranscriptionResult(
                text=text.strip(), usage=as_dict(result.get("usage")),
                upstream_request_id=request_id, raw_response=raw,
            )
        except httpx.HTTPStatusError as exc:
            raise ProviderTranscriptionError(
                f"Hugging Face transcription returned HTTP {exc.response.status_code}.", raw_response=raw,
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderTranscriptionError("Hugging Face transcription failed.", raw_response=raw) from exc


class HuggingFaceSpeech:
    async def synthesize(
        self, connection: ProviderConnection, *, model: str, resource_type: str,
        text: str, options: SpeechOptions,
    ) -> SpeechResult:
        if resource_type != "model":
            raise ValueError("Hugging Face speech requires a model resource.")
        if options.pitch or any(value is not None for value in (
            options.stability, options.similarity_boost, options.style, options.use_speaker_boost,
        )):
            raise ValueError("These voice controls are not supported by Hugging Face speech.")
        route = await resolve_route(connection, options.model.strip() or model, "speech")
        body: dict[str, Any] = {
            "model": route.model, "input": text, "response_format": "mp3", "speed": options.speed,
        }
        if options.voice.strip():
            body["voice"] = options.voice.strip().removeprefix("voice:")
        if options.language.strip():
            body["language"] = options.language.strip().lower().split("-", 1)[0]
        content = await post_buffered(
            route.url("text-to-speech"), headers={**headers(connection), "Accept": "audio/mpeg"},
            json=body, timeout=120, max_bytes=32_000_000,
        )
        if not (content.startswith(b"ID3") or (len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0)):
            raise ValueError("Hugging Face returned no MP3 audio.")
        return SpeechResult(content, connection.name, options.voice)

    async def create_realtime_stream(
        self, connection: ProviderConnection, *, model: str, resource_type: str, options: SpeechOptions,
    ) -> RealtimeSpeechStream | None:
        return None


class HuggingFaceImageGeneration:
    def select_size(self, model: str, width: int, height: int) -> NativeImageSize:
        # The native model chooses its defaults; arbitrary sizes are not portable.
        return NativeImageSize(None, None, {})

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        if sources:
            raise ValueError("Hugging Face text-to-image does not support source-image editing.")
        name, provider = split_model(model)
        if provider not in {None, "hf-inference"}:
            raise ValueError("This image provider is not supported by the Hugging Face bridge.")
        return httpx.Request(
            "POST", f"{ROUTER}/hf-inference/models/{name}", headers=headers(connection), json={"inputs": prompt},
        )

    def read_response(self, response: httpx.Response) -> ImageGenerationResult:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in {"image/png", "image/jpeg", "image/webp"} or not response.content:
            raise ValueError("Hugging Face returned no supported image.")
        return ImageGenerationResult(response.content, mime)
