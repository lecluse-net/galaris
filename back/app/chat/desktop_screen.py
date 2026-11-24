"""One-use screen requests routed to the authenticated desktop tab that sent the turn."""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import anyio
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.conversation.contracts import ConversationTurn
from app.messenger import get_internal_room, has_chat_room_access
from core.database import get_db
from core.user import web_session_active
from core.util import decrypt_value, encrypt_value

from .models import ChatDesktopScreenRequest, ChatDesktopScreenSession


SCREEN_HEADER = "X-Galaris-Chat-Desktop"
MAX_IMAGE_BYTES = 1_500_000
PRESENCE_LIFETIME = timedelta(seconds=18)
CAPTURE_LIFETIME = timedelta(seconds=50)
_KEY = re.compile(r"[A-Za-z0-9_-]{43}")


class ScreenRequest(BaseModel):
    id: UUID
    expires_at: datetime
    agent: str
    reason: str


class ScreenUnavailable(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def tab_identity(user_id: int, family: str, key: str) -> UUID | None:
    if not _KEY.fullmatch(key):
        return None
    return UUID(bytes=sha256(f"{user_id}:{family}:{key}".encode()).digest()[:16])


async def register_tab(user_id: int, family: str, source: UUID) -> None:
    db = get_db()
    until = _now() + PRESENCE_LIFETIME
    await db.execute(insert(ChatDesktopScreenSession).values(
        id=source, user_id=user_id, web_family=family, expires_at=until,
    ).on_conflict_do_update(index_elements=[ChatDesktopScreenSession.id], set_={"expires_at": until},
        where=(ChatDesktopScreenSession.user_id == user_id) & (ChatDesktopScreenSession.web_family == family)))
    await db.commit()


async def forget_tab(source: UUID) -> None:
    await get_db().execute(delete(ChatDesktopScreenSession).where(ChatDesktopScreenSession.id == source))
    await get_db().commit()


async def tab_is_live(user_id: int, family: str, source: UUID) -> bool:
    row = await get_db().get(ChatDesktopScreenSession, source)
    return bool(row and row.user_id == user_id and row.web_family == family and row.expires_at > _now())


async def await_screen_authorization(source: UUID, identifier: UUID) -> bool:
    db = get_db()
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        alive = await db.scalar(select(ChatDesktopScreenRequest.id).where(
            ChatDesktopScreenRequest.session_id == source, ChatDesktopScreenRequest.id == identifier,
            ChatDesktopScreenRequest.outcome.is_(None), ChatDesktopScreenRequest.expires_at > _now(),
        ))
        await db.commit()
        if alive is None:
            return False
        await asyncio.sleep(0.5)
    return True


async def next_screen_request(source: UUID) -> ScreenRequest | None:
    db = get_db()
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        row = await db.scalar(select(ChatDesktopScreenRequest).where(
            ChatDesktopScreenRequest.session_id == source,
            ChatDesktopScreenRequest.claimed_at.is_(None), ChatDesktopScreenRequest.expires_at > _now(),
        ).order_by(ChatDesktopScreenRequest.expires_at).limit(1).with_for_update(skip_locked=True))
        if row is not None:
            row.claimed_at = _now()
            request = ScreenRequest(id=row.id, expires_at=row.expires_at, agent=row.agent_label, reason=row.reason)
            await db.commit()
            return request
        await db.commit()
        await asyncio.sleep(0.25)
    return None


def verify_image(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data), formats=["JPEG"]) as image:
            if not (0 < image.width <= 1920 and 0 < image.height <= 1920):
                return False
            image.load()
            return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


async def complete_screen_request(source: UUID, user_id: int, identifier: UUID, content: bytes | None) -> bool:
    db = get_db()
    session = await db.get(ChatDesktopScreenSession, source)
    if (session is None or session.user_id != user_id or session.expires_at <= _now()
            or not await web_session_active(user_id, session.web_family)):
        return False
    row = await db.scalar(select(ChatDesktopScreenRequest).where(
        ChatDesktopScreenRequest.session_id == source, ChatDesktopScreenRequest.id == identifier,
        ChatDesktopScreenRequest.claimed_at.is_not(None), ChatDesktopScreenRequest.expires_at > _now(),
    ).with_for_update())
    if row is None or not await has_chat_room_access(user_id, row.room_id):
        return False
    if row.outcome is None:
        row.outcome = "approved" if content is not None else "declined"
        if content is not None:
            row.image_ciphertext = encrypt_value(base64.b64encode(content).decode("ascii"))
    await db.commit()
    return True


async def eligible_tab(turn: ConversationTurn) -> ChatDesktopScreenSession | None:
    requester = turn.messaging_context.get("requester_user_id")
    if (turn.desktop_screen_session is None or type(requester) is not int or turn.origin != "text"
            or turn.direct_task_requested or turn.sender_is_ai or turn.messaging_context.get("platform") != "internal"):
        return None
    row = await get_db().get(ChatDesktopScreenSession, turn.desktop_screen_session, populate_existing=True)
    if (row is None or row.user_id != requester or row.expires_at <= _now()
            or not await web_session_active(row.user_id, row.web_family)):
        return None
    return row if await has_chat_room_access(row.user_id, turn.room_id) else None


async def request_screen(turn: ConversationTurn, reason: str) -> bytes:
    db = get_db()
    if turn.assert_fresh_before_effect is None or not await turn.assert_fresh_before_effect():
        raise ScreenUnavailable("The Chat turn is no longer current.")
    source = await eligible_tab(turn)
    if source is None:
        raise ScreenUnavailable("The original desktop tab is disconnected.")
    room = await get_internal_room(source.user_id, turn.room_id)
    if room is None or room.agent_id != turn.agent_id or not room.agent_active:
        raise ScreenUnavailable("The Chat room is unavailable.")
    request = ChatDesktopScreenRequest(
        session_id=source.id, round_id=turn.round_id, room_id=turn.room_id,
        agent_label=room.agent_name[:255], reason=reason[:400],
        expires_at=_now() + CAPTURE_LIFETIME,
    )
    db.add(request)
    await db.commit()
    try:
        while _now() < request.expires_at:
            if turn.should_interrupt is not None and await turn.should_interrupt():
                raise ScreenUnavailable("The Chat turn ended or received a newer message.")
            if await eligible_tab(turn) is None:
                raise ScreenUnavailable("The original desktop tab disconnected.")
            row = await db.get(ChatDesktopScreenRequest, request.id, populate_existing=True)
            await db.commit()
            if row is None or row.outcome == "declined":
                raise ScreenUnavailable("The desktop did not authorize a screenshot.")
            if row.image_ciphertext is not None:
                if not await turn.assert_fresh_before_effect():
                    raise ScreenUnavailable("The Chat turn is no longer current.")
                return base64.b64decode(decrypt_value(row.image_ciphertext), validate=True)
            await asyncio.sleep(0.5)
        raise ScreenUnavailable("The screenshot request expired.")
    finally:
        with anyio.CancelScope(shield=True):
            await db.execute(delete(ChatDesktopScreenRequest).where(ChatDesktopScreenRequest.id == request.id))
            await db.commit()


async def prune_screen_requests() -> None:
    db = get_db()
    await db.execute(delete(ChatDesktopScreenSession).where(ChatDesktopScreenSession.expires_at <= _now()))
    await db.execute(delete(ChatDesktopScreenRequest).where(ChatDesktopScreenRequest.expires_at <= _now()))
    await db.commit()
