from __future__ import annotations

import json

import httpx
import pytest
from unittest.mock import AsyncMock
from app.messenger.interface import DeliveryOutcomeUnknown

from bridge.whatsapp.client import (
    WhatsAppAPIError,
    WhatsAppClient,
    WhatsAppMediaTooLarge,
)


def _client(http: httpx.AsyncClient) -> WhatsAppClient:
    return WhatsAppClient(
        access_token="secret-token",
        phone_number_id="phone-id",
        graph_url="https://graph.facebook.com",
        graph_version="v23.0",
        timeout=10,
        http=http,
    )


@pytest.mark.asyncio
async def test_native_voice_payload_sets_audio_voice_flag() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.voice"}]})

    async with httpx.AsyncClient(
        base_url="https://graph.facebook.com/v23.0",
        transport=httpx.MockTransport(handler),
    ) as http:
        await _client(http).send_media(
            "33612345678",
            kind="audio",
            media_id="media-id",
            reply_to="wamid.parent",
            voice=True,
        )

    payload = json.loads(requests[0].content)
    assert payload["audio"] == {"id": "media-id", "voice": True}
    assert payload["context"] == {"message_id": "wamid.parent"}


@pytest.mark.asyncio
async def test_media_download_is_rejected_from_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media-id"):
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.facebook.com/media",
                    "mime_type": "audio/ogg",
                },
            )
        return httpx.Response(
            200,
            headers={"Content-Length": "20"},
            content=b"x" * 20,
        )

    async with httpx.AsyncClient(
        base_url="https://graph.facebook.com/v23.0",
        transport=httpx.MockTransport(handler),
    ) as http:
        with pytest.raises(WhatsAppMediaTooLarge):
            await _client(http).download_media("media-id", max_bytes=10)


def test_remote_errors_redact_numbers_and_secrets() -> None:
    error = WhatsAppAPIError(
        400,
        "131030",
        "Recipient +33 6 12 34 56 78 rejected; token=very-secret-value",
    )

    rendered = str(error)
    assert "33612345678" not in rendered.replace(" ", "")
    assert "very-secret-value" not in rendered
    assert "[redacted-number]" in rendered
    assert "[redacted-secret]" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "server"])
@pytest.mark.parametrize("operation", ["text", "template", "image", "document", "voice", "upload"])
async def test_accepted_send_with_lost_response_is_not_repeated(failure, operation):
    effects = []
    def handler(request):
        effects.append(request.content)
        if failure == "timeout":
            raise httpx.ReadTimeout("accepted but response lost", request=request)
        return httpx.Response(503)

    async with httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DeliveryOutcomeUnknown):
            client = _client(http)
            if operation == "text":
                await client.send_text("recipient", "one message")
            elif operation == "template":
                await client.send_template("recipient", name="reminder", language="fr")
            elif operation == "upload":
                await client.upload_media(b"attachment", "file.txt", "text/plain")
            else:
                await client.send_media("recipient", kind="audio" if operation == "voice" else operation,
                                        media_id="media", voice=operation == "voice")
    assert len(effects) == 1


@pytest.mark.asyncio
async def test_read_retains_bounded_network_retry(monkeypatch):
    monkeypatch.setattr("bridge.whatsapp.client.asyncio.sleep", AsyncMock())
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            raise httpx.ReadTimeout("unavailable", request=request)
        return httpx.Response(200, json={"id": "phone"})
    async with httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler)) as http:
        assert (await _client(http).validate())["id"] == "phone"
    assert count == 2
