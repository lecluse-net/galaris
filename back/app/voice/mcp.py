"""Voice-call MCP and native tools exposed to agent drivers.

Room-explicit MCP functions support stateless runtimes such as Hermes. Native in-process tools
read the current room from ``MessagingContext``. Real-time media behavior remains in the voice
domain and transport bridges.
"""

from __future__ import annotations

from typing import Any, List
from uuid import UUID

from loguru import logger

from app.tools import require_galaris_admin_access
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.i18n import default_language, is_supported, render_prompt, t


async def _context_language(ctx: McpToolContext) -> str:
    turn = ctx.resource("conversation_turn")
    if turn is not None and getattr(turn, "agent_id", None) == ctx.agent_id:
        return _language(str(getattr(turn, "language", "") or ""))
    return await context_language(ctx)


def _language(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if is_supported(normalized) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"voice.{key}", language), **values)


def _turn_id(value: str) -> UUID:
    try:
        return UUID(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid voice conversation turn UUID: {value}") from exc


@mcp_tool(
    "galaris_admin",
    name="voice_turn_get",
    description=(
        "Return the complete persisted dataset for one voice conversation turn by exact UUID: "
        "turn and call-session state, agent identity, transcript, accumulated objective, "
        "assistant response, complete execution result, timing, lineage, and every correlated "
        "LLM call. Audio bytes are not persisted in the conversation-turn dataset."
    ),
)
async def voice_turn_get(
    ctx: McpToolContext,
    *,
    turn_id: str,
) -> dict[str, Any]:
    """Inspect one voice turn through the optional administration package."""

    from .inspection_service import inspect_turn

    identifier = _turn_id(turn_id)
    await require_galaris_admin_access(ctx.agent_id)
    payload = await inspect_turn(identifier)
    if payload is None:
        raise ValueError(f"Voice conversation turn not found: {identifier}")
    return payload


# Shared MCP and native orchestration.


async def _start_call(
    agent_id: int,
    room_id: str,
    connection_id: int = 0,
    language: str | None = None,
) -> str:
    """Start a voice call through the exact conversation connection when known."""
    from app.agent import agent_service
    from app.voice import voice_call_manager

    lang = _language(language)
    from core.params import runtime_settings

    if not runtime_settings.VOICE_ENABLED:
        return _message(lang, "disabled")

    room_id = (room_id or "").strip()
    if not room_id:
        return _message(lang, "room_required")

    try:
        agent = await agent_service.get(agent_id)
        if agent is None:
            return _message(lang, "agent_missing")
        provider = await _call_provider_for_connection(
            agent_id,
            connection_id or None,
            lang,
        )
        resolved_connection_id = await provider.resolve_connection_id(
            agent_id=agent_id,
            connection_id=connection_id or None,
            room_id=room_id,
            language=lang,
        )
        for active_call in voice_call_manager.active_calls(agent_id=agent_id):
            if (
                active_call.connection_id == resolved_connection_id
                and active_call.room_id == room_id
            ):
                return _message(
                    lang,
                    "already_active",
                    call_id=active_call.call_id,
                    room_id=active_call.room_id,
                )
        transport = await provider.create_transport(
            resolved_connection_id,
            outgoing=True,
        )

        info, created = voice_call_manager.start_agent_call(
            agent_id=agent_id,
            connection_id=resolved_connection_id,
            room_id=room_id,
            transport=transport,
            language=lang,
        )
        if not created:
            return _message(
                lang,
                "already_active",
                call_id=info.call_id,
                room_id=info.room_id,
            )
        return _message(
            lang,
            "started",
            call_id=info.call_id,
            room_id=info.room_id,
        )
    except Exception as exc:
        logger.exception("Voice start_voice_call failed")
        return _message(lang, "start_failed", error=exc)


async def _stop_call(
    agent_id: int,
    call_id: str = "",
    room_id: str = "",
    connection_id: int = 0,
    language: str | None = None,
) -> str:
    """Gracefully stop a voice call by ID, room, or agent."""
    from app.voice import voice_call_manager

    call_id = (call_id or "").strip()
    room_id = (room_id or "").strip()
    lang = _language(language)
    try:
        if call_id:
            stopped = await voice_call_manager.request_stop_call(call_id)
            return _message(lang, "stopped" if stopped else "call_missing")
        count = await voice_call_manager.request_stop_calls(
            agent_id=agent_id,
            room_id=room_id or None,
            connection_id=connection_id or None,
        )
        if count == 0:
            return _message(lang, "none_to_stop")
        return _message(lang, "stopped_count", count=count)
    except Exception as exc:
        logger.exception("Voice stop_voice_call failed")
        return _message(lang, "stop_failed", error=exc)


async def _call_provider_for_connection(
    agent_id: int,
    connection_id: int | None,
    language: str,
) -> Any:
    """Select a call provider from a server-owned connection, not a room ID."""

    from app.voice import get_call_provider
    from core.params import runtime_settings

    kind = runtime_settings.MESSENGER_DRIVER
    if connection_id is not None:
        from app.connection import connection_service
        from app.messenger import is_kind_enabled, kind_for_tool
        from app.tools import tool_service

        connection = await connection_service.get_connection(connection_id)
        if connection is None:
            raise ValueError(
                _message(language, "connection_not_found", connection_id=connection_id)
            )
        if int(connection.agent_id) != agent_id:
            raise ValueError(
                _message(
                    language,
                    "connection_wrong_agent",
                    connection_id=connection_id,
                )
            )
        if not connection.active:
            raise ValueError(
                _message(language, "connection_inactive", connection_id=connection_id)
            )
        tool = await tool_service.get_tool_by_id(int(connection.tool_id))
        tool_code = str(getattr(tool, "code", "") or "")
        resolved_kind = kind_for_tool(tool)
        if resolved_kind is None:
            raise ValueError(
                _message(language, "provider_missing", provider=tool_code or "messenger")
            )
        kind = resolved_kind
        if not is_kind_enabled(kind):
            raise ValueError(_message(language, "provider_missing", provider=kind))
    else:
        from app.messenger import is_kind_enabled

        if not is_kind_enabled(kind):
            raise ValueError(_message(language, "provider_missing", provider=kind))
    provider = get_call_provider(kind)
    if provider is None:
        raise ValueError(_message(language, "provider_missing", provider=kind))
    return provider


async def _task_connection_id(ctx: McpToolContext) -> int:
    """Read the task-pinned connection without exposing it as a model argument."""

    if ctx.task_id is None:
        return 0
    from app.task import task_service

    task = await task_service.get_by_id(ctx.task_id)
    if task is None or task.agent_id is None or int(task.agent_id) != ctx.agent_id:
        return 0
    return int(task.messenger_connection_id or 0)


def _conversation_call_scope(ctx: McpToolContext) -> tuple[str, int]:
    """Resolve the exact server-owned call scope for a conversation tool call."""

    from app.conversation import ConversationTurn

    turn = ctx.resource("conversation_turn")
    if not isinstance(turn, ConversationTurn) or turn.agent_id != ctx.agent_id:
        return "", 0
    # Active calls are keyed by the provider-facing room locator. The canonical
    # Messenger UUID remains useful for persistence and UI routing, but cannot
    # select a transport call (notably ``chat:direct:…`` for internal Chat).
    room_id = str(
        turn.messaging_context.get("room_locator")
        or turn.messaging_context.get("room_id")
        or ""
    ).strip()
    raw_connection_id = turn.messaging_context.get("connection_id")
    connection_id = (
        int(str(raw_connection_id))
        if raw_connection_id is not None and str(raw_connection_id).strip()
        else 0
    )
    return room_id, connection_id


async def _list_calls(agent_id: int, language: str | None = None) -> str:
    """List active voice calls for an agent."""
    from app.voice import voice_call_manager

    calls = voice_call_manager.active_calls(agent_id=agent_id)
    lang = _language(language)
    if not calls:
        return _message(lang, "none_active")
    return "\n".join(
        _message(
            lang,
            "call_line",
            call_id=call.call_id,
            room_id=call.room_id,
            transport_kind=call.transport_kind,
        )
        for call in calls
    )


@mcp_tool(
    "voice",
    name="voice_call_start",
    description="Start a voice call in the current room on its exact messaging connection.",
    requires=("voice_calling",),
)
async def mcp_start_voice_call(
    ctx: McpToolContext,
    room_id: str,
    connection_id: int = 0,
) -> str:
    """Start a voice call in a room."""
    pinned_connection_id = await _task_connection_id(ctx)
    return await _start_call(
        ctx.agent_id,
        room_id,
        pinned_connection_id or connection_id,
        await _context_language(ctx),
    )


@mcp_tool(
    "voice",
    name="voice_call_stop",
    description=(
        "End the current live audio call for real. Call this when the caller asks to "
        "hang up, end, or disconnect; do not merely say that the call ended."
    ),
    requires=("voice_calling",),
    conversation_policy="short",
)
async def mcp_stop_voice_call(
    ctx: McpToolContext,
    call_id: str = "",
    room_id: str = "",
) -> str:
    """Stop a voice call."""
    pinned_connection_id = await _task_connection_id(ctx)
    scoped_room_id, scoped_connection_id = _conversation_call_scope(ctx)
    # A live conversation owns its call target. Model-provided arguments can be
    # stale canonical UUIDs (or even identify another call), so they must never
    # override the exact transport scope attached to the server-side turn.
    conversation_scoped = bool(scoped_room_id)
    resolved_call_id = "" if conversation_scoped else call_id
    resolved_room_id = scoped_room_id if conversation_scoped else room_id.strip()
    resolved_connection_id = (
        scoped_connection_id if conversation_scoped else pinned_connection_id
    )
    return await _stop_call(
        ctx.agent_id,
        resolved_call_id,
        resolved_room_id,
        resolved_connection_id,
        await _context_language(ctx),
    )


@mcp_tool(
    "voice",
    name="voice_call_list",
    description="List active voice calls for this AI agent.",
    requires=("voice_calling",),
)
async def mcp_list_voice_calls(ctx: McpToolContext) -> str:
    """List active voice calls for this AI agent."""
    return await _list_calls(ctx.agent_id, await _context_language(ctx))


# Native in-process facade using the conversation context.


def _current_agent_room() -> tuple[int | None, str | None, int | None]:
    """Return the current conversation's agent, room, and exact connection."""
    from app.messenger import current_context

    ctx = current_context()
    if ctx is None:
        return None, None, None
    return ctx.agent_id, ctx.room_id, ctx.connection_id


def _current_context_language() -> str:
    from app.messenger import current_context

    ctx = current_context()
    return _language(ctx.language if ctx is not None else None)


async def start_voice_call() -> str:
    """Call the user through the current conversation platform."""
    agent_id, room_id, connection_id = _current_agent_room()
    language = _current_context_language()
    if agent_id is None or not room_id:
        return _message(language, "no_conversation_start")
    return await _start_call(
        agent_id,
        room_id,
        connection_id or 0,
        language,
    )


async def stop_voice_call(call_id: str = "") -> str:
    """Stop the current conversation's voice call or a precise call ID."""
    agent_id, room_id, connection_id = _current_agent_room()
    language = _current_context_language()
    if agent_id is None:
        return _message(language, "no_conversation_stop")
    return await _stop_call(
        agent_id,
        call_id,
        room_id or "",
        connection_id or 0,
        language,
    )


async def list_voice_calls() -> str:
    """List the current agent's active voice calls."""
    agent_id, _room_id, _connection_id = _current_agent_room()
    language = _current_context_language()
    if agent_id is None:
        return _message(language, "no_conversation")
    return await _list_calls(agent_id, language)


# Native tools exposed to in-process agents.
AGENT_VOICE_TOOLS: List[Any] = [
    start_voice_call,
    stop_voice_call,
    list_voice_calls,
]
