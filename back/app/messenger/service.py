"""Application-side messaging resolution, inbound handling, and listener lifecycle.

Canonical ``message_received`` events become tasks for the receiving agent. The injected
``AppMessengerResolver`` maps configured connections to concrete bridges, while listener
supervision manages pull-based bridge loops. Dependencies remain directed from app to core.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import select, update

from app.memory import MemoryItem
from core.database import get_db, get_db_session
from app.messenger import contact_memory, facade, ingest
from app.messenger.events import message_received
from app.messenger.interface import Messenger, NotSupported
from app.messenger.models import Message, MessengerUser, Room
from app.messenger.contracts import resolve_effective_topic_id
from core.i18n import default_language, render_prompt, t


INSTANT_MESSAGE_MAX_AGE = timedelta(hours=1)
_DREAM_ONLY_ADMISSION_REASON = "instant_message_older_than_one_hour"


@dataclass(frozen=True)
class RecentUserRoom:
    """Exact route of the latest inbound room observed for one human identity."""

    connection_id: int
    room_id: str
    user_id: UUID


@dataclass(frozen=True)
class _RecentUserRoomCandidate:
    connection_id: int
    room_id: str
    user_id: UUID
    contact_id: UUID | None
    external_id: str
    display_name: str


def _incoming_message(key: str, **values: Any) -> str:
    return render_prompt(
        t(f"messenger_incoming.{key}", default_language()), **values
    )


def _bridge_error(key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_bridge.errors.{key}"), **values)


def _normalize_bridge_kind(kind: str) -> str:
    return "one_bot" if kind in {"one_bot", "onebot"} else kind


def _bridge_kind_for_tool(tool: Any) -> Optional[str]:
    """Return the bridge kind for a messaging tool."""
    if tool is None:
        return None
    from core.params import runtime_settings

    return facade.kind_for_tool(
        tool,
        preferred_kind=runtime_settings.MESSENGER_DRIVER,
    )


async def _lock_inbound_message(message_id: UUID) -> None:
    """Serialize one business admission on its canonical journal row."""

    locked_message_id = await get_db().scalar(
        select(Message.id).where(Message.id == message_id).with_for_update()
    )
    if locked_message_id is None:
        raise RuntimeError("The inbound Messenger journal row disappeared during admission.")


async def messaging_tool_records(kind: str) -> list[Any]:
    """Return tool records whose connections own credentials for ``kind``."""
    from app.tools import tool_service
    from core.params import runtime_settings

    normalized_kind = _normalize_bridge_kind(kind)
    if not facade.is_kind_enabled(normalized_kind):
        return []
    return [
        record
        for record in await tool_service.get_all_tool_records()
        if facade.kind_for_tool(
            record,
            preferred_kind=runtime_settings.MESSENGER_DRIVER,
        )
        == normalized_kind
    ]


# Human-readable messaging driver labels used in incoming task labels.
_DRIVER_LABELS: dict[str, str] = {
    "nextcloud_talk": "Nextcloud Talk",
    "matrix": "Matrix",
    "one_bot": "OneBot",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "internal": _incoming_message("internal_harness"),
}


def _driver_label(kind: str) -> str:
    """Return the active bridge display name with a title-cased fallback."""
    return _DRIVER_LABELS.get(kind, kind.replace("_", " ").title())


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _message_excerpt(text: str, max_chars: int = 200) -> str:
    """Return a short, stable excerpt of received text."""
    return _truncate(re.sub(r"\s+", " ", text or "").strip(), max_chars)


def _incoming_sender_name(data: dict[str, Any]) -> str:
    return str(
        data.get("sender.nickname")
        or data.get("sender.display_name")
        or data.get("sender.user_id")
        or _incoming_message("unknown_sender")
    )


def _incoming_task_label(driver_label: str, data: dict[str, Any]) -> str:
    return _truncate(
        _incoming_message(
            "task_label", driver=driver_label, sender=_incoming_sender_name(data)
        ),
        400,
    )


# =============================================================================
# Resolver from application facade to bridge
# =============================================================================

class AppMessengerResolver:
    """Application implementation of the facade's ``MessengerResolver``."""

    async def messenger_for_connection(self, connection_id: int) -> Messenger:
        from app.connection import connection_service
        from app.tools import tool_service

        connection = await connection_service.get_connection(connection_id)
        if connection is None:
            raise ValueError(_bridge_error(
                "connection_not_found", connection_id=connection_id
            ))
        if not connection.active:
            raise ValueError(_bridge_error(
                "connection_inactive", connection_id=connection_id
            ))
        tool = await tool_service.get_tool_by_id(connection.tool_id)

        kind = _bridge_kind_for_tool(tool)
        if not kind:
            raise ValueError(_bridge_error(
                "tool_not_registered", tool_id=connection.tool_id
            ))
        if not facade.is_kind_enabled(kind):
            raise ValueError(f"Messaging bridge {kind} is disabled.")
        bridge = facade.get_factory(kind)
        if bridge is None:
            raise ValueError(_bridge_error("bridge_not_registered", kind=kind))
        messenger = await bridge.from_connection_id(connection_id)
        messenger.tool_code = str(getattr(tool, "code", ""))
        return messenger

    async def messenger_for(self, tool_id: int, self_id: str) -> Messenger:
        from app.connection import connection_service

        connections = await connection_service.get_connections_by_param(
            tool_id=tool_id, param_name="user_id", param_value=self_id
        )
        if not connections:
            raise ValueError(_bridge_error(
                "identity_connection_not_found", tool_id=tool_id, self_id=self_id
            ))
        return await self.messenger_for_connection(connections[0].id)

    async def default_messenger(self) -> Messenger:
        raise NotSupported(_bridge_error("default_not_configured"))


