"""Bridge-independent MCP messaging tools exposed to every agent driver.

The MCP gateway keeps no conversation state, so agents provide the room or recipient explicitly
with each call. ``MessagingContext`` carries the current room only for other runtime tools such as
voice calls.
"""

from __future__ import annotations

import contextvars
import difflib
import tempfile
from dataclasses import dataclass, field

from pathlib import Path
from typing import Any, List, Optional, cast
from uuid import UUID

from loguru import logger

from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool
from core.database import release_db_transaction
from core.i18n import default_language, is_supported, render_prompt, t
from .facade import MessengerFacade, normalize_kind
from .interface import NotSupported
from .models import Capability, File, Message
from .resource_reference import attachment_resource_uri


@dataclass
class MessagingContext:
    """Messaging context set by the executor for the current task."""

    messenger: Optional[MessengerFacade] = None
    room_id: Optional[str] = None
    connection_id: Optional[int] = None
    message_id: Optional[str] = None  # Triggering message used by reactions.
    attachments: List[File] = field(default_factory=lambda: [])
    agent_id: Optional[int] = None  # Current agent for non-messaging tools.
    language: str = ""  # Durable language of the current task.


def _task_language(task: Any | None) -> str:
    raw_data = getattr(task, "data", None) if task is not None else None
    data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
    raw = str(data.get("language") or "").strip().lower()
    return raw if is_supported(raw) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_mcp.{key}", language), **values)


async def _context_language(ctx: McpToolContext) -> str:
    return await context_language(ctx)


_ctx: contextvars.ContextVar[Optional[MessagingContext]] = contextvars.ContextVar(
    "agent_messaging_ctx", default=None
)


def set_context(ctx: MessagingContext) -> "contextvars.Token[Optional[MessagingContext]]":
    return _ctx.set(ctx)


def reset_context(token: "contextvars.Token[Optional[MessagingContext]]") -> None:
    _ctx.reset(token)


def current_context() -> Optional[MessagingContext]:
    """Return the current task messaging context, or ``None`` outside a conversation.

    Other modules use this public accessor without depending on the ContextVar implementation.
    """
    return _ctx.get()


async def _resolve_agent_messenger(
    agent_id: int,
    language: str,
    task_id: UUID | None = None,
) -> MessengerFacade:
    from .service import messenger_for_agent, messenger_for_agent_connection

    if task_id is not None:
        data = await _task_data(task_id)
        raw_connection_id = data.get("messenger_connection_id")
        if raw_connection_id is None:
            raw_connection_id = data.get("connection_id")
        expected_platform = str(
            data.get("goal_referrer_platform")
            or data.get("message_platform")
            or ""
        ).strip()
        expected_kind = expected_platform
        if expected_kind.startswith("voice:"):
            expected_kind = expected_kind.partition(":")[2]
        expected_kind = normalize_kind(expected_kind) or ""
        if raw_connection_id is not None:
            try:
                connection_id = int(raw_connection_id)
            except (TypeError, ValueError) as exc:
                raise NotSupported(t("messenger_mcp.no_messenger", language)) from exc
            if connection_id <= 0:
                raise NotSupported(t("messenger_mcp.no_messenger", language))
            try:
                messenger = await messenger_for_agent_connection(agent_id, connection_id)
            except (LookupError, ValueError) as exc:
                raise NotSupported(str(exc)) from exc
            if expected_kind and messenger.kind != expected_kind:
                raise NotSupported(
                    f"The selected Messenger connection no longer uses {expected_kind}."
                )
            return messenger
        if expected_kind:
            raise NotSupported(
                "This Task has a messaging channel but no exact connection; "
                "cross-channel fallback is disabled."
            )

    messenger = await messenger_for_agent(agent_id)
    if messenger is None:
        raise NotSupported(t("messenger_mcp.no_messenger", language))
    return messenger


