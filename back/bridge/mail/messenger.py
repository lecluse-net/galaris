"""Polling adapter from IMAP inbox events to canonical Messenger admission."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, cast

from loguru import logger

from app.messenger import journal
from app.messenger._observations import (
    ObservedMessengerMessage,
    ObservedMessengerRoom,
    ObservedMessengerUser,
)
from app.messenger.inbound import dispatch_incoming
from app.messenger.interface import Messenger, NotSupported
from core.i18n import default_language, render_prompt, t

from .connection_service import resolve_connection
from .contracts import MailConnectionConfig, MailMessageRef, MailMessageSummary
from .imap_client import ImapClient

_KIND = "mail"
_POLL_LIMIT = 50
_ERROR_BACKOFF_MAX_SECONDS = 300.0


def _encode_cursor(uid_validity: int, uid: int) -> str:
    return json.dumps(
        {"v": 1, "uid_validity": uid_validity, "uid": uid},
        separators=(",", ":"),
    )


def _decode_cursor(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        decoded = cast(object, json.loads(value))
        if not isinstance(decoded, dict):
            raise ValueError
        payload = cast(dict[str, object], decoded)
        if payload.get("v") != 1:
            raise ValueError
        uid_validity = int(str(payload["uid_validity"]))
        uid = int(str(payload["uid"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if uid_validity <= 0 or uid < 0:
        return None
    return uid_validity, uid


def _objective(summary: MailMessageSummary) -> str:
    return render_prompt(
        t("messenger_incoming.mail_objective", default_language()),
        sender=summary.from_address or "—",
        subject=summary.subject or "—",
        message_ref=summary.ref,
    )


class MailMessenger(Messenger):
    """Poll one active Mail connection and admit every new INBOX UID as a Task."""

    kind = _KIND
    capabilities = set()
    provider_history = False

    def __init__(
        self,
        config: MailConnectionConfig,
        *,
        tool_id: int,
    ) -> None:
        self.config = config
        self.connection_id = config.connection_id
        self.tool_id = tool_id
        self.self_id = str(config.email_address)

    @classmethod
    async def from_connection_id(cls, connection_id: int) -> "MailMessenger":
        from app.messenger import resolve_messenger_configuration

        resolved = await resolve_messenger_configuration(
            connection_id,
            expected_service=_KIND,
        )
        return cls(
            await resolve_connection(connection_id),
            tool_id=resolved.tool_id,
        )

    async def check_connection(self) -> str:
        await asyncio.to_thread(ImapClient(self.config).status)
        return self.self_id

    async def send_to_room(
        self,
        room_id: str,
        text: str,
        reply_to: Optional[str] = None,
    ) -> ObservedMessengerMessage:
        del room_id, text, reply_to
        raise NotSupported("Mail task results are sent only through explicit mail_* tools")

    async def send_to_user(
        self,
        user_id: str,
        text: str,
    ) -> ObservedMessengerMessage:
        del user_id, text
        raise NotSupported("Mail task results are sent only through explicit mail_* tools")

    async def history(self, room_id: str, limit: int = 20) -> list[ObservedMessengerMessage]:
        del room_id, limit
        return []

    def _message(self, summary: MailMessageSummary) -> ObservedMessengerMessage:
        ref = MailMessageRef.decode(summary.ref)
        observed_at = summary.date or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        timestamp = int(observed_at.timestamp())
        return ObservedMessengerMessage(
            id=f"{ref.uid_validity}:{ref.uid}",
            platform=self.kind,
            tool_id=self.tool_id,
            sender=ObservedMessengerUser(
                id=summary.from_address or "unknown-sender",
                display_name=summary.from_name or summary.from_address,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            recipient=ObservedMessengerUser(
                id=self.self_id,
                display_name=self.self_id,
                is_ai=True,
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            room=ObservedMessengerRoom(
                id=summary.ref,
                label=summary.subject or summary.from_address or "Mail",
                kind="direct",
                connection_id=self.connection_id,
                tool_id=self.tool_id,
            ),
            text=_objective(summary),
            time=timestamp,
        )

    async def listen(self) -> None:
        raw_cursor = await journal.listener_cursor(self.connection_id)
        cursor = _decode_cursor(raw_cursor)
        backoff = 5.0
        logger.info(
            "Mail polling started connection={} interval_s={}",
            self.connection_id,
            self.config.poll_interval_s,
        )
        while True:
            try:
                after_uid = cursor[1] if cursor is not None else None
                batch = await asyncio.to_thread(
                    ImapClient(self.config).poll_inbox,
                    after_uid=after_uid,
                    limit=_POLL_LIMIT,
                )
                backoff = 5.0
                if cursor is None or cursor[0] != batch.uid_validity:
                    cursor = (batch.uid_validity, batch.latest_uid)
                    await journal.update_listener_state(
                        self.connection_id,
                        self.kind,
                        cursor=_encode_cursor(*cursor),
                        available=True,
                    )
                    logger.info(
                        "Mail polling baseline established connection={} uid_validity={} uid={}",
                        self.connection_id,
                        *cursor,
                    )
                else:
                    for summary in batch.messages:
                        ref = MailMessageRef.decode(summary.ref)
                        await dispatch_incoming(self._message(summary))
                        cursor = (ref.uid_validity, ref.uid)
                        await journal.update_listener_state(
                            self.connection_id,
                            self.kind,
                            cursor=_encode_cursor(*cursor),
                            available=True,
                            event_received=True,
                        )
                    if not batch.messages:
                        await journal.update_listener_state(
                            self.connection_id,
                            self.kind,
                            cursor=_encode_cursor(*cursor),
                            available=True,
                        )
                if not batch.truncated:
                    await asyncio.sleep(self.config.poll_interval_s)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await journal.update_listener_state(
                    self.connection_id,
                    self.kind,
                    cursor=_encode_cursor(*cursor) if cursor is not None else None,
                    available=False,
                    error=type(exc).__name__,
                    reconnect=True,
                )
                logger.warning(
                    "Mail polling failed connection={} retry_in={}s type={}",
                    self.connection_id,
                    backoff,
                    type(exc).__name__,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _ERROR_BACKOFF_MAX_SECONDS)


__all__ = ["MailMessenger"]
