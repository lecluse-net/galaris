"""Resolve a live MCP view from a canonical, Chat-visible message."""

from __future__ import annotations

from uuid import UUID

from app.conversation.facade import McpTable as McpTable, request_conversation_mcp_view
from app.messenger import get_chat_message, get_internal_room
from core.database import release_db_transaction
from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, Field, JsonValue, model_validator


class McpAppFilter(BaseModel):
    arguments: dict[str, JsonValue] = Field(max_length=16)

    @model_validator(mode="after")
    def _bounded_arguments(self) -> McpAppFilter:
        if len(self.model_dump_json().encode()) > 32_000:
            raise ValueError("The filter arguments exceed the request limit")
        return self


class McpAppDocument(BaseModel):
    html: str


async def read_mcp_app(
    user_id: int, room_id: UUID, message_id: UUID, presentation_id: UUID,
    *, arguments: dict[str, JsonValue] | None = None,
) -> str | McpTable:
    room = await get_internal_room(user_id, room_id)
    message = await get_chat_message(user_id, room_id, message_id) if room is not None and room.writable else None
    presentation = next((item for item in message.mcp_presentations if item.id == presentation_id), None) if message else None
    if room is None or presentation is None or not presentation.resource_uri:
        raise HTTPException(status_code=404)
    await release_db_transaction()
    try:
        return await request_conversation_mcp_view(
            presentation, agent_id=room.agent_id, user_id=user_id, room_id=room_id, arguments=arguments,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403) from exc
    except Exception as exc:
        logger.warning("MCP app request failed for presentation {} ({})", presentation_id, type(exc).__name__)
        raise HTTPException(status_code=502) from exc