# =============================================================================
# Inbound subscriber: human conversation or AI collaboration Task
# =============================================================================

async def handle_incoming(message: Message) -> None:
    """Admit one canonical ``message_received`` event.

    Failures propagate to the durable inbound dispatcher so it can retain a retryable
    journal state. Background listeners and OneBot calls use an independent database session.
    """

    await admit_incoming(message)


def is_stale_instant_message(
    message: Message,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether an inbound instant message is too old for business admission.

    Mail owns an explicit Task admission policy and is intentionally exempt: an email remains
    actionable asynchronously. Every conversation-mode or legacy Messenger bridge is instant and
    therefore becomes journal/Dream-only after one hour.
    """

    if message.direction != "inbound":
        return False
    spec = facade.get_spec(message.platform)
    if spec is not None and spec.inbound_admission == "task":
        return False
    created_at = cast(datetime | None, message.created_at)
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return created_at < current - INSTANT_MESSAGE_MAX_AGE


async def _mark_stale_message_dream_only(message: Message, *, now: datetime) -> None:
    """Persist the terminal journal-only disposition of one historical instant message."""

    record = await get_db().scalar(
        select(Message).where(Message.id == message.id).with_for_update()
    )
    if record is None:
        raise RuntimeError(
            "The stale inbound Messenger journal row disappeared during admission."
        )
    created_at = record.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    admission = {
        "disposition": "dream_only",
        "reason": _DREAM_ONLY_ADMISSION_REASON,
        "decided_at": now.isoformat(),
        "age_seconds": max(0, int((now - created_at).total_seconds())),
    }
    record.status = "admitted"
    record.last_error = None
    record.metadata_ = {**(record.metadata_ or {}), "inbound_admission": admission}
    # Keep the detached event object coherent for any caller that inspects it after admission.
    message.status = record.status
    message.last_error = None
    message.metadata_ = dict(record.metadata_)


async def archive_stale_instant_message(message: Message) -> bool:
    """Apply the permanent journal/Dream-only policy before any business signal."""

    now = datetime.now(timezone.utc)
    if not is_stale_instant_message(message, now=now):
        return False
    async with get_db_session():
        await _mark_stale_message_dream_only(message, now=now)
    logger.info(
        "Historical inbound Messenger message archived for Dream without run: "
        "message={} platform={} created_at={}",
        message.id,
        message.platform,
        message.created_at,
    )
    return True


async def admit_incoming(message: Message) -> bool:
    """Admit one canonical message, or archive a stale instant message for Dream only.

    The boolean is false only when the permanent one-hour policy blocks Conversation and Task
    effects. Failures still propagate to durable listeners.
    """

    if await archive_stale_instant_message(message):
        return False
    async with get_db_session():
        await _process_incoming(message)
        return True


async def _process_incoming(message: Message) -> None:
    from app.tools import tool_service
    from app.connection import connection_service
    from app.agent import agent_service
    from app.task import TaskCreate, TaskMessage, TaskStatus, task_service
    from app.task import runner

    recipient = message.recipient
    if recipient is None or not message.tool_id:
        logger.warning("Ignoring incoming message without recipient or tool_id")
        return

    tool = await tool_service.get_tool_by_id(message.tool_id)
    if tool is None:
        logger.warning("Incoming message tool {} not found", message.tool_id)
        return

    connection = await connection_service.get_connection(message.connection_id)
    if connection is not None and (
        connection.tool_id != message.tool_id or not connection.active
    ):
        connection = None
    if connection is None:
        logger.warning(
            "No incoming-message connection or agent for messenger_user_id={}",
            recipient.id,
        )
        return

    agent = await agent_service.get(connection.agent_id)
    if agent is None:
        logger.warning("Incoming-message agent {} not found", connection.agent_id)
        return

    from .contact_access import require_contact_with_identity
    contact_sender = message.sender
    if contact_sender is None or not contact_sender.external_id:
        return
    try:
        await require_contact_with_identity(connection.agent_id, contact_sender)
    except PermissionError:
        logger.info("Incoming contact denied by team policy: agent={}", connection.agent_id)
        return

    connection_kind = _bridge_kind_for_tool(tool)
    declared_kind = _normalize_bridge_kind(message.platform) if message.platform else None
    if connection_kind and declared_kind and declared_kind != connection_kind:
        logger.warning(
            "Incoming message platform {} disagrees with connection {} ({})",
            declared_kind,
            connection.id,
            connection_kind,
        )
    # The server-owned connection is authoritative. A bridge payload cannot
    # relabel its transport and later redirect task output to another channel.
    actual_kind = connection_kind or declared_kind or str(tool.code)
    if not facade.is_kind_enabled(actual_kind):
        logger.info(
            "Ignoring incoming message for disabled bridge {} connection={}",
            actual_kind,
            connection.id,
        )
        return
    message.platform = actual_kind
    bridge_spec = facade.get_spec(actual_kind)
    # Human contact projection is private to the receiving agent and fail-open.
    contact_memory_item_id = await contact_memory.observe_incoming_contact(
        message,
        owner_agent_id=int(connection.agent_id),
        messaging_id=actual_kind,
    )
    if contact_memory_item_id is not None and message.id:
        try:
            async with get_db_session() as db:
                # The observer normally returns a durable Memory item. Recheck the
                # public identifier before writing the journal FK so a degraded or
                # mocked projection cannot prevent admission of the message.
                if await db.get(MemoryItem, contact_memory_item_id) is not None:
                    # Keep the hydrated canonical object coherent with the journal
                    # update. ``app.conversation`` consumes this same instance next.
                    message.contact_memory_item_id = contact_memory_item_id
                    await db.execute(
                        update(Message)
                        .where(
                            Message.id == message.id,
                        )
                        .values(contact_memory_item_id=contact_memory_item_id)
                    )
                    await db.commit()
        except Exception:
            logger.exception(
                "Failed to attach contact memory {} to inbound message {}",
                contact_memory_item_id,
                message.id,
            )

    from app.messenger import interactions
    from .events import message_admitting

    # Optional classification begins only after the contact and bridge checks.
    # Its receiver schedules independent work; admission never awaits a model.
    await message_admitting.send_async(message)

    resolved_choice = await interactions.resolve_from_message(
        message,
        agent_id=connection.agent_id,
    )
    if resolved_choice is not None:
        logger.info(
            "Incoming message consumed by messaging interaction {} ({})",
            resolved_choice.interaction_id,
            resolved_choice.kind,
        )
        return

    # Human dialogue belongs to the independent low-latency control plane. AI-to-AI
    # collaboration deliberately keeps the durable Task workflow below.
    if (
        not message.is_ai
        and (
            bridge_spec is None
            or bridge_spec.inbound_admission == "conversation"
        )
        and message.id
        and message.room is not None
        and message.room.id
    ):
        from app.conversation import admit_messenger_input

        try:
            await ingest.transcribe_audio_for_conversation(
                message,
                agent_id=int(connection.agent_id),
            )
        except Exception:
            logger.exception(
                "Automatic audio transcription failed open for Messenger message {}",
                message.id,
            )
        await admit_messenger_input(
            message,
            agent_id=int(connection.agent_id),
            connection_id=int(connection.id),
        )
        return

    room_id = str(message.room.id) if message.room else None

    # Fetch canonical room history through the bridge.
    history: List[Message] = []
    if room_id and (
        bridge_spec is None or bridge_spec.inbound_admission == "conversation"
    ):
        try:
            if message.platform in {"telegram", "whatsapp"}:
                # These push/poll APIs expose no arbitrary conversation history. The current
                # message was durably journalled before this handler ran, so avoid an unnecessary
                # remote credential validation on the latency-sensitive inbound path.
                from app.messenger import journal

                history = await journal.history(
                    connection.id,
                    message.room.external_id if message.room is not None else room_id,
                )
            else:
                messenger = await facade.get_messenger(connection.id)
                history = await messenger.history(room_id)
        except Exception:
            logger.exception("Could not retrieve room history for {}", room_id)

    # The dispatcher owns loop detection from timestamped history. This layer only records
    # whether the current sender is another AI.
    sender_is_ai = message.is_ai

    # Annotate an incoming turn when this agent already awaits that peer in the room. The
    # dispatcher remains the semantic arbiter, and peer task completion resolves the await.
    open_exchange_await_id: Optional[UUID] = None
    open_exchange_parent_id: Optional[UUID] = None
    if room_id and message.sender is not None:
        from app.task import collab

        open_exchange = await collab.open_exchange_await(
            agent_id=connection.agent_id,
            connection_id=int(connection.id),
            room_id=room_id,
            peer_user_id=str(message.sender.id),
        )
        if open_exchange is not None:
            open_exchange_await_id = open_exchange.id
            open_exchange_parent_id = open_exchange.parent_id

    # Relay a late peer answer during the grace window while still processing the message through
    # the normal dispatcher path.
    if (
        open_exchange_await_id is None
        and room_id
        and sender_is_ai
        and message.sender is not None
    ):
        from app.task import collab

        late_await = await collab.timed_out_await_for_late_reply(
            agent_id=connection.agent_id,
            connection_id=int(connection.id),
            room_id=room_id,
            peer_user_id=str(message.sender.id),
        )
        if late_await is not None:
            await collab.relay_late_answer(
                late_await,
                message.text,
                message.sender.display_name or message.sender.external_id,
            )

    # Stamp an incoming peer task with the await it resolves. Nesting it below awaited child S
    # preserves the requester's objective tree. Peer completion resolves S before parent resumption.
    resolves_await_id: Optional[str] = None
    await_anchor_id: Optional[UUID] = None
    source_anchor_id: Optional[UUID] = None
    if room_id and message.sender is not None and message.sender.agent_id is not None:
        from app.task import collab

        awaited = await collab.awaited_for_incoming(
            sender_agent_id=message.sender.agent_id,
            connection_id=int(connection.id),
            platform=actual_kind,
            room_id=room_id,
            recipient_user_id=str(recipient.id),
        )
        if awaited is not None:
            resolves_await_id = str(awaited.id)
            await_anchor_id = awaited.id
            source_anchor_id = awaited.id

    if resolves_await_id is None and open_exchange_await_id is not None:
        await_anchor_id = open_exchange_parent_id
        source_anchor_id = open_exchange_await_id

    # Keep canonical message data plus flat aliases required by legacy OneBot templates.
    sender = message.sender
    message_snapshot = TaskMessage.from_messenger(message)
    data: dict[str, Any] = message_snapshot.model_dump(mode="json")
    data.update({
        "text": message.text,
        "message": message.text,
        "raw_message": message.text,
        "message_id": str(message.id),
        "time": int(message.created_at.timestamp()),
        "group_id": room_id or "",
        "room_id": room_id or "",
        "message_type": (
            "group"
            if message.room is not None and message.room.kind == "group"
            else "private"
        ),
        "self_id": recipient.external_id,
        "connection_id": connection.id,
        "messenger_connection_id": connection.id,
        "user_id": str(sender.id) if sender else "",
        "sender_is_ai": sender_is_ai,
        "sender.id": str(sender.id) if sender else "",
        "sender.user_id": str(sender.id) if sender else "",
        "sender.nickname": sender.display_name if sender else "",
        "sender.display_name": sender.display_name if sender else "",
        "sender.agent_id": sender.agent_id if sender else None,
        "sender.connection_id": message.connection_id if sender else None,
        "recipient.agent_id": recipient.agent_id,
        "recipient.connection_id": message.connection_id,
        "message_excerpt": _message_excerpt(message.text),
    })
    # Stamp collaboration resolution. Auto-approval still stops at the agent boundary.
    if resolves_await_id is not None:
        from app.task import collab

        data[collab.RESOLVES_KEY] = resolves_await_id
    if open_exchange_await_id is not None:
        from app.task import collab

        data[collab.OPEN_EXCHANGE_KEY] = str(open_exchange_await_id)

    # Build localized task metadata using the active bridge display name.
    driver_label = _driver_label(actual_kind)

    label = _incoming_task_label(driver_label, data)
    # The message body becomes the task objective; executor context is reconstructed from data.
    objective = str(data.get("raw_message") or "").strip() or _incoming_message("no_text")

    task_create = TaskCreate(
        agent_id=connection.agent_id,
        label=label,
        messenger_connection_id=(
            int(connection.id)
            if bridge_spec is None or bridge_spec.deliver_task_result
            else None
        ),
        message_platform=(
            actual_kind
            if bridge_spec is None or bridge_spec.deliver_task_result
            else None
        ),
        message_group_id=(
            room_id
            if bridge_spec is None or bridge_spec.deliver_task_result
            else None
        ),
        data=data,
        objective=objective,
        topic_id=resolve_effective_topic_id(
            message.topic_id,
            topic_overridden=message.topic_overridden,
            room_topic_id=message.room.topic_id if message.room is not None else None,
        ),
        status=TaskStatus.CREATE,
        ai=sender_is_ai,
        cost=0.0,
        messages=(
            [TaskMessage.from_messenger(item) for item in history]
            if history
            else None
        ),
        parent_id=await_anchor_id,
        source_task_id=source_anchor_id,
    )
    # Serialize admission on the canonical journal row and persist the message UUID as a unique
    # Task key.  This closes both crash and multi-instance races: even when the process dies after
    # committing the Task but before setting Message.status="admitted", a redelivery finds the
    # already-created Task and cannot reproduce its effects.
    await _lock_inbound_message(message.id)
    new_task, created = await task_service.create_from_messenger(
        task_create,
        message.id,
    )
    if not created:
        logger.info(
            "Inbound Messenger message {} already admitted as Task {}",
            message.id,
            new_task.id,
        )
        return
    runner.go_next(new_task.id, fast=True)


# =============================================================================
# Resolve outgoing task messaging
# =============================================================================

async def resolve_task_messaging(
    task: Any,
) -> Tuple[Optional[facade.MessengerFacade], Optional[str]]:
    """Return ``(messenger, self_id)`` for a task room, or ``(None, None)``.

    Concrete bridges remain encapsulated behind the Messenger facade.
    """
    platform = getattr(task, "message_platform", None)
    if not platform or not task.agent_id:
        return None, None
    if not facade.is_kind_enabled(str(platform)):
        return None, None
    from app.tools import tool_service
    from app.connection import connection_service

    connection = None
    pinned_id: object | None = cast(
        object | None, getattr(task, "messenger_connection_id", None)
    )
    if pinned_id is None:
        raw_task_data: object = getattr(task, "data", None)
        if isinstance(raw_task_data, dict):
            task_data = cast(dict[str, Any], raw_task_data)
            pinned_id = task_data.get("messenger_connection_id") or task_data.get(
                "connection_id"
            )
    has_pinned_connection = pinned_id is not None
    try:
        pinned_int = int(pinned_id) if isinstance(pinned_id, (int, str)) else 0
    except ValueError:
        pinned_int = 0
    if has_pinned_connection:
        if pinned_int <= 0:
            logger.warning(
                "Task {} declares an invalid messaging connection {}",
                getattr(task, "id", ""),
                pinned_id,
            )
            return None, None
        candidate = await connection_service.get_connection(pinned_int)
        if (
            candidate is None
            or int(candidate.agent_id) != int(task.agent_id)
            or not candidate.active
        ):
            logger.warning(
                "Task {} cannot use pinned messaging connection {}",
                getattr(task, "id", ""),
                pinned_int,
            )
            return None, None
        connection = candidate
    else:
        candidates: list[Any] = []
        for candidate in await connection_service.get_connections_by_agent(
            int(task.agent_id)
        ):
            if not candidate.active:
                continue
            tool = await tool_service.get_tool_by_id(int(candidate.tool_id))
            if _bridge_kind_for_tool(tool) == str(platform):
                candidates.append(candidate)
        if len(candidates) != 1:
            return None, None
        connection = candidates[0]
    if connection is None:
        return None, None
    if not connection.active:
        return None, None
    self_id: Optional[str] = None
    try:
        _, params = await connection_service.get_params_as_dict(
            connection.id, decrypt_passwords=True
        )
        self_id = params.get("user_id")
    except Exception:
        self_id = None

    try:
        messenger = await facade.get_messenger(connection.id)
    except Exception:
        messenger = None
    if messenger is not None and messenger.kind != str(platform):
        logger.warning(
            "Task {} is pinned to connection {} ({}) but declares platform {}",
            getattr(task, "id", ""),
            connection.id,
            messenger.kind,
            platform,
        )
        return None, self_id
    return messenger, self_id


async def send_task_progress(agent_id: int, task_id: UUID, message: str) -> bool:
    """Send a non-terminal progress message without suppressing final task delivery."""
    from app.task import task_service

    text = message.strip()
    if not text:
        return False
    try:
        async with get_db_session():
            task = await task_service.get_by_id(task_id)
            if (
                task is None
                or task.agent_id != agent_id
                or not task.message_group_id
            ):
                return False
            messenger, _self_id = await resolve_task_messaging(task)
            if messenger is None:
                return False
            await messenger.send_to_room(task.message_group_id, text)
        return True
    except Exception:
        logger.exception("Could not send progress message for task {}", task_id)
        return False


async def messenger_for_agent(agent_id: int) -> Optional[facade.MessengerFacade]:
    """Return the sole active Messenger for an agent, or ``None`` when ambiguous."""
    from app.connection import connection_service
    from app.tools import tool_service

    candidates: list[Any] = []
    for conn in await connection_service.get_connections_by_agent(agent_id):
        if not getattr(conn, "active", True):
            continue
        tool = await tool_service.get_tool_by_id(conn.tool_id)
        kind = _bridge_kind_for_tool(tool)
        if kind and facade.is_kind_enabled(kind) and facade.get_factory(kind):
            candidates.append(conn)
    if len(candidates) != 1:
        return None
    try:
        return await facade.get_messenger(candidates[0].id)
    except Exception:
        logger.exception(
            "messenger_for_agent: failed to build messenger for connection {}",
            candidates[0].id,
        )
        return None


async def messenger_for_agent_connection(
    agent_id: int, connection_id: int
) -> facade.MessengerFacade:
    """Resolve one exact active messaging connection owned by ``agent_id``.

    Goal Tasks use this stricter resolver so a user selected on one platform is never
    reached through another arbitrary connection of the same agent.
    """
    from app.connection import connection_service
    from app.messenger.models import Capability
    from app.tools import tool_service

    connection = await connection_service.get_connection(connection_id)
    if connection is None or connection.agent_id != agent_id:
        raise ValueError(
            f"Messaging connection {connection_id} does not belong to agent {agent_id}."
        )
    if not connection.active:
        raise ValueError(f"Messaging connection {connection_id} is inactive.")
    tool = await tool_service.get_tool_by_id(connection.tool_id)
    kind = _bridge_kind_for_tool(tool)
    if kind is None or facade.get_factory(kind) is None:
        raise ValueError(f"Connection {connection_id} is not a messaging connection.")
    if not facade.is_kind_enabled(kind):
        raise ValueError(f"Messaging bridge {kind} is disabled.")
    messenger = await facade.get_messenger(connection_id)
    if not messenger.supports(Capability.SEND):
        raise ValueError(f"Messaging connection {connection_id} cannot send messages.")
    return messenger


async def messenger_for_agent_tool_code(
    agent_id: int,
    tool_code: str,
) -> facade.MessengerFacade:
    """Resolve the exact active Messenger capability carried by one Tool code."""

    from app.connection import connection_service
    from app.tools import tool_service

    candidates: list[Any] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool is not None and tool.code == tool_code and tool.messenger is not None:
            candidates.append(connection)
    if not candidates:
        raise ValueError(
            f"Agent {agent_id} has no active Messenger Tool {tool_code!r}."
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Agent {agent_id} has several active Messenger connections for "
            f"Tool {tool_code!r}."
        )
    return await messenger_for_agent_connection(agent_id, int(candidates[0].id))


async def messenger_room_locator_known(
    connection_id: int,
    room_locator: str,
) -> bool:
    """Return whether a provider room locator belongs to one exact connection."""

    from sqlalchemy import select

    from core.database import get_db

    normalized = room_locator.strip()
    if not normalized:
        return False
    return (
        await get_db().scalar(
            select(Room.id).where(
                Room.connection_id == connection_id,
                Room.external_id == normalized,
            )
        )
    ) is not None


async def messenger_for_agent_kind(
    agent_id: int, kind: str
) -> facade.MessengerFacade:
    """Resolve the agent's single active connection for an explicit channel kind."""

    from app.connection import connection_service
    from app.tools import tool_service

    requested = facade.normalize_kind(kind)
    if requested is None or not facade.is_kind_enabled(requested):
        raise ValueError(f"Messaging bridge {kind or '<empty>'} is unavailable.")
    candidates: list[Any] = []
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not getattr(connection, "active", True):
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if _bridge_kind_for_tool(tool) == requested:
            candidates.append(connection)
    if not candidates:
        raise ValueError(f"Agent {agent_id} has no active {requested} connection.")
    if len(candidates) > 1:
        raise ValueError(
            f"Agent {agent_id} has several active {requested} connections; "
            "an exact messaging connection is required."
        )
    return await messenger_for_agent_connection(agent_id, int(candidates[0].id))


async def recent_user_room(
    agent_id: int,
    user: str,
    *,
    connection_id: int | None = None,
) -> RecentUserRoom | None:
    """Return the last room in which ``user`` wrote to this agent.

    The canonical journal is authoritative: this does not require a provider directory
    or direct-room creation. ``user`` may be a canonical Messenger user UUID, a
    provider external ID, a contact-memory UUID, or a display name.
    """

    from sqlalchemy import func, or_, select

    from app.connection import Connection
    from core.database import get_db

    value = user.strip()
    if not value:
        return None
    query = (
        select(
            Message.connection_id,
            Message.room_id,
            Message.messenger_user_id,
            Message.contact_memory_item_id,
            MessengerUser.external_id,
            MessengerUser.display_name,
        )
        .join(Connection, Connection.id == Message.connection_id)
        .join(MessengerUser, MessengerUser.id == Message.messenger_user_id)
        .where(
            Connection.agent_id == agent_id,
            Connection.active.is_(True),
            Message.direction == "inbound",
            Message.room_id.is_not(None),
            Message.messenger_user_id.is_not(None),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
    )
    if connection_id is not None:
        query = query.where(Connection.id == connection_id)
    exact_conditions = [
        func.lower(MessengerUser.external_id) == value.lower(),
        func.lower(MessengerUser.display_name) == value.lower(),
    ]
    try:
        identity_id = UUID(value)
    except ValueError:
        identity_id = None
    if identity_id is not None:
        exact_conditions.extend(
            [
                Message.messenger_user_id == identity_id,
                Message.contact_memory_item_id == identity_id,
            ]
        )
    exact_row = (
        await get_db().execute(query.where(or_(*exact_conditions)).limit(1))
    ).first()
    rows = (
        [exact_row]
        if exact_row is not None
        else list((await get_db().execute(query.limit(1_000))).all())
    )
    candidates = [
        _RecentUserRoomCandidate(
            connection_id=int(row[0]),
            room_id=str(row[1]),
            user_id=cast(UUID, row[2]),
            contact_id=cast(UUID | None, row[3]),
            external_id=str(row[4] or ""),
            display_name=str(row[5] or ""),
        )
        for row in rows
    ]
    if not candidates:
        return None

    selected = candidates[0] if exact_row is not None else None
    if selected is None:
        folded = value.casefold()
        newest_by_user: dict[UUID, _RecentUserRoomCandidate] = {}
        for row in candidates:
            newest_by_user.setdefault(row.user_id, row)
        selected = max(
            newest_by_user.values(),
            key=lambda row: difflib.SequenceMatcher(
                None,
                folded,
                (row.display_name or row.external_id).casefold(),
            ).ratio(),
        )
        similarity = difflib.SequenceMatcher(
            None,
            folded,
            (selected.display_name or selected.external_id).casefold(),
        ).ratio()
        if similarity < 0.6:
            return None

    return RecentUserRoom(
        connection_id=int(selected.connection_id),
        room_id=str(selected.room_id),
        user_id=selected.user_id,
    )


async def search_agent_users(
    agent_id: int, query: str
) -> list[tuple[int, int, str, MessengerUser]]:
    """Search every enabled channel and return every known exact identity.

    Every active connection whose bridge exposes a native directory is queried. The Messenger
    facade persists each remote identity before this service receives its local projection.
    Results retain both the local identity and the exact messaging route. They are not merged
    cross-channel or promoted to Memory contacts by search alone.
    """
    from app.connection import connection_service
    from app.messenger.models import Capability
    from app.tools import tool_service

    value = query.strip()
    available: dict[int, tuple[Any, str]] = {}
    for connection in await connection_service.get_connections_by_agent(agent_id):
        if not connection.active:
            continue
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        kind = _bridge_kind_for_tool(tool)
        if (
            kind is None
            or not facade.is_kind_enabled(kind)
            or facade.get_factory(kind) is None
        ):
            continue
        available[int(connection.id)] = (connection, kind)

    matches: dict[tuple[int, UUID], tuple[int, int, str, MessengerUser]] = {}

    for connection_id, (connection, kind) in available.items():
        spec = facade.get_spec(kind)
        if spec is None or Capability.SEARCH_USERS not in spec.capabilities:
            continue
        messenger: facade.MessengerFacade | None = None
        try:
            messenger = await facade.get_messenger(connection.id)
            if not (
                messenger.supports(Capability.SEND)
                and messenger.supports(Capability.SEARCH_USERS)
            ):
                continue
            for user in await messenger.search_users(value):
                if user.external_id == messenger.self_id:
                    continue
                matches[(connection_id, user.id)] = (
                    connection_id,
                    int(connection.tool_id),
                    messenger.kind or kind,
                    user,
                )
        except Exception:
            logger.exception(
                "Messenger user search failed for messaging connection {}", connection.id
            )
        finally:
            if messenger is not None:
                try:
                    await messenger.close()
                except Exception:
                    logger.debug(
                        "Messenger user search cleanup failed for messaging connection {}",
                        connection.id,
                    )
    return sorted(
        matches.values(),
        key=lambda item: (
            (item[3].display_name or item[3].external_id).casefold(),
            item[2],
            item[0],
            str(item[3].id),
        ),
    )


# =============================================================================
# Pull-based bridge listener lifecycle
# =============================================================================

_listener_tasks: dict[int, "asyncio.Task[None]"] = {}
_listener_signatures: dict[int, str] = {}
_listener_retry_after: dict[int, float] = {}
_listener_supervisor: "asyncio.Task[None] | None" = None
_listeners_stopping = False
_LISTENER_RECONCILE_INTERVAL = 2.0
_LISTENER_RETRY_DELAY = 60.0


def _listener_configuration_signature() -> str:
    from core.params import runtime_settings

    values = sorted(
        (name, str(value))
        for name, value in runtime_settings.model_dump().items()
        if name.startswith("MESSENGER_")
    )
    return hashlib.sha256(repr(values).encode()).hexdigest()


async def _listener_configuration_signatures(
    connection_ids: set[int],
) -> dict[int, str]:
    """Hash each listener's Tool config and encrypted connection values."""

    from sqlalchemy import select

    from app.connection import Connection, ConnectionParam
    from app.tools import ToolModel as Tool

    if not connection_ids:
        return {}
    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(
                    Connection.id,
                    Tool.updated_at,
                    Tool.messenger_config,
                    ConnectionParam.param_name,
                    ConnectionParam.param_value,
                )
                .join(Tool, Tool.id == Connection.tool_id)
                .outerjoin(
                    ConnectionParam,
                    ConnectionParam.connection_id == Connection.id,
                )
                .where(Connection.id.in_(connection_ids))
                .order_by(Connection.id, ConnectionParam.param_name)
            )
        ).all()
    grouped: dict[int, list[object]] = {
        connection_id: [_listener_configuration_signature()]
        for connection_id in connection_ids
    }
    for connection_id, updated_at, messenger_config, param_name, param_value in rows:
        grouped[int(connection_id)].append(
            (
                updated_at.isoformat() if updated_at is not None else "",
                json.dumps(messenger_config or {}, sort_keys=True, default=str),
                str(param_name or ""),
                str(param_value or ""),
            )
        )
    return {
        connection_id: hashlib.sha256(
            repr(parts).encode()
        ).hexdigest()
        for connection_id, parts in grouped.items()
    }