async def _task_data(task_id: UUID) -> dict[str, Any]:
    from sqlalchemy import select

    from app.task import Task
    from core.database import get_db

    row = (
        await get_db().execute(
            select(
                Task.data,
                Task.messenger_connection_id,
                Task.message_platform,
            ).where(Task.id == task_id)
        )
    ).one_or_none()
    if row is None:
        return {}
    raw_data = cast(object, row[0])
    connection_id = cast(int | None, row[1])
    platform = cast(str | None, row[2])
    data: dict[str, Any] = (
        dict(cast(dict[str, Any], raw_data)) if isinstance(raw_data, dict) else {}
    )
    if connection_id is not None:
        data["messenger_connection_id"] = int(connection_id)
    if platform:
        data.setdefault("message_platform", str(platform))
    return data


async def _recent_agent_attachments(
    agent_id: int,
    room_id: str,
    language: str,
    task_id: UUID | None = None,
) -> dict[str, File]:
    if task_id is None:
        messenger = await _resolve_agent_messenger(agent_id, language)
    else:
        messenger = await _resolve_agent_messenger(agent_id, language, task_id)
    seen: dict[str, File] = {}
    for message in await messenger.history(room_id, 30):
        for attachment in message.files:
            key = str(attachment.id)
            if key and key not in seen:
                seen[key] = attachment
    return seen


def _attachment_history_payload(message: Message, attachment: File) -> dict[str, Any]:
    """Serialize one file as a canonical resource nested in its message."""

    if message.room is None:
        raise RuntimeError(
            f"Messenger attachment {attachment.id} has no canonical room."
        )
    return {
        "id": str(attachment.id),
        "uri": attachment_resource_uri(
            message.tool_code,
            message.room.external_id,
            attachment.id,
        ),
        "external_identifier": attachment.external_identifier,
        "name": attachment.name,
        "mime": attachment.mime_type,
        "size": attachment.size_bytes,
        "kind": attachment.kind,
    }


async def _resolve_context_messenger(
    ctx: McpToolContext, language: str
) -> MessengerFacade:
    """Resolve a Task-pinned messenger while preserving context-free tool calls."""

    if ctx.task_id is None:
        return await _resolve_agent_messenger(ctx.agent_id, language)
    return await _resolve_agent_messenger(ctx.agent_id, language, ctx.task_id)


