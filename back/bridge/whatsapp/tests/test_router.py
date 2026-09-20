from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from core.params.runtime_settings import runtime_settings
from bridge.whatsapp import router as whatsapp_router


def _signature(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_phone_number_lookup_uses_the_tool_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import messenger
    from app.connection import connection_service

    tool = SimpleNamespace(
        id=7,
        messenger_config={
            "service": "whatsapp",
            "param_map": {"phone_number_id": "meta_phone"},
        },
    )
    connection = SimpleNamespace(id=42, active=True)

    async def records(_kind: str) -> list[SimpleNamespace]:
        return [tool]

    async def connections(
        tool_id: int,
        param_name: str,
        param_value: str,
    ) -> list[SimpleNamespace]:
        assert (tool_id, param_name, param_value) == (7, "meta_phone", "123")
        return [connection]

    monkeypatch.setattr(messenger, "messaging_tool_records", records)
    monkeypatch.setattr(
        connection_service,
        "get_connections_by_param",
        connections,
    )

    assert (
        await whatsapp_router._connection_for_phone_number_id("123")  # pyright: ignore[reportPrivateUsage]
        == 42
    )


@pytest.mark.asyncio
async def test_webhook_verification_handshake(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_WHATSAPP_VERIFY_TOKEN",
        "isolated-whatsapp-verify-secret",
    )
    response = await client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "isolated-whatsapp-verify-secret",
            "hub.challenge": "challenge-123",
        },
    )
    assert response.status_code == 200
    assert response.text == "challenge-123"

    denied = await client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "challenge-123",
        },
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_webhook_post_requires_valid_hmac(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "isolated-whatsapp-meta-app-secret-0001"
    monkeypatch.setattr(runtime_settings, "MESSENGER_WHATSAPP_APP_SECRET", secret)
    raw = b'{"object":"not_whatsapp","entry":[]}'

    rejected = await client.post(
        "/api/whatsapp/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert rejected.status_code == 401

    accepted = await client.post(
        "/api/whatsapp/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": _signature(raw, secret)},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_webhook_rejects_oversized_body(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_settings, "MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES", 1_024)
    response = await client.post("/api/whatsapp/webhook", content=b"x" * 1_025)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_disabled_webhook_is_not_exposed(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "MESSENGER_ENABLED_CHANNELS",
        '["matrix"]',
    )

    verification = await client.get("/api/whatsapp/webhook")
    delivery = await client.post("/api/whatsapp/webhook", content=b"{}")

    assert verification.status_code == 404
    assert delivery.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, "1"])
async def test_webhook_stops_consuming_oversized_stream(monkeypatch, declared):
    from fastapi import HTTPException, Request

    monkeypatch.setattr(runtime_settings, "MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES", 1024)
    monkeypatch.setattr(whatsapp_router, "is_kind_enabled", lambda _: True)
    chunks = iter([b"x" * 512, b"y" * 513, b"must not be read"])
    reads = []

    async def receive():
        chunk = next(chunks)
        reads.append(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    headers = [] if declared is None else [(b"content-length", declared.encode())]
    request = Request({"type": "http", "headers": headers}, receive)
    with pytest.raises(HTTPException) as raised:
        await whatsapp_router._receive_webhook(request, tool_id=None)
    assert raised.value.status_code == 413
    assert reads == [b"x" * 512, b"y" * 513]