async def check_configuration() -> dict[str, Any]:
    """Check credentials and reception state for every active provider connection."""
    from sqlalchemy import select

    from app.connection import Connection
    tool_kind_by_id: dict[int, str] = {}
    for kind in facade.enabled_kinds():
        for tool in await messaging_tool_records(kind):
            tool_kind_by_id.setdefault(int(tool.id), kind)
    tool_ids = list(tool_kind_by_id)
    if not tool_ids:
        return {"provider": "multi", "ok": False, "connections": []}

    from app.messenger.models import ListenerState
    from core.database import get_db

    records = (
        await get_db().execute(
            select(
                Connection.id,
                Connection.agent_id,
                Connection.tool_id,
                ListenerState.available,
                ListenerState.last_event_at,
            )
            .outerjoin(
                ListenerState,
                ListenerState.connection_id == Connection.id,
            )
            .where(
                Connection.tool_id.in_(tool_ids),
                Connection.active.is_(True),
            )
            .order_by(Connection.id)
        )
    ).all()

    results: list[dict[str, Any]] = []
    for connection_id, agent_id, tool_id, available, last_event_at in records:
        provider = tool_kind_by_id.get(int(tool_id), "messenger")
        messenger: facade.MessengerFacade | None = None
        try:
            messenger = await facade.get_messenger(int(connection_id))
            async with asyncio.timeout(20):
                detail = await messenger.check_connection()
            results.append(
                {
                    "connection_id": int(connection_id),
                    "agent_id": int(agent_id),
                    "provider": provider,
                    "ok": True,
                    "identity": messenger.self_id,
                    "detail": detail,
                    "receiving": available,
                    "last_received_at": last_event_at,
                }
            )
        except Exception as exc:
            logger.warning(
                "Messaging configuration check failed provider={} connection={}: {}",
                provider,
                connection_id,
                exc,
            )
            results.append(
                {
                    "connection_id": int(connection_id),
                    "agent_id": int(agent_id),
                    "provider": provider,
                    "ok": False,
                    "detail": str(exc),
                    "receiving": available,
                    "last_received_at": last_event_at,
                }
            )
        finally:
            if messenger is not None:
                try:
                    await messenger.close()
                except Exception:
                    logger.debug(
                        "Messaging configuration check cleanup failed connection={}",
                        connection_id,
                    )

    return {
        "provider": "multi",
        "ok": bool(results) and all(bool(item["ok"]) for item in results),
        "connections": results,
    }


