"""ElevenLabs batch and realtime speech synthesis."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from loguru import logger
from websockets.asyncio.client import ClientConnection, connect

from app.llm.provider_facade import (
    ProviderConnection,
    RealtimeSpeechStream,
    SpeechOptions,
    SpeechResult,
)
from core.util import as_dict, post_buffered


def _voice(resource_type: str, model: str, options: SpeechOptions) -> str:
    if options.voice.strip():
        return options.voice.strip().removeprefix("voice:")
    if resource_type == "voice":
        return model.strip().removeprefix("voice:")
    return ""


def _model(resource_type: str, model: str, options: SpeechOptions, default: str) -> str:
    if options.model.strip():
        return options.model.strip()
    return model.strip() if resource_type != "voice" else default


def _settings(options: SpeechOptions) -> dict[str, Any]:
    if options.speed < 0.7 or options.speed > 1.2:
        raise ValueError("speed must be between 0.7 and 1.2")
    settings: dict[str, Any] = {"speed": options.speed}
    for key, value in (
        ("stability", options.stability),
        ("similarity_boost", options.similarity_boost),
        ("style", options.style),
        ("use_speaker_boost", options.use_speaker_boost),
    ):
        if value is not None:
            settings[key] = value
    return settings


def _api_key(connection: ProviderConnection) -> str:
    if not connection.api_key:
        raise ValueError(f"provider {connection.name} requires an API key")
    return connection.api_key


def _websocket_url(base_url: str, path: str, query: dict[str, str]) -> str:
    parsed = urlsplit(base_url)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise RuntimeError("the TTS provider has no valid WebSocket endpoint")
    full_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((scheme, parsed.netloc, full_path, urlencode(query), ""))


class ElevenLabsRealtimeSpeechStream:
    sample_rate = 24_000
    channels = 1

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        options: SpeechOptions,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._options = options

    def stream(self, segments: AsyncIterator[str]) -> AsyncIterator[bytes]:
        return self._stream(segments)

    async def _stream(self, segments: AsyncIterator[str]) -> AsyncIterator[bytes]:
        connection: ClientConnection | None = None
        sender: asyncio.Task[None] | None = None
        try:
            connection = await connect(
                self._url,
                additional_headers={"xi-api-key": self._api_key},
                open_timeout=10,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=20,
                max_queue=64,
            )
            sender = asyncio.create_task(
                self._send_text(connection, segments),
                name="provider_realtime_tts_sender",
            )
            while True:
                receive = asyncio.create_task(
                    connection.recv(),
                    name="provider_realtime_tts_receiver",
                )
                done, _ = await asyncio.wait(
                    {receive, sender},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if sender in done:
                    if sender.cancelled():
                        receive.cancel()
                        await asyncio.gather(receive, return_exceptions=True)
                        raise asyncio.CancelledError
                    sender_error = sender.exception()
                    if sender_error is not None:
                        receive.cancel()
                        await asyncio.gather(receive, return_exceptions=True)
                        raise sender_error
                raw = receive.result() if receive.done() else await receive
                decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                payload = json.loads(decoded)
                if not isinstance(payload, dict):
                    raise RuntimeError("the realtime TTS provider returned an invalid event")
                event = as_dict(payload)
                error = str(event.get("error") or "").strip()
                if error:
                    raise RuntimeError(error)
                encoded = event.get("audio")
                if isinstance(encoded, str) and encoded:
                    try:
                        audio = base64.b64decode(encoded, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise RuntimeError(
                            "the realtime TTS provider returned invalid audio"
                        ) from exc
                    if audio:
                        yield audio
                if event.get("is_final") is True or event.get("isFinal") is True:
                    break
            await sender
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError("the realtime TTS provider stream failed") from exc
        finally:
            if sender is not None and not sender.done():
                sender.cancel()
            if sender is not None:
                await asyncio.gather(sender, return_exceptions=True)
            if connection is not None:
                try:
                    await connection.close()
                except Exception as exc:
                    logger.debug(
                        "ElevenLabs realtime connection close failed: {}",
                        type(exc).__name__,
                    )

    async def _send_text(
        self,
        connection: ClientConnection,
        segments: AsyncIterator[str],
    ) -> None:
        await connection.send(
            json.dumps({"text": " ", "voice_settings": _settings(self._options)})
        )
        async for segment in segments:
            text = segment.strip()
            if text:
                await connection.send(json.dumps({"text": f"{text} "}))
        await connection.send(json.dumps({"text": ""}))


class ElevenLabsSpeech:
    async def synthesize(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        text: str,
        options: SpeechOptions,
    ) -> SpeechResult:
        voice = _voice(resource_type, model, options)
        if not voice:
            raise ValueError("a voice is required")
        selected_model = _model(
            resource_type,
            model,
            options,
            "eleven_multilingual_v2",
        )
        payload: dict[str, Any] = {
            "text": text,
            "model_id": selected_model,
            "voice_settings": _settings(options),
        }
        if options.language.strip():
            payload["language_code"] = options.language.strip()
        content = await post_buffered(
                (
                    f"{connection.base_url.rstrip('/')}/text-to-speech/"
                    f"{quote(voice, safe='')}"
                ),
                headers={
                    "xi-api-key": _api_key(connection),
                    "Accept": "audio/mpeg",
                },
                json=payload,
                params={"output_format": "mp3_44100_128"},
            )
        if not content:
            raise RuntimeError("the TTS provider returned an empty audio file")
        return SpeechResult(content, connection.name, voice)

    async def create_realtime_stream(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        options: SpeechOptions,
    ) -> RealtimeSpeechStream | None:
        voice = _voice(resource_type, model, options)
        if not voice:
            raise ValueError("a voice is required")
        selected_model = _model(
            resource_type,
            model,
            options,
            "eleven_flash_v2_5",
        )
        query = {
            "model_id": selected_model,
            "output_format": "pcm_24000",
            "auto_mode": "true",
            "inactivity_timeout": "180",
            "apply_text_normalization": "auto",
        }
        language_code = options.language.strip().lower().split("-", 1)[0]
        if language_code:
            query["language_code"] = language_code
        return ElevenLabsRealtimeSpeechStream(
            url=_websocket_url(
                connection.base_url.rstrip("/"),
                f"text-to-speech/{quote(voice, safe='')}/stream-input",
                query,
            ),
            api_key=_api_key(connection),
            options=options,
        )