async def _deliver_agent_file_with_status(
    ctx: McpToolContext,
    messenger: Any,
    room_id: str,
    filename: str,
    message: str,
    language: str | None = None,
) -> tuple[dict[str, object] | str, bool]:
    from app.file_share import (
        ResourceContext,
        deliver_resource_to_messenger,
    )

    lang = language if language and is_supported(language) else default_language()
    resource_ctx = ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        console_resource=ctx.resource("console"),
        language=lang,
    )
    try:
        delivered = await deliver_resource_to_messenger(
            resource_ctx,
            messenger,
            room_id,
            filename,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("send_file: could not transfer {} ({})", filename, exc)
        return _message(lang, "missing_file", path=filename), False
    if message:
        await messenger.send_to_room(room_id, message)
    # Delivery is copy-out. The Task tree may still need this exact provider source for later
    # iterations or a targeted delivery retry. Provider retention is independent from the
    # transport acknowledgement path.
    return {
        "message": _message(
            lang,
            "file_sent",
            name=delivered.name,
            size=delivered.size,
            uri=delivered.uri,
        ),
        "source_uri": delivered.source_uri,
        "uri": delivered.uri,
        "name": delivered.name,
        "size": delivered.size,
    }, True


@mcp_tool(
    "messenger",
    name="messenger_room_send_message",
    description="Send a Markdown message to a room or conversation.",
)
async def mcp_room_send_message(ctx: McpToolContext, room_id: str, message: str) -> str:
    """Send a Markdown message to a room or conversation."""
    from .reply_guard import note_reply, text_already_sent

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        connection_id = int(getattr(messenger, "connection_id", 0) or 0) or None
        # A Task may deliberately make the same explicit call more than once. Its
        # terminal fallback relies on the structured execution trace, not this
        # process-local guard. Preserve the historical guard outside Tasks.
        if ctx.task_id is None and text_already_sent(
            ctx.agent_id,
            room_id,
            message,
            task_id=ctx.task_id,
            connection_id=connection_id,
        ):
            return _message(language, "duplicate")
        await messenger.send_to_room(room_id, message)
        if ctx.task_id is None:
            note_reply(
                ctx.agent_id,
                room_id,
                message,
                connection_id=connection_id,
            )
        return _message(language, "message_sent")
    except NotSupported as exc:
        raise RuntimeError(_message(language, "unavailable", error=exc)) from exc
    except Exception as exc:
        logger.exception("MCP messenger_room_send_message failed")
        raise RuntimeError(_message(language, "send_failed", error=exc)) from exc


@mcp_tool(
    "messenger",
    name="messenger_send_message_to_user",
    description=(
        "Send a message to an exact provider user ID or a display name resolved by that provider. "
        "The current Task's exact messaging connection is used by default. Set channel "
        "(nextcloud_talk, telegram, matrix, whatsapp, or one_bot) to select another platform; "
        "an unavailable or ambiguous channel never falls back. Use messenger_search_users first "
        "when the recipient ID is unknown. Sending to another AI agent becomes a blocking peer "
        "request."
    ),
)
async def mcp_send_message_to_user(
    ctx: McpToolContext,
    user: str,
    message: str,
    channel: str = "",
) -> str:
    """Send a private message, blocking when the recipient is another AI agent.

    ``user`` may be an exact ID or a display name resolved to its closest match.
    """
    from core.params import runtime_settings
    from app.task import collab, task_service

    language = await _context_language(ctx)
    try:
        try:
            messenger, user_id = await _resolve_user_delivery(
                ctx,
                user,
                language,
                channel=channel,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        # A peer AI recipient with a known current task becomes a blocking collaboration
        # await. Regular recipients use a simple private message.
        peer_agent_id = await _recipient_agent_id(messenger, user_id)
        is_peer_ai = peer_agent_id is not None and peer_agent_id != ctx.agent_id
        if is_peer_ai and ctx.task_id is not None:
            parent = await task_service.get_by_id(ctx.task_id)
            if parent is not None:
                if task_service.is_held_by_user(parent):
                    # A human-held task cannot create coordination children.
                    return _message(_task_language(parent), "paused_peer")
                if collab.collab_rounds(parent) >= runtime_settings.TASK_ASK_AGENT_MAX_ROUNDS:
                    return _message(_task_language(parent), "round_limit")
                room = await messenger.ensure_direct_room(user_id)
                # Directory/room synchronization must be visible to the independent
                # outbound journal transaction before the provider accepts a message.
                await release_db_transaction()
                await messenger.send_to_room(room.id, message)
                await collab.dispatch_question(
                    parent=parent,
                    peer_user_id=user_id,
                    peer_display=user_id,
                    room_id=str(room.id),
                    platform=messenger.kind,
                    question=message,
                    connection_id=int(
                        getattr(messenger, "connection_id", 0) or 0
                    )
                    or None,
                )
                return _message(_task_language(parent), "peer_waiting")

        # Recipient search refreshes messenger_users in this tool's transaction.
        # The outbound journal uses another transaction and resolves those same
        # identities; keeping the search locks would block our own receipt.
        await release_db_transaction()
        await messenger.send_to_user(user_id, message)
        return _message(language, "message_sent")
    except NotSupported as exc:
        raise RuntimeError(_message(language, "unavailable", error=exc)) from exc
    except Exception as exc:
        logger.exception("MCP messenger_send_message_to_user failed")
        raise RuntimeError(_message(language, "send_failed", error=exc)) from exc


async def _resolve_recipient_id(
    messenger: MessengerFacade,
    user: str,
    language: str,
) -> str:
    """Resolve an opaque user ID or display name to a concrete recipient ID.

    Exact IDs take precedence, then the closest display name. When search is unsupported or empty,
    the value remains an opaque ID for the bridge to validate.
    """
    value = (user or "").strip()
    if not value:
        raise ValueError(t("messenger_mcp.recipient_missing", language))
    try:
        candidates = await messenger.search_users(value)
    except NotSupported:
        return value
    if not candidates:
        return value
    # Exact IDs always beat display-name similarity.
    for candidate in candidates:
        if value in {str(candidate.id), candidate.external_id}:
            return str(candidate.id)
    best = max(
        candidates,
        key=lambda candidate: difflib.SequenceMatcher(
            None,
            value.lower(),
            (candidate.display_name or candidate.external_id).lower(),
        ).ratio(),
    )
    return str(best.id)


async def _resolve_task_recipient_id(
    task_id: UUID | None,
    messenger: MessengerFacade,
    user: str,
    language: str,
) -> str:
    """Keep a Goal's selected human ID exact instead of fuzzy-matching it again."""

    value = (user or "").strip()
    if task_id is not None:
        data = await _task_data(task_id)
        pinned = str(data.get("goal_referrer_user_id") or "").strip()
        if pinned and value == pinned:
            return pinned
    return await _resolve_recipient_id(messenger, value, language)


async def _resolve_user_delivery(
    ctx: McpToolContext,
    user: str,
    language: str,
    *,
    channel: str = "",
    capability: Capability = Capability.SEND,
) -> tuple[MessengerFacade, str]:
    """Resolve one exact transport and one provider-native user identifier."""

    requested_channel = channel.strip()
    if requested_channel:
        from .service import messenger_for_agent_kind

        messenger = await messenger_for_agent_kind(ctx.agent_id, requested_channel)
    else:
        messenger = await _resolve_context_messenger(ctx, language)
    if not messenger.supports(capability):
        raise ValueError(
            f"Messaging connection {getattr(messenger, 'connection_id', '')} "
            f"does not support {capability.value}."
        )
    user_id = await _resolve_task_recipient_id(ctx.task_id, messenger, user, language)
    return messenger, user_id


async def _recipient_agent_id(
    messenger: MessengerFacade, user_id: str
) -> Optional[int]:
    """Return the recipient's agent ID when it represents an AI agent."""
    from . import directory

    tool_id = int(getattr(messenger, "tool_id", 0) or 0)
    if not tool_id:
        return None
    user = await directory.resolve_user(tool_id, user_id)
    return user.agent_id


async def _deliver_agent_audio(
    agent_id: int,
    messenger: MessengerFacade,
    room_id: str,
    message: str,
    *,
    voice: str = "",
    model: str = "",
    language: str = "",
    speed: float = 1.0,
    pitch: float = 0.0,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
) -> tuple[str, int, str]:
    """Generate and deliver one temporary audio message, returning provider metadata."""
    from app.llm import tts_service

    generated = await tts_service.generate_for_agent(
        agent_id,
        message,
        tts_service.TTSOptions(
            voice=voice,
            model=model,
            language=language,
            speed=speed,
            pitch=pitch,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
        ),
    )
    filename = "message-audio.mp3"
    with tempfile.TemporaryDirectory(prefix="galaris-tts-") as directory:
        path = Path(directory) / filename
        path.write_bytes(generated.content)
        if Capability.VOICE_NOTES in getattr(messenger, "capabilities", ()):
            await messenger.send_voice_note(room_id, path)
        else:
            await messenger.upload_file_path(room_id, path, filename)
    return generated.provider_name, len(generated.content), generated.voice


@mcp_tool(
    "messenger",
    name="messenger_send_audio_message",
    description=(
        "Generate an MP3 voice message with this agent's configured TTS and attach it to a "
        "conversation. The destination is the latest room in which user wrote to this agent; "
        "the Task does not need to carry a room ID. user accepts a canonical Messenger user "
        "ID, provider ID, contact ID, or display name. Set channel only to restrict that "
        "journal lookup to a specific platform. "
        "Common controls are voice, model, language, speed and pitch. Some provider bridges "
        "also support stability, similarity_boost, style and use_speaker_boost. Omitted values keep the "
        "configured voice and provider defaults. This tool requires a TTS on the agent."
    ),
)
async def mcp_send_audio_message(
    ctx: McpToolContext,
    user: str,
    message: str,
    channel: str = "",
    voice: str = "",
    model: str = "",
    language: str = "",
    speed: float = 1.0,
    pitch: float = 0.0,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
) -> dict[str, Any]:
    """Generate an MP3 from ``message`` and post it to the user's latest room."""
    from app.llm.tts_service import TTSNotConfigured
    from app.tools import RecoverableToolError

    tool_language = await _context_language(ctx)
    try:
        from .service import (
            messenger_for_agent_connection,
            messenger_for_agent_kind,
            recent_user_room,
        )

        requested_channel = channel.strip()
        selected_connection_id: int | None = None
        if requested_channel:
            selected = await messenger_for_agent_kind(
                ctx.agent_id, requested_channel
            )
            selected_connection_id = int(selected.connection_id)
        route = await recent_user_room(
            ctx.agent_id,
            user,
            connection_id=selected_connection_id,
        )
        if route is None:
            raise RecoverableToolError(
                _message(tool_language, "recent_room_missing", user=user)
            )
        messenger = await messenger_for_agent_connection(
            ctx.agent_id, route.connection_id
        )
        if not messenger.supports(Capability.FILES):
            raise RecoverableToolError(
                _message(
                    tool_language,
                    "unavailable",
                    error="the last room does not support file delivery",
                )
            )
        provider, size, effective_voice = await _deliver_agent_audio(
            ctx.agent_id,
            messenger,
            route.room_id,
            message,
            voice=voice,
            model=model,
            language=language,
            speed=speed,
            pitch=pitch,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
        )
        return {
            "message": _message(
                tool_language,
                "audio_sent",
                provider=provider,
                voice=effective_voice,
                size=size,
            ),
            "destination": route.room_id,
            "connection_id": route.connection_id,
            "provider": provider,
            "voice": effective_voice,
            "size": size,
        }
    except RecoverableToolError:
        raise
    except TTSNotConfigured as exc:
        raise RecoverableToolError(_message(tool_language, "tts_missing")) from exc
    except ValueError as exc:
        raise RecoverableToolError(str(exc)) from exc
    except NotSupported as exc:
        raise RecoverableToolError(
            _message(tool_language, "unavailable", error=exc)
        ) from exc
    except Exception as exc:
        logger.exception("MCP messenger_send_audio_message failed")
        raise RuntimeError(
            _message(tool_language, "audio_send_failed", error=exc)
        ) from exc


@mcp_tool(
    "messenger",
    name="messenger_list_rooms",
    description=(
        "List every room accessible through the current Task's exact messaging "
        "connection, with canonical and provider identifiers."
    ),
)
async def mcp_list_rooms(ctx: McpToolContext) -> dict[str, Any] | str:
    """Return rooms from the Task-pinned connection without cross-channel fallback."""

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        rooms = await messenger.rooms()
        channel = messenger.kind
    except NotSupported as exc:
        return _message(language, "unavailable", error=exc)
    except Exception as exc:
        logger.exception("MCP messenger_list_rooms failed")
        return _message(language, "generic_failed", error=exc)
    return {
        "channel": channel,
        "count": len(rooms),
        "rooms": [
            {
                "id": str(room.id),
                "external_id": room.external_id,
                "label": room.label,
                "kind": room.kind,
                "conversation_type": room.conversation_type,
            }
            for room in rooms
        ],
    }


@mcp_tool(
    "messenger",
    name="messenger_room_history",
    description=(
        "Return one newest-to-oldest page of room history. Pass next_cursor as cursor "
        "to retrieve the next older batch. Attachments remain nested in their message "
        "and expose a canonical URI whose scheme is the exact connected Tool code."
    ),
)
async def mcp_room_history(
    ctx: McpToolContext,
    room_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any] | str:
    """Return one cursor-paginated batch of room history."""

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        page = await messenger.history_page(
            room_id,
            limit,
            cursor,
        )
    except NotSupported as exc:
        return _message(language, "unavailable", error=exc)
    except Exception as exc:
        logger.exception("MCP messenger_room_history failed")
        return _message(language, "generic_failed", error=exc)
    room = next((message.room for message in page.messages if message.room), None)
    return {
        "room_id": str(room.id) if room is not None else None,
        "external_room_id": room.external_id if room is not None else None,
        "messages": [
            {
                "id": str(message.id),
                "external_id": message.remote_message_id,
                "platform": message.platform,
                "sender": {
                    "id": (
                        str(message.sender.id)
                        if message.sender is not None
                        else None
                    ),
                    "external_id": (
                        message.sender.external_id
                        if message.sender is not None
                        else None
                    ),
                    "display_name": (
                        message.sender.display_name if message.sender is not None else ""
                    ),
                },
                "text": message.text,
                "attachments": [
                    _attachment_history_payload(message, attachment)
                    for attachment in message.files
                ],
                "reply_to": message.reply_to,
                "time": int(message.created_at.timestamp()),
            }
            for message in page.messages
        ],
        "page": {
            "limit": limit,
            "count": len(page.messages),
            "has_more": page.has_more,
            "next_cursor": page.next_cursor,
        },
    }


@mcp_tool(
    "messenger",
    name="messenger_search_users",
    description=(
        "List or search users across every enabled messaging channel, with their exact "
        "user and messaging connection IDs."
    ),
)
async def mcp_search_users(ctx: McpToolContext, query: str = "") -> str:
    """List or search messaging users without collapsing channel identities."""

    language = await _context_language(ctx)
    try:
        from .service import search_agent_users

        users = await search_agent_users(ctx.agent_id, query)
    except Exception as exc:
        logger.exception("MCP messenger_search_users failed")
        return _message(language, "generic_failed", error=exc)
    user_lines = [
        (
            f"{user.display_name or user.external_id} (id: {user.id}; "
            f"external_id: {user.external_id}; connection_id: {connection_id}; "
            f"tool_id: {tool_id}; channel: {platform})"
        )
        for connection_id, tool_id, platform, user in users
    ]
    return "\n".join(user_lines) or _message(language, "no_users")


async def mcp_list_attachments(ctx: McpToolContext, room_id: str) -> str:
    """List attachments received in a room."""
    from . import describe

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        history = await messenger.history(room_id, 30)
    except NotSupported as exc:
        return _message(language, "unavailable", error=exc)
    except Exception as exc:
        logger.exception("MCP messenger_list_attachments failed")
        return _message(language, "generic_failed", error=exc)
    entries: list[str] = []
    seen: set[str] = set()
    for message in history:
        for attachment in message.files:
            key = str(attachment.id)
            if key in seen:
                continue
            seen.add(key)
            payload = _attachment_history_payload(message, attachment)
            entries.append(
                f"- {describe(attachment, language)} — {payload['uri']}"
            )
    if not entries:
        return _message(language, "no_attachments")
    return "\n".join(entries)


async def mcp_read_attachment(ctx: McpToolContext, room_id: str, attachment_id: str) -> str:
    """Read or extract text from an attachment."""
    from . import extract_text

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        atts = await _recent_agent_attachments(
            ctx.agent_id, room_id, language, ctx.task_id
        )
        att = atts.get(attachment_id) or next(
            (a for a in atts.values() if attachment_id in (a.id, a.name)),
            None,
        )
        if att is None:
            return _message(
                language, "attachment_missing", attachment=attachment_id
            )
        return await extract_text(messenger, att, language)
    except NotSupported as exc:
        return _message(language, "unavailable", error=exc)
    except Exception as exc:
        logger.exception("MCP messenger_read_attachment failed")
        return _message(language, "read_failed", error=exc)


@mcp_tool(
    "messenger",
    name="messenger_send_file_to_user",
    description=(
        "Send a file from any canonical resource URI to an exact provider user. Galaris "
        "transfers console://, HTTPS, Nextcloud, Mail, Messenger attachment, "
        "or other connected-provider sources transparently. The current Task's exact messaging "
        "connection is used by default; set channel to select another platform."
    ),
)
async def mcp_send_file_to_user(
    ctx: McpToolContext,
    user_id: str,
    resource_uri: str,
    message: str = "",
    channel: str = "",
) -> dict[str, object]:
    """Send a resource privately to a user and return its destination URI."""

    language = await _context_language(ctx)
    try:
        try:
            messenger, resolved_user_id = await _resolve_user_delivery(
                ctx,
                user_id,
                language,
                channel=channel,
                capability=Capability.FILES,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        room_id = str(
            (await messenger.ensure_direct_room(resolved_user_id)).id
        )
        result, delivered = await _deliver_agent_file_with_status(
            ctx,
            messenger,
            room_id,
            resource_uri,
            message,
            language,
        )
        if not delivered:
            raise RuntimeError(str(result))
        return cast(dict[str, object], result)
    except NotSupported as exc:
        raise RuntimeError(_message(language, "unavailable", error=exc)) from exc
    except Exception:
        logger.exception("MCP messenger_send_file_to_user failed")
        raise


@mcp_tool(
    "messenger",
    name="messenger_room_send_file",
    description=(
        "Attach a file from any canonical resource URI to a messaging room. Galaris resolves "
        "and transfers the source transparently through file_share."
    ),
)
async def mcp_room_send_file(
    ctx: McpToolContext,
    room_id: str,
    filename: str,
    message: str = "",
) -> dict[str, object]:
    """Attach a resource to a room and return its destination URI."""

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        result, delivered = await _deliver_agent_file_with_status(
            ctx,
            messenger,
            room_id,
            filename,
            message,
            language,
        )
        if not delivered:
            raise RuntimeError(str(result))
        return cast(dict[str, object], result)
    except NotSupported as exc:
        raise RuntimeError(_message(language, "unavailable", error=exc)) from exc
    except Exception:
        logger.exception("MCP messenger_room_send_file failed")
        raise


async def mcp_room_resend_attachment(
    ctx: McpToolContext,
    room_id: str,
    attachment_id: str,
    message: str = "",
) -> str:
    """Copy one existing room attachment back into the room without local regeneration."""

    from core.params import runtime_settings

    language = await _context_language(ctx)
    try:
        messenger = await _resolve_context_messenger(ctx, language)
        atts = await _recent_agent_attachments(
            ctx.agent_id, room_id, language, ctx.task_id
        )
        att = atts.get(attachment_id) or next(
            (item for item in atts.values() if attachment_id == str(item.id)),
            None,
        )
        if att is None:
            raise LookupError(
                _message(language, "attachment_missing", attachment=attachment_id)
            )
        if (
            att.size_bytes is not None
            and att.size_bytes > runtime_settings.messenger_content_max_bytes
        ):
            raise ValueError(
                _message(language, "attachment_too_large", size=att.size_bytes)
            )
        safe_name = Path((att.name or "attachment").replace("\\", "/")).name
        with tempfile.TemporaryDirectory(prefix="galaris-resend-") as temp_dir:
            path = Path(temp_dir) / safe_name
            size = await messenger.fetch_attachment_to_file(att, path)
            if size > runtime_settings.messenger_content_max_bytes:
                raise ValueError(
                    _message(language, "attachment_too_large", size=size)
                )
            await messenger.upload_file_path(room_id, path, safe_name)
        if message:
            await messenger.send_to_room(room_id, message)
        return _message(language, "file_resent", name=safe_name, size=size)
    except NotSupported as exc:
        raise RuntimeError(_message(language, "unavailable", error=exc)) from exc
    except Exception:
        logger.exception("MCP messenger_room_resend_attachment failed")
        raise
