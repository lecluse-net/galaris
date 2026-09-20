"""Matrix implementation of Galaris real-time call-provider resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.voice.interface import CallProvider, CallTransport

if TYPE_CHECKING:
    from app.connection.models import Connection


async def _connection_sees_room(connection_id: int, room_id: str) -> bool:
    from .client import Matrix

    matrix = await Matrix.from_connection_id(connection_id)
    try:
        members = await matrix.joined_members(room_id)
        return matrix.user_id in members and not await matrix.room_is_encrypted(room_id)
    finally:
        await matrix.aclose()


class MatrixVoiceProvider(CallProvider):
    """Resolve Matrix accounts and create classic VoIP v1 transports."""

    kind = "matrix"

    async def resolve_connection_id(
        self,
        *,
        agent_id: int,
        room_id: str,
        connection_id: int | None = None,
        language: str = "en",
    ) -> int:
        del language
        from app.connection import connection_service
        from app.messenger import kind_for_tool
        from app.tools import tool_service
        if connection_id is not None:
            connection = await connection_service.get_connection(connection_id)
            if connection is None or connection.agent_id != agent_id:
                raise ValueError("The Matrix connection does not belong to this agent")
            if not connection.active:
                raise ValueError("The Matrix connection is inactive")
            tool = await tool_service.get_tool_by_id(connection.tool_id)
            if (
                tool is None
                or kind_for_tool(tool) != self.kind
            ):
                raise ValueError("The selected connection is not a messaging connection")
            if not room_id or await _connection_sees_room(connection_id, room_id):
                return connection_id
            raise ValueError("The selected Matrix connection cannot access this room")

        candidates: list[Connection] = []
        for candidate in await connection_service.get_connections_by_agent(agent_id):
            if not candidate.active:
                continue
            tool = await tool_service.get_tool_by_id(candidate.tool_id)
            if (
                tool is not None
                and kind_for_tool(tool) == self.kind
            ):
                candidates.append(candidate)
        for candidate in candidates:
            try:
                if not room_id or await _connection_sees_room(int(candidate.id), room_id):
                    return int(candidate.id)
            except Exception:
                logger.opt(exception=True).debug(
                    "Matrix voice room validation failed connection={}", candidate.id
                )
        raise ValueError("No active Matrix connection can access this room")

    async def create_transport(
        self,
        connection_id: int,
        *,
        outgoing: bool,
    ) -> CallTransport:
        from .call import MatrixCall

        return await MatrixCall.from_connection_id(
            connection_id,
            outgoing=outgoing,
        )

    async def start_listeners(self) -> None:
        from .voice_listener import start_matrix_voice_listeners

        await start_matrix_voice_listeners()

    async def stop_listeners(self) -> None:
        from .voice_listener import stop_matrix_voice_listeners

        await stop_matrix_voice_listeners()

    def listeners_running(self) -> bool:
        from .voice_listener import voice_listeners_running

        return voice_listeners_running()


MATRIX_VOICE_PROVIDER = MatrixVoiceProvider()
