"""FastAPI webhook for verified WhatsApp Business Cloud events."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from loguru import logger
from pydantic import ValidationError

from app.messenger import journal
from app.messenger import is_kind_enabled
from app.messenger.inbound import dispatch_incoming
from core.authorize import independent_auth
from core.params import runtime_settings
from core.util import as_dict, as_list

from .messenger import WhatsAppMessenger, whatsapp_to_message
from .schemas import WhatsAppWebhook, normalize_phone

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


def verify_signature(raw: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256=") or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.lower(), expected.lower())


def _phone_ref(value: str, secret: str) -> str:
    """Keyed diagnostic fingerprint that never reveals a phone number."""
    key = secret.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:10]


async def _connection_for_phone_number_id(
    phone_number_id: str,
    *,
    tool_id: int | None = None,
) -> int | None:
    from app.connection import connection_service
    from app.messenger import messaging_tool_records

    matches: list[int] = []
    for tool in await messaging_tool_records("whatsapp"):
        if tool_id is not None and int(tool.id) != tool_id:
            continue
        messenger_config = cast(dict[str, Any], tool.messenger_config or {})
        param_map = cast(dict[str, Any], messenger_config.get("param_map") or {})
        param_name = str(param_map.get("phone_number_id") or "")
        if not param_name:
            continue
        connections = await connection_service.get_connections_by_param(
            int(tool.id), param_name, phone_number_id
        )
        matches.extend(int(item.id) for item in connections if item.active)
    if len(matches) > 1:
        logger.error(
            "WhatsApp phone_number_id has multiple active connections count={}",
            len(matches),
        )
        return None
    return matches[0] if matches else None


async def _tool_settings(tool_id: int) -> dict[str, str]:
    from app.messenger import kind_for_tool
    from app.tools import tool_service

    tool = await tool_service.get_tool_by_id(tool_id)
    if tool is None or kind_for_tool(tool) != "whatsapp" or tool.messenger is None:
        return {}
    return dict(tool.messenger.settings)


@router.get("/webhook", response_class=Response)
@independent_auth(reason="Meta webhook challenge token")
async def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    if not is_kind_enabled("whatsapp"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    configured = runtime_settings.MESSENGER_WHATSAPP_VERIFY_TOKEN
    if not configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if mode != "subscribe" or not challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    if not hmac.compare_digest(verify_token, configured):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return Response(content=challenge, media_type="text/plain")


@router.get("/webhook/{tool_id}", response_class=Response)
@independent_auth(reason="Tool-specific Meta webhook challenge token")
async def verify_tool_webhook(
    tool_id: int,
    mode: str = Query(default="", alias="hub.mode"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    """Verify the webhook owned by one Messenger-capable Tool."""

    if not is_kind_enabled("whatsapp"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    configured = (await _tool_settings(tool_id)).get("verify_token", "")
    if not configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if mode != "subscribe" or not challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    if not hmac.compare_digest(verify_token, configured):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return Response(content=challenge, media_type="text/plain")


def _contacts(value: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_value in as_list(value.get("contacts")):
        raw = as_dict(raw_value)
        if not raw:
            continue
        wa_id = normalize_phone(str(raw.get("wa_id") or ""))
        profile = as_dict(raw.get("profile"))
        if wa_id:
            result[wa_id] = str(profile.get("name") or "")
    return result


async def _process_value(
    value: dict[str, Any],
    *,
    tool_id: int | None = None,
    signature_secret: str,
) -> None:
    if not is_kind_enabled("whatsapp"):
        return
    metadata = as_dict(value.get("metadata"))
    phone_number_id = str(metadata.get("phone_number_id") or "")
    if not phone_number_id:
        return
    connection_id = await _connection_for_phone_number_id(
        phone_number_id,
        tool_id=tool_id,
    )
    if connection_id is None:
        logger.warning("WhatsApp webhook has no unique active connection")
        return
    messenger = await WhatsAppMessenger.from_connection_id(connection_id, validate=False)
    try:
        for delivery_value in as_list(value.get("statuses")):
            delivery = as_dict(delivery_value)
            if not delivery:
                continue
            errors = as_list(delivery.get("errors"))
            error = ""
            if errors:
                first_error = as_dict(errors[0])
                error = str(first_error.get("code") or first_error.get("title") or "")
            await journal.update_delivery_status(
                connection_id=connection_id,
                remote_message_id=str(delivery.get("id") or ""),
                status=str(delivery.get("status") or "unknown"),
                error=error or None,
            )

        contacts = _contacts(value)
        for raw_value in as_list(value.get("messages")):
            raw = as_dict(raw_value)
            if not raw:
                continue
            sender = normalize_phone(str(raw.get("from") or ""))
            if not messenger.is_allowed(sender):
                logger.info(
                    "WhatsApp ignored unauthorized sender ref={}",
                    _phone_ref(sender, signature_secret),
                )
                continue
            message = whatsapp_to_message(
                raw,
                contacts=contacts,
                phone_number_id=phone_number_id,
                tool_id=messenger.tool_id,
                connection_id=connection_id,
            )
            if message is None:
                continue
            inserted = await dispatch_incoming(message)
            logger.info(
                "WhatsApp webhook message connection={} new={}",
                connection_id,
                inserted,
            )
    finally:
        await messenger.client.aclose()


async def _receive_webhook(
    request: Request,
    *,
    tool_id: int | None,
) -> dict[str, str]:
    if not is_kind_enabled("whatsapp"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > runtime_settings.MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from None
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > runtime_settings.MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        body.extend(chunk)
    raw = bytes(body)
    secret = (
        (await _tool_settings(tool_id)).get("app_secret", "")
        if tool_id is not None
        else runtime_settings.MESSENGER_WHATSAPP_APP_SECRET
    )
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not verify_signature(
        raw,
        request.headers.get("X-Hub-Signature-256", ""),
        secret,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = WhatsAppWebhook.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc
    if payload.object != "whatsapp_business_account":
        return {"status": "ignored"}
    for entry in payload.entry:
        for change in entry.changes:
            if change.field == "messages":
                await _process_value(
                    change.value,
                    tool_id=tool_id,
                    signature_secret=secret,
                )
    return {"status": "ok"}


@router.post("/webhook")
@independent_auth(reason="Meta payload signature")
async def receive_webhook(request: Request) -> dict[str, str]:
    """Compatibility endpoint using the former global Meta application."""

    return await _receive_webhook(request, tool_id=None)


@router.post("/webhook/{tool_id}")
@independent_auth(reason="Tool-specific Meta payload signature")
async def receive_tool_webhook(
    request: Request,
    tool_id: int,
) -> dict[str, str]:
    """Receive events for one Tool-selected WhatsApp bridge."""

    return await _receive_webhook(request, tool_id=tool_id)