async def start_listeners() -> None:
    """Start the supervisor that reconciles listeners with active connections."""
    global _listener_supervisor, _listeners_stopping

    if _listener_supervisor is not None and not _listener_supervisor.done():
        return

    _listeners_stopping = False
    try:
        await _reconcile_listeners()
    except Exception:
        logger.exception("Initial messaging listener reconciliation failed")
    _listener_supervisor = asyncio.create_task(
        _supervise_listeners(), name="messenger_listener_supervisor"
    )


def listeners_running() -> bool:
    """Return whether the canonical listener supervisor is alive."""
    return _listener_supervisor is not None and not _listener_supervisor.done()


async def _discover_active_listener_connections() -> set[int]:
    from sqlalchemy import select
    from app.connection import Connection
    async with get_db_session() as db:
        tool_ids: set[int] = set()
        for spec in facade.enabled_specs():
            if not set(spec.inbound_modes).intersection(
                {"polling", "sync", "signaling"}
            ):
                continue
            if facade.get_factory(spec.kind) is None:
                continue
            records = await messaging_tool_records(spec.kind)
            tool_ids.update(int(record.id) for record in records)
        if not tool_ids:
            return set()
        result = await db.execute(
            select(Connection.id).where(
                Connection.tool_id.in_(tool_ids), Connection.active.is_(True)
            )
        )
        return {int(cid) for cid in result.scalars().all()}


