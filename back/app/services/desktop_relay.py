"""Queue MCP calls for explicitly shared desktop endpoints."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, JsonValue, TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from core.database import get_db
from core.util import decrypt_value, encrypt_value
from . import service
from .desktop_relay_models import DesktopMcpRelay, DesktopMcpRequest
from .schemas import McpConfig, ServiceCreate


REQUEST_LIFETIME = timedelta(seconds=25)
PRESENCE_LIFETIME = timedelta(seconds=20)
POLL_SECONDS = 8
MAX_REQUESTS = 16
DESKTOP_HEADER = "X-Desktop-MCP-Token"
SERVICE_HEADER = "X-Desktop-MCP-Service"
SERVICE_CODE_PREFIX = "desk_"
API_PATH = "/api/services/desktop-mcp"
MCP_URL_PREFIX = f"http://127.0.0.1:8000{API_PATH}/"
message_adapter = TypeAdapter(dict[str, JsonValue])


def is_desktop_mcp_url(url: str | None) -> bool:
    """Recognize the internal MCP endpoint, including previously registered relays."""
    if url is None or not url.startswith(MCP_URL_PREFIX) or not url.endswith("/mcp"):
        return False
    identifier = url[len(MCP_URL_PREFIX):-len("/mcp")]
    try:
        return str(UUID(identifier)) == identifier
    except ValueError:
        return False


class Registration(BaseModel):
    relay: UUID
    label: str = Field(min_length=1, max_length=120)


class Delivery(BaseModel):
    request: UUID
    session: UUID
    message: dict[str, JsonValue] | None


class Completion(BaseModel):
    request: UUID
    response: dict[str, JsonValue]


class RelayUnavailable(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _valid_token(token: str) -> bool:
    return len(token) == 43 and token.isascii() and all(char.isalnum() or char in "-_" for char in token)


def _seal(message: dict[str, JsonValue]) -> str:
    return encrypt_value(message_adapter.dump_json(message).decode())


def _open(ciphertext: str) -> dict[str, JsonValue]:
    return message_adapter.validate_json(decrypt_value(ciphertext))


async def _relay(
    relay: UUID, token: str, *, desktop: bool, lock: bool = False,
) -> DesktopMcpRelay:
    if not _valid_token(token):
        raise PermissionError
    query = select(DesktopMcpRelay).where(DesktopMcpRelay.id == relay)
    row = await get_db().scalar(query.with_for_update() if lock else query)
    if row is None or not compare_digest(row.desktop_digest if desktop else row.service_digest, _digest(token)):
        raise PermissionError
    return row


async def register(data: Registration, token: str) -> int:
    if not _valid_token(token):
        raise PermissionError
    db = get_db()
    access = token_urlsafe(32)
    # An interrupted response can be retried with the same desktop-generated identity.
    try:
        async with db.begin_nested():
            existing = await db.get(DesktopMcpRelay, data.relay)
            if existing is not None:
                if not compare_digest(existing.desktop_digest, _digest(token)):
                    raise PermissionError
                return existing.service_id
            record = await service.create_service(
                ServiceCreate(
                    code=f"{SERVICE_CODE_PREFIX}{data.relay.hex[:16]}",
                    label=data.label,
                    description="",
                    mcp_config=McpConfig(
                        type="http", url=f"{MCP_URL_PREFIX}{data.relay}/mcp",
                        headers={SERVICE_HEADER: access},
                    ),
                ),
                commit=False,
            )
            db.add(DesktopMcpRelay(id=data.relay, service_id=record.id,
                                   desktop_digest=_digest(token), service_digest=_digest(access)))
    except IntegrityError:
        existing = await _relay(data.relay, token, desktop=True)
        return existing.service_id
    await db.commit()
    return record.id


async def presence(relay: UUID, token: str, *, online: bool) -> None:
    db = get_db()
    row = await _relay(relay, token, desktop=True, lock=True)
    row.last_seen_at = now() if online else None
    if not online:
        await db.execute(delete(DesktopMcpRequest).where(DesktopMcpRequest.relay_id == relay))
    await db.commit()


async def poll(relay: UUID, token: str) -> Delivery | None:
    await presence(relay, token, online=True)
    db = get_db()
    deadline = asyncio.get_running_loop().time() + POLL_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        row = await db.scalar(
            select(DesktopMcpRequest)
            .where(DesktopMcpRequest.relay_id == relay, DesktopMcpRequest.claimed.is_(False),
                   DesktopMcpRequest.expires_at > now())
            .order_by(DesktopMcpRequest.expires_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is not None:
            delivery = Delivery(request=row.id, session=row.session_key,
                                message=_open(row.message_ciphertext) if row.message_ciphertext is not None else None)
            row.claimed = True
            await db.commit()
            return delivery
        await db.commit()
        await asyncio.sleep(0.5)
    return None


async def complete(relay: UUID, token: str, data: Completion) -> None:
    await _relay(relay, token, desktop=True)
    db = get_db()
    row = await db.scalar(select(DesktopMcpRequest).where(
        DesktopMcpRequest.id == data.request, DesktopMcpRequest.relay_id == relay,
        DesktopMcpRequest.claimed.is_(True), DesktopMcpRequest.expires_at > now(),
    ).with_for_update())
    if row is not None and row.response_ciphertext is None:
        row.response_ciphertext = _seal(data.response)
    await db.commit()


async def authorize_service(relay: UUID, token: str) -> None:
    await _relay(relay, token, desktop=False)


async def request_desktop(
    relay: UUID, token: str, session: UUID, message: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    db = get_db()
    device = await _relay(relay, token, desktop=False, lock=True)
    current = now()
    if device.last_seen_at is None or device.last_seen_at + PRESENCE_LIFETIME < current:
        raise RelayUnavailable
    pending = await db.scalar(select(func.count()).select_from(DesktopMcpRequest).where(
        DesktopMcpRequest.relay_id == relay, DesktopMcpRequest.expires_at > current,
    ))
    if pending is not None and pending >= MAX_REQUESTS:
        raise RelayUnavailable
    request_key = uuid4()
    db.add(DesktopMcpRequest(id=request_key, relay_id=relay, session_key=session,
                             expires_at=current + REQUEST_LIFETIME,
                             message_ciphertext=_seal(message) if message is not None else None))
    await db.commit()
    deadline = asyncio.get_running_loop().time() + REQUEST_LIFETIME.total_seconds()
    try:
        while asyncio.get_running_loop().time() < deadline:
            row = await db.get(DesktopMcpRequest, request_key, populate_existing=True)
            await db.commit()
            if row is None:
                raise RelayUnavailable
            if row.response_ciphertext is not None:
                return _open(row.response_ciphertext)
            await asyncio.sleep(0.15)
        raise RelayUnavailable
    finally:
        await db.execute(delete(DesktopMcpRequest).where(DesktopMcpRequest.id == request_key))
        await db.commit()


async def prune_requests() -> None:
    db = get_db()
    await db.execute(delete(DesktopMcpRequest).where(DesktopMcpRequest.expires_at <= now()))
    await db.commit()
