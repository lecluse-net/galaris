"""ElevenLabs batch and realtime transcription."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import ClientConnection, connect

from app.llm.provider_facade import (
    ProviderConnection,
    ProviderTranscriptionError,
    RealtimeTranscriber,
    TranscriptionResult,
)
from core.util import as_dict


def _websocket_url(base_url: str, path: str, query: dict[str, str]) -> str:
    parsed = urlsplit(base_url)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme)
    if scheme is None or not parsed.netloc:
        raise ProviderTranscriptionError(
            "the transcription provider has no valid WebSocket endpoint"
        )
    full_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((scheme, parsed.netloc, full_path, urlencode(query), ""))


def _payload(raw: str | bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderTranscriptionError(
            "the realtime transcription provider returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ProviderTranscriptionError(
            "the realtime transcription provider returned an invalid event"
        )
    return as_dict(value)


def _event_error(payload: dict[str, Any]) -> str:
    message_type = str(payload.get("message_type") or "")
    raw_error = payload.get("error")
    error = str(raw_error).strip() if raw_error is not None else ""
    if error:
        return error
    if message_type.endswith("_error") or message_type in {
        "rate_limited",
        "quota_exceeded",
        "resource_exhausted",
        "session_time_limit_exceeded",
    }:
        return message_type
    return ""


async def _post_multipart(
    client: httpx.AsyncClient,
    url: str,
    source: bytes | Path,
    *,
    filename: str,
    mime_type: str,
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    if isinstance(source, Path):
        with source.open("rb") as audio_file:
            return await _post_audio_file(
                client,
                url,
                audio_file,
                filename=filename,
                mime_type=mime_type,
                data=data,
                headers=headers,
            )
    return await client.post(
        url,
        data=data,
        files={"file": (filename, source, mime_type)},
        headers=headers,
    )


async def _post_audio_file(
    client: httpx.AsyncClient,
    url: str,
    audio_file: BinaryIO,
    *,
    filename: str,
    mime_type: str,
    data: dict[str, str],
    headers: dict[str, str],
) -> httpx.Response:
    return await client.post(
        url,
        data=data,
        files={"file": (filename, audio_file, mime_type)},
        headers=headers,
    )


class ElevenLabsTranscription:
    async def transcribe(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        source: bytes | Path,
        filename: str,
        mime_type: str,
        language: str,
        timeout: float,
    ) -> TranscriptionResult:
        data = {"model_id": model.removesuffix("_realtime")}
        language_code = language.strip().lower().split("-", 1)[0]
        if language_code:
            data["language_code"] = language_code
        raw_response = ""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await _post_multipart(
                    client,
                    f"{connection.base_url.rstrip('/')}/speech-to-text",
                    source,
                    filename=filename,
                    mime_type=mime_type,
                    data=data,
                    headers=(
                        {"xi-api-key": connection.api_key}
                        if connection.api_key
                        else {}
                    ),
                )
                raw_response = response.content.decode("utf-8", errors="replace")
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderTranscriptionError(
                f"the transcription provider returned HTTP {exc.response.status_code}",
                raw_response=exc.response.content.decode("utf-8", errors="replace"),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderTranscriptionError(
                "the transcription provider request failed"
            ) from exc
        except ValueError as exc:
            raise ProviderTranscriptionError(
                "the transcription provider returned invalid JSON",
                raw_response=raw_response,
            ) from exc
        text = (
            str(as_dict(payload).get("text") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        if not text:
            raise ProviderTranscriptionError(
                "the transcription provider returned no text",
                raw_response=raw_response,
            )
        payload_result = as_dict(payload)
        return TranscriptionResult(
            text=text,
            usage=as_dict(payload_result.get("usage")),
            upstream_request_id=response.headers.get("request-id")
            or response.headers.get("x-request-id"),
            raw_response=raw_response,
        )

    async def create_realtime_transcriber(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        language: str,
        sample_rate: int,
        channels: int,
    ) -> RealtimeTranscriber | None:
        if not model.endswith("_realtime"):
            return None
        query = {
            "model_id": model,
            "audio_format": f"pcm_{sample_rate}",
            "commit_strategy": "manual",
        }
        language_code = language.strip().lower().split("-", 1)[0]
        if language_code:
            query["language_code"] = language_code
        return await ElevenLabsRealtimeTranscriber.open(
            url=_websocket_url(
                connection.base_url.rstrip("/"),
                "speech-to-text/realtime",
                query,
            ),
            api_key=(connection.api_key or "").strip(),
            sample_rate=sample_rate,
            channels=channels,
        )


class ElevenLabsRealtimeTranscriber:
    def __init__(
        self,
        connection: ClientConnection,
        *,
        sample_rate: int,
        channels: int,
    ) -> None:
        self._connection = connection
        self._pending = bytearray()
        self._chunk_bytes = max(2, sample_rate * channels * 2 // 10)
        self._committed: asyncio.Queue[
            str | ProviderTranscriptionError
        ] = asyncio.Queue()
        self._failure: ProviderTranscriptionError | None = None
        self._closing = False
        self._receiver = asyncio.create_task(
            self._receive_events(),
            name="provider_realtime_stt_receiver",
        )

    @classmethod
    async def open(
        cls,
        *,
        url: str,
        api_key: str,
        sample_rate: int,
        channels: int,
    ) -> ElevenLabsRealtimeTranscriber:
        headers = {"xi-api-key": api_key} if api_key else None
        connection: ClientConnection | None = None
        try:
            connection = await connect(
                url,
                additional_headers=headers,
                open_timeout=10,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=20,
                max_queue=64,
            )
            async with asyncio.timeout(10):
                payload = _payload(await connection.recv())
            error = _event_error(payload)
            if error:
                raise ProviderTranscriptionError(error)
            if payload.get("message_type") != "session_started":
                raise ProviderTranscriptionError(
                    "the realtime transcription provider did not start a session"
                )
        except asyncio.CancelledError:
            if connection is not None:
                await asyncio.shield(connection.close())
            raise
        except ProviderTranscriptionError:
            if connection is not None:
                await connection.close()
            raise
        except Exception as exc:
            if connection is not None:
                await connection.close()
            raise ProviderTranscriptionError(
                "the realtime transcription provider connection failed"
            ) from exc
        return cls(connection, sample_rate=sample_rate, channels=channels)

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._raise_if_failed()
        self._pending.extend(pcm)
        if len(self._pending) >= self._chunk_bytes:
            await self._send_pending(commit=False)

    async def commit(self) -> str:
        self._raise_if_failed()
        await self._send_pending(commit=True)
        try:
            async with asyncio.timeout(15):
                result = await self._committed.get()
        except TimeoutError as exc:
            raise ProviderTranscriptionError(
                "the realtime transcription provider did not commit the utterance"
            ) from exc
        if isinstance(result, ProviderTranscriptionError):
            raise result
        text = result.strip()
        if not text:
            raise ProviderTranscriptionError(
                "the realtime transcription provider returned no text"
            )
        return text

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._receiver.cancel()
        await asyncio.gather(self._receiver, return_exceptions=True)
        try:
            await self._connection.close()
        except Exception:
            return

    async def _send_pending(self, *, commit: bool) -> None:
        self._raise_if_failed()
        payload: dict[str, Any] = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(bytes(self._pending)).decode("ascii"),
        }
        if commit:
            payload["commit"] = True
        try:
            await self._connection.send(json.dumps(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = ProviderTranscriptionError(
                "the realtime transcription provider connection failed"
            )
            self._failure = failure
            raise failure from exc
        self._pending.clear()

    async def _receive_events(self) -> None:
        try:
            while True:
                payload = _payload(await self._connection.recv())
                error = _event_error(payload)
                if error:
                    raise ProviderTranscriptionError(error)
                if payload.get("message_type") == "committed_transcript":
                    await self._committed.put(str(payload.get("text") or ""))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, ProviderTranscriptionError)
                else ProviderTranscriptionError(
                    "the realtime transcription provider connection failed"
                )
            )
            self._failure = failure
            await self._committed.put(failure)

    def _raise_if_failed(self) -> None:
        if self._failure is not None:
            raise self._failure
