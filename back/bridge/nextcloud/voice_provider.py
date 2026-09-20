"""Nextcloud Talk implementation of the generic Galaris call provider."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from app.voice.interface import CallProvider, CallTransport
from core.i18n import default_language, is_supported, render_prompt, t

if TYPE_CHECKING:
    from app.connection.models import Connection


def _language(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if is_supported(normalized) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"voice.{key}", language), **values)


async def _connection_sees_room(connection_id: int, room_id: str) -> bool:
    from .messenger import NextcloudTalkMessenger

    messenger = None
    try:
        messenger = await NextcloudTalkMessenger.from_connection_id(connection_id)
        rooms = await messenger.client.get_rooms()
        return any(str(room.get("token") or "") == room_id for room in rooms)
    finally:
        if messenger is not None:
            await messenger.client.aclose()


class NextcloudTalkVoiceProvider(CallProvider):
    """Resolve Talk accounts, create WebRTC transports, and auto-answer calls."""

    kind = "nextcloud_talk"

    async def resolve_connection_id(
        self,
        *,
        agent_id: int,
        room_id: str,
        connection_id: int | None = None,
        language: str = "en",
    ) -> int:
        from app.connection import connection_service
        from app.messenger import kind_for_tool
        from app.tools import tool_service

        lang = _language(language)
        if connection_id:
            connection = await connection_service.get_connection(connection_id)
            if connection is None:
                raise ValueError(
                    _message(lang, "connection_not_found", connection_id=connection_id)
                )
            if connection.agent_id != agent_id:
                raise ValueError(
                    _message(lang, "connection_wrong_agent", connection_id=connection_id)
                )
            if not connection.active:
                raise ValueError(
                    _message(lang, "connection_inactive", connection_id=connection_id)
                )
            tool = await tool_service.get_tool_by_id(connection.tool_id)
            if (
                not tool
                or kind_for_tool(tool) != self.kind
            ):
                raise ValueError(
                    _message(lang, "connection_not_talk", connection_id=connection_id)
                )
            try:
                if not room_id or await _connection_sees_room(int(connection.id), room_id):
                    return int(connection.id)
            except Exception as exc:
                logger.warning(
                    "Talk voice: exact connection={} could not be validated for room={} "
                    "({}: {})",
                    connection.id,
                    room_id,
                    type(exc).__name__,
                    exc,
                )
                raise ValueError(
                    _message(
                        lang,
                        "room_connection_missing",
                        agent_id=agent_id,
                        room_id=room_id,
                    )
                ) from exc
            raise ValueError(
                _message(
                    lang,
                    "room_connection_missing",
                    agent_id=agent_id,
                    room_id=room_id,
                )
            )

        connections = await connection_service.get_connections_by_agent(agent_id)
        candidates: list[Connection] = []
        for candidate in connections:
            if not candidate.active:
                continue
            tool = await tool_service.get_tool_by_id(candidate.tool_id)
            if (
                tool
                and kind_for_tool(tool) == self.kind
            ):
                candidates.append(candidate)

        if room_id:
            for candidate in candidates:
                try:
                    if not await _connection_sees_room(int(candidate.id), room_id):
                        continue
                    logger.info(
                        "Talk voice: resolved account by room access agent={} "
                        "connection={} room={}",
                        agent_id,
                        candidate.id,
                        room_id,
                    )
                    return int(candidate.id)
                except Exception as exc:
                    logger.debug(
                        "Talk voice: connection={} cannot see room={} ({}: {})",
                        candidate.id,
                        room_id,
                        type(exc).__name__,
                        exc,
                    )
            raise ValueError(
                _message(
                    lang,
                    "room_connection_missing",
                    agent_id=agent_id,
                    room_id=room_id,
                )
            )
        if candidates:
            return int(candidates[0].id)
        raise ValueError(_message(lang, "talk_connection_missing"))

    async def create_transport(
        self,
        connection_id: int,
        *,
        outgoing: bool,
    ) -> CallTransport:
        from .call import TalkCall

        return await TalkCall.from_connection_id(
            connection_id,
            start_call=outgoing,
            ring_attempts=3 if outgoing else 1,
            ring_interval_s=8.0,
        )

    async def start_listeners(self) -> None:
        from .call_listener import start_voice_call_listeners

        await start_voice_call_listeners()

    async def stop_listeners(self) -> None:
        from .call_listener import stop_voice_call_listeners

        await stop_voice_call_listeners()

    def listeners_running(self) -> bool:
        from .call_listener import voice_listeners_running

        return voice_listeners_running()


NEXTCLOUD_TALK_VOICE_PROVIDER = NextcloudTalkVoiceProvider()