async def _reconcile_listeners() -> None:
    if _listeners_stopping:
        return

    active_ids = await _discover_active_listener_connections()
    if _listeners_stopping:
        return
    now = time.monotonic()
    signatures = await _listener_configuration_signatures(active_ids)

    for connection_id, task in list(_listener_tasks.items()):
        signature_changed = (
            _listener_signatures.get(connection_id)
            != signatures.get(connection_id)
        )
        if (
            connection_id in active_ids
            and not task.done()
            and not signature_changed
        ):
            continue
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        _listener_tasks.pop(connection_id, None)
        _listener_signatures.pop(connection_id, None)
        # Keep the cooldown recorded by a listener that failed with the same
        # configuration. Dropping it here caused invalid credentials to be
        # rebuilt and logged every reconciliation cycle (every two seconds).
        # A removed connection or an actual settings change may retry at once.
        if connection_id not in active_ids or signature_changed:
            _listener_retry_after.pop(connection_id, None)
        if connection_id not in active_ids:
            logger.info("Messaging listener stopped connection={}", connection_id)

    for connection_id in sorted(active_ids - set(_listener_tasks)):
        if _listener_retry_after.get(connection_id, 0.0) > now:
            continue
        _listener_tasks[connection_id] = asyncio.create_task(
            _run_listener(connection_id), name=f"messenger_listen_{connection_id}"
        )
        _listener_signatures[connection_id] = signatures[connection_id]
        logger.info("Messaging listener started connection={}", connection_id)


