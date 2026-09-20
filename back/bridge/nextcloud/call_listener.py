"""Auto-answer incoming Nextcloud Talk calls with Galaris voice agents."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import aliased

from core.params import runtime_settings
from core.database import get_db_session
from core.util import as_dict, as_list

from app.connection.models import Connection
from app.agent.models import Agent
from app.messenger import messaging_tool_records
from app.tools import tool_service
from app.voice.call_manager import voice_call_manager


_DISCOVERY_ERROR_BACKOFF = 30.0
_START_RETRY_COOLDOWN = 10.0
_ROOM_ERROR_LOG_INTERVAL = 60.0


@dataclass(slots=True)
class _TalkAutoAnswerContext:
    connection_id: int
    agent_id: int
    self_id: str
    client: Any
    hpb_url: str = ""
    room_tokens: set[str] = field(default_factory=lambda: set())
    room_retry_after: dict[str, float] = field(default_factory=lambda: {})
    room_error_logged_at: dict[str, float] = field(default_factory=lambda: {})
    signaling_clients: dict[str, Any] = field(default_factory=lambda: {})
    signaling_tasks: dict[str, asyncio.Task[None]] = field(default_factory=lambda: {})


_listener_tasks: dict[int, asyncio.Task[None]] = {}
_listener_self_ids: dict[int, str] = {}
_listener_signatures: dict[int, tuple[tuple[str, str], ...]] = {}
_listener_supervisor: asyncio.Task[None] | None = None
_LISTENER_RECONCILE_INTERVAL = 2.0
_suppressed_remote_calls: dict[tuple[int, str], frozenset[str]] = {}


def suppress_auto_answer(
    connection_id: int,
    room_id: str,
    remote_actor_ids: set[str] | frozenset[str],
) -> None:
    """Do not rejoin a Talk call that this agent deliberately left.

    Talk calls belong to the room rather than to one peer. Leaving removes only
    the agent, so the auto-answer listener can otherwise interpret the caller
    who remains in the room as a fresh incoming call.
    """

    normalized_room_id = room_id.strip()
    if connection_id <= 0 or not normalized_room_id:
        return
    key = (connection_id, normalized_room_id)
    _suppressed_remote_calls[key] = frozenset(remote_actor_ids)
    logger.info(
        "Voice auto-answer: suppressing rejoin after local hangup "
        "connection={} room={} remotes={}",
        connection_id,
        normalized_room_id,
        sorted(remote_actor_ids),
    )


def _same_remote_call_is_suppressed(
    context: _TalkAutoAnswerContext,
    room_id: str,
    remote_actor_ids: set[str],
) -> bool:
    """Keep suppression until the same remote participants leave the call."""

    key = (context.connection_id, room_id)
    suppressed_actor_ids = _suppressed_remote_calls.get(key)
    if suppressed_actor_ids is None:
        return False
    if remote_actor_ids and (
        not suppressed_actor_ids
        or not suppressed_actor_ids.isdisjoint(remote_actor_ids)
    ):
        return True
    _suppressed_remote_calls.pop(key, None)
    logger.info(
        "Voice auto-answer: previous remote call ended; re-enabling answers "
        "connection={} room={}",
        context.connection_id,
        room_id,
    )
    return False


def _call_is_inactive_error(exc: Exception) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code == 404
    )


def _configuration_signature() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (name, str(value))
            for name, value in runtime_settings.model_dump().items()
            if name.startswith("VOICE_")
            or name.startswith("MESSENGER_NEXTCLOUD_TALK_")
        )
    )


async def start_voice_call_listeners() -> None:
    """Start the supervisor that follows active Messenger + Voice connections."""
    global _listener_supervisor

    if _listener_supervisor is not None and not _listener_supervisor.done():
        return

    try:
        await _reconcile_voice_call_listeners()
    except Exception:
        logger.exception("Voice auto-answer: initial reconciliation failed")
    _listener_supervisor = asyncio.create_task(
        _supervise_voice_call_listeners(), name="voice_listener_supervisor"
    )


def voice_listeners_running() -> bool:
    """Return whether the Talk voice reconciliation loop is alive."""
    return _listener_supervisor is not None and not _listener_supervisor.done()


async def stop_voice_call_listeners() -> None:
    global _listener_supervisor

    if _listener_supervisor is not None:
        _listener_supervisor.cancel()
        await asyncio.gather(_listener_supervisor, return_exceptions=True)
        _listener_supervisor = None
    for task in _listener_tasks.values():
        task.cancel()
    if _listener_tasks:
        await asyncio.gather(*_listener_tasks.values(), return_exceptions=True)
    _listener_tasks.clear()
    _listener_self_ids.clear()
    _listener_signatures.clear()
    _suppressed_remote_calls.clear()


async def _reconcile_voice_call_listeners() -> None:
    discovered = dict(await _discover_voice_capable_talk_connections())
    signature = _configuration_signature()

    for connection_id, task in list(_listener_tasks.items()):
        if (
            connection_id in discovered
            and not task.done()
            and _listener_signatures.get(connection_id) == signature
        ):
            continue
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        _listener_tasks.pop(connection_id, None)
        _listener_signatures.pop(connection_id, None)
        if connection_id not in discovered:
            logger.info("Voice auto-answer stopped connection={}", connection_id)

    for connection_id in sorted(set(discovered) - set(_listener_tasks)):
        agent_id = discovered[connection_id]
        _listener_tasks[connection_id] = asyncio.create_task(
            _run_connection_listener(connection_id, agent_id),
            name=f"voice_auto_answer_{connection_id}",
        )
        _listener_signatures[connection_id] = signature
        logger.info(
            "Voice auto-answer started connection={} agent={}",
            connection_id,
            agent_id,
        )


async def _supervise_voice_call_listeners() -> None:
    while True:
        try:
            await asyncio.sleep(_LISTENER_RECONCILE_INTERVAL)
            await _reconcile_voice_call_listeners()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice auto-answer: reconciliation failed")


async def _discover_voice_capable_talk_connections() -> list[tuple[int, int]]:
    if (
        not runtime_settings.VOICE_ENABLED
        or not runtime_settings.VOICE_AUTO_ANSWER_ENABLED
    ):
        return []
    from app.agent import list_driver_specs

    voice_driver_codes = tuple(
        spec.code for spec in list_driver_specs() if spec.tool_profile.voice_calling
    )
    if not voice_driver_codes:
        return []
    async with get_db_session() as db:
        records = await messaging_tool_records("nextcloud_talk")
        tool_ids = [int(record.id) for record in records]
        if not tool_ids:
            return []

        voice_tool = await tool_service.get_tool_record("voice")
        if voice_tool is None:
            return []

        voice_connection = aliased(Connection)

        result = await db.execute(
            select(Connection.id, Connection.agent_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .join(
                voice_connection,
                voice_connection.agent_id == Connection.agent_id,
            )
            .where(
                Connection.tool_id.in_(tool_ids),
                Connection.active.is_(True),
                voice_connection.tool_id == voice_tool.id,
                voice_connection.active.is_(True),
                Agent.agent_driver.in_(voice_driver_codes),
            )
            .order_by(Connection.id)
        )
        return [(int(connection_id), int(agent_id)) for connection_id, agent_id in result.all()]


async def _run_connection_listener(connection_id: int, agent_id: int) -> None:
    context: _TalkAutoAnswerContext | None = None
    try:
        while True:
            if context is None:
                try:
                    context = await _build_context(connection_id, agent_id)
                    _listener_self_ids[connection_id] = context.self_id
                    logger.info(
                        "Voice auto-answer: Talk listener started connection={} agent={} self_id={}",
                        connection_id,
                        agent_id,
                        context.self_id,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Voice auto-answer: initialization failed connection={} agent={}",
                        connection_id,
                        agent_id,
                    )
                    await asyncio.sleep(_DISCOVERY_ERROR_BACKOFF)
                    continue

            try:
                await _listen_connection(context)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Voice auto-answer: listener stopped after error connection={}", connection_id)
                await _close_context(context)
                context = None
                await asyncio.sleep(_DISCOVERY_ERROR_BACKOFF)
    finally:
        _listener_self_ids.pop(connection_id, None)
        if context is not None:
            await _close_context(context)


async def _build_context(connection_id: int, agent_id: int) -> _TalkAutoAnswerContext:
    from .messenger import NextcloudTalkMessenger

    async with get_db_session():
        messenger = await NextcloudTalkMessenger.from_connection_id(connection_id)
        hpb_url = await messenger._resolve_hpb_url()  # pyright: ignore[reportPrivateUsage]
    return _TalkAutoAnswerContext(
        connection_id=connection_id,
        agent_id=agent_id,
        self_id=messenger.self_id,
        client=messenger.client,
        hpb_url=hpb_url,
    )


async def _listen_connection(context: _TalkAutoAnswerContext) -> None:
    next_discovery_at = 0.0
    while True:
        if not await _voice_listening_is_enabled(context):
            logger.info(
                "Voice auto-answer stopped connection={} agent={}: "
                "messaging or voice was disabled or removed",
                context.connection_id,
                context.agent_id,
            )
            return
        now = time.monotonic()
        if now >= next_discovery_at:
            await _refresh_rooms(context)
            if context.hpb_url:
                await _reconcile_signaling_rooms(context)
            next_discovery_at = now + float(runtime_settings.VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL)

        if not context.hpb_url:
            for room_id in sorted(context.room_tokens):
                await _maybe_answer_room(context, room_id)

        await asyncio.sleep(float(runtime_settings.VOICE_AUTO_ANSWER_POLL_INTERVAL))


async def _voice_listening_is_enabled(context: _TalkAutoAnswerContext) -> bool:
    """Revalidate both capabilities required to listen for Talk calls."""
    from app.connection import connection_service
    from app.messenger import resolve_messenger_configuration

    async with get_db_session():
        try:
            messenger = await resolve_messenger_configuration(
                context.connection_id,
                expected_service="nextcloud_talk",
            )
        except ValueError:
            return False
        if messenger.agent_id != context.agent_id:
            return False
        return await connection_service.has_active_tool_connection(
            context.agent_id,
            "voice",
        )


async def _refresh_rooms(context: _TalkAutoAnswerContext) -> None:
    rooms = await context.client.get_rooms()
    tokens = {str(room.get("token") or "") for room in rooms if room.get("token")}
    tokens.discard("")
    if tokens != context.room_tokens:
        logger.info(
            "Voice auto-answer: monitored rooms connection={} count={} rooms={}",
            context.connection_id,
            len(tokens),
            sorted(tokens),
        )
        context.room_tokens = tokens
        context.room_retry_after = {
            room_id: retry_after
            for room_id, retry_after in context.room_retry_after.items()
            if room_id in tokens
        }
        context.room_error_logged_at = {
            room_id: logged_at
            for room_id, logged_at in context.room_error_logged_at.items()
            if room_id in tokens
        }
        for key in tuple(_suppressed_remote_calls):
            connection_id, room_id = key
            if connection_id == context.connection_id and room_id not in tokens:
                _suppressed_remote_calls.pop(key, None)


async def _reconcile_signaling_rooms(context: _TalkAutoAnswerContext) -> None:
    from .signaling import TalkSignalingRoom

    async def _ignore_raw(_room_id: str, _raw: dict[str, Any]) -> None:
        return None

    for room_id in sorted(context.room_tokens - set(context.signaling_clients)):
        async def _on_event(token: str, event: dict[str, Any]) -> None:
            await _handle_signaling_event(context, token, event)

        sig = TalkSignalingRoom(
            hpb_url=context.hpb_url,
            client=context.client,
            room_token=room_id,
            self_id=context.self_id,
            nextcloud_url=context.client.base_url,
            on_raw=_ignore_raw,
            on_event=_on_event,
        )
        context.signaling_clients[room_id] = sig
        context.signaling_tasks[room_id] = asyncio.create_task(
            sig.start(),
            name=f"voice_auto_answer_sig_{context.connection_id}_{room_id}",
        )
        logger.info(
            "Voice auto-answer: signaling HPB surveille room={} connection={}",
            room_id,
            context.connection_id,
        )

    for room_id in sorted(set(context.signaling_clients) - context.room_tokens):
        sig = context.signaling_clients.pop(room_id)
        task = context.signaling_tasks.pop(room_id, None)
        await sig.stop()
        if task is not None:
            task.cancel()


async def _handle_signaling_event(
    context: _TalkAutoAnswerContext,
    room_id: str,
    event: dict[str, Any],
) -> None:
    key = (context.connection_id, room_id)
    if key in _suppressed_remote_calls:
        try:
            participants = await context.client.get_call_participants(room_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _call_is_inactive_error(exc):
                _same_remote_call_is_suppressed(context, room_id, set())
                return
            logger.debug(
                "Voice auto-answer: keeping local-hangup suppression while "
                "participants cannot be verified room={} connection={} error={}: {}",
                room_id,
                context.connection_id,
                type(exc).__name__,
                exc,
            )
            return
        current_remote_actor_ids = _remote_actor_ids(
            participants,
            context.self_id,
            ignored_actor_ids=set(_listener_self_ids.values()),
        )
        if _same_remote_call_is_suppressed(
            context,
            room_id,
            current_remote_actor_ids,
        ):
            return
        # The event that proved the previous call ended may be a partial or
        # stale signaling update. Wait for a subsequent event before answering.
        return

    remote_actor_ids = _remote_actor_ids_from_signaling_event(
        event,
        context.self_id,
        ignored_actor_ids=set(_listener_self_ids.values()),
    )
    if not remote_actor_ids:
        return

    now = time.monotonic()
    if context.room_retry_after.get(room_id, 0.0) > now:
        return
    if _has_active_call(context, room_id):
        return

    context.room_retry_after[room_id] = now + _START_RETRY_COOLDOWN
    logger.info(
        "Voice auto-answer: inbound call detected through signaling room={} connection={} remotes={}",
        room_id,
        context.connection_id,
        sorted(remote_actor_ids),
    )
    await _start_incoming_call(context, room_id, remote_actor_ids)


async def _maybe_answer_room(context: _TalkAutoAnswerContext, room_id: str) -> None:
    now = time.monotonic()
    if context.room_retry_after.get(room_id, 0.0) > now:
        return

    try:
        participants = await context.client.get_call_participants(room_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if _call_is_inactive_error(exc):
            _same_remote_call_is_suppressed(context, room_id, set())
        last_logged = context.room_error_logged_at.get(room_id, 0.0)
        if now - last_logged >= _ROOM_ERROR_LOG_INTERVAL:
            logger.debug(
                "Voice auto-answer: Call API inactive or unavailable room={} connection={} error={}: {}",
                room_id,
                context.connection_id,
                type(exc).__name__,
                exc,
            )
            context.room_error_logged_at[room_id] = now
        return

    remote_actor_ids = _remote_actor_ids(
        participants,
        context.self_id,
        ignored_actor_ids=set(_listener_self_ids.values()),
    )
    if _same_remote_call_is_suppressed(context, room_id, remote_actor_ids):
        return
    if not remote_actor_ids:
        return
    if _has_active_call(context, room_id):
        return

    context.room_retry_after[room_id] = now + _START_RETRY_COOLDOWN
    await _start_incoming_call(context, room_id, remote_actor_ids)


def _remote_actor_ids_from_signaling_event(
    event: dict[str, Any],
    self_id: str,
    *,
    ignored_actor_ids: set[str] | None = None,
) -> set[str]:
    if event.get("target") != "participants" or event.get("type") != "update":
        return set()

    ignored = ignored_actor_ids or set()
    remote_actor_ids: set[str] = set()
    updates_raw = event.get("update")
    updates = [as_dict(updates_raw)] if isinstance(updates_raw, dict) else as_list(updates_raw)

    for update_item in updates:
        update = as_dict(update_item)
        users_raw = update.get("users")
        users = [as_dict(users_raw)] if isinstance(users_raw, dict) else as_list(users_raw)
        for user_item in users:
            user = as_dict(user_item)
            if not _signaling_user_in_call(user):
                continue
            actor_id = str(
                user.get("userid")
                or user.get("userId")
                or user.get("actorId")
                or user.get("sessionId")
                or user.get("sessionid")
                or ""
            )
            if (
                not actor_id
                or actor_id == self_id
                or actor_id in ignored
            ):
                continue
            actor_type = str(user.get("actorType") or "")
            if actor_type == "bots":
                continue
            remote_actor_ids.add(actor_id)
    return remote_actor_ids


def _signaling_user_in_call(user: dict[str, Any]) -> bool:
    in_call = user.get("inCall")
    if isinstance(in_call, bool):
        active = in_call
    elif isinstance(in_call, int):
        active = in_call != 0
    elif isinstance(in_call, str):
        active = in_call.strip().lower() in {"1", "true", "yes", "on"}
    else:
        active = False

    flags = user.get("flags")
    if isinstance(flags, str) and flags.isdigit():
        flags = int(flags)
    if isinstance(flags, int):
        active = active or bool(flags & 1)
    return active


def _remote_actor_ids(
    participants: list[dict[str, Any]],
    self_id: str,
    *,
    ignored_actor_ids: set[str] | None = None,
) -> set[str]:
    ignored = ignored_actor_ids or set()
    actors: set[str] = set()
    for participant in participants:
        actor_id = str(participant.get("actorId") or participant.get("userId") or "")
        if (
            not actor_id
            or actor_id == self_id
            or actor_id in ignored
        ):
            continue
        actor_type = str(participant.get("actorType") or "")
        if actor_type == "bots":
            continue
        actors.add(actor_id)
    return actors


def _has_active_call(context: _TalkAutoAnswerContext, room_id: str) -> bool:
    return any(
        call.connection_id == context.connection_id and call.room_id == room_id
        for call in voice_call_manager.active_calls(agent_id=context.agent_id)
    )


async def _start_incoming_call(
    context: _TalkAutoAnswerContext,
    room_id: str,
    remote_actor_ids: set[str],
) -> None:
    from .voice_provider import NEXTCLOUD_TALK_VOICE_PROVIDER

    try:
        # Signaling callbacks run in their own long-lived task, outside the
        # request/CLI database context.  Transport construction resolves the
        # stored Talk and Nextcloud credentials, so give that short operation a
        # managed session.  Exit it before spawning the voice task to avoid
        # copying a soon-to-be-closed session through ContextVar inheritance.
        async with get_db_session():
            transport = await NEXTCLOUD_TALK_VOICE_PROVIDER.create_transport(
                context.connection_id,
                outgoing=False,
            )
        info, created = voice_call_manager.start_agent_call(
            agent_id=context.agent_id,
            connection_id=context.connection_id,
            room_id=room_id,
            transport=transport,
            remote_user_ids=tuple(sorted(remote_actor_ids)),
        )
        if created:
            logger.info(
                "Voice auto-answer: incoming call accepted call_id={} room={} remotes={}",
                info.call_id,
                room_id,
                sorted(remote_actor_ids),
            )
        else:
            logger.info("Voice auto-answer: call already active call_id={} room={}", info.call_id, room_id)
    except Exception:
        logger.exception(
            "Voice auto-answer: unable to answer call room={} connection={}",
            room_id,
            context.connection_id,
        )


async def _close_context(context: _TalkAutoAnswerContext) -> None:
    for sig in context.signaling_clients.values():
        try:
            await sig.stop()
        except Exception:
            logger.opt(exception=True).debug(
                "Voice auto-answer: signaling shutdown failed connection={}",
                context.connection_id,
            )
    for task in context.signaling_tasks.values():
        task.cancel()
    if context.signaling_tasks:
        await asyncio.gather(*context.signaling_tasks.values(), return_exceptions=True)
    context.signaling_clients.clear()
    context.signaling_tasks.clear()
    try:
        await context.client.aclose()
    except Exception:
        logger.opt(exception=True).debug(
            "Voice auto-answer: client close failed connection={}",
            context.connection_id,
        )