async def _supervise_listeners() -> None:
    while True:
        try:
            await asyncio.sleep(_LISTENER_RECONCILE_INTERVAL)
            await _reconcile_listeners()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Messaging listener reconciliation failed")


async def _run_listener(connection_id: int) -> None:
    """Build a messenger in a short DB session, then start its listen loop."""
    try:
        async with get_db_session():
            messenger = await facade.get_messenger(connection_id)
    except ValueError as exc:
        # Configuration errors need a clear warning rather than a traceback.
        _listener_retry_after[connection_id] = time.monotonic() + _LISTENER_RETRY_DELAY
        logger.warning("Connection listener {} skipped: {}", connection_id, exc)
        return
    except Exception:
        _listener_retry_after[connection_id] = time.monotonic() + _LISTENER_RETRY_DELAY
        logger.exception("Failed to build messenger listener {}", connection_id)
        return
    # Construction may finish while shutdown is already under way. Some bridge
    # constructors perform network cleanup before propagating cancellation, so
    # cancellation alone is not a sufficient barrier against a late listen task.
    if _listeners_stopping:
        return
    listen_task = asyncio.create_task(
        messenger.listen(), name=f"messenger_bridge_listen_{connection_id}"
    )
    try:
        await listen_task
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Connection listener {} stopped after an error", connection_id)
    finally:
        _listener_retry_after[connection_id] = time.monotonic() + _LISTENER_RETRY_DELAY
        if not listen_task.done():
            listen_task.cancel()
        await asyncio.gather(listen_task, return_exceptions=True)


async def stop_listeners() -> None:
    global _listener_supervisor, _listeners_stopping

    _listeners_stopping = True
    if _listener_supervisor is not None:
        _listener_supervisor.cancel()
        await asyncio.gather(_listener_supervisor, return_exceptions=True)
        _listener_supervisor = None
    for task in _listener_tasks.values():
        task.cancel()
    if _listener_tasks:
        await asyncio.gather(*_listener_tasks.values(), return_exceptions=True)
    _listener_tasks.clear()
    _listener_signatures.clear()
    _listener_retry_after.clear()


# =============================================================================
# Startup registration
# =============================================================================

def register_messaging() -> None:
    """Inject the resolver and subscribe inbound handling to ``message_received``."""
    from core.params import Params, params_service

    async def refresh_messenger_tool(name: str, _value: str | None) -> None:
        if name not in {
            Params.MESSENGER_DRIVER,
            Params.MESSENGER_ENABLED_CHANNELS,
        }:
            return
        if name == Params.MESSENGER_DRIVER:
            from app.tools import sync_mandatory_tools
            from core.database import get_db

            await sync_mandatory_tools()
            await get_db().commit()
    facade.set_resolver(AppMessengerResolver())
    message_received.connect(handle_incoming)
    from app.agent import register_context_provider
    from app.messenger.session import session_context_provider

    register_context_provider(
        "messenger_session", session_context_provider, priority=10
    )
    params_service.register_change_listener(refresh_messenger_tool)
    logger.info(
        "Application messaging registered (enabled kinds: {})",
        facade.enabled_kinds(),
    )
