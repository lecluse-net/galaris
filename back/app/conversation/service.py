"""Transactional room-scoped conversation rounds and notification delivery."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Literal, cast
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from app.agent.contracts import AIResult, ReasoningEffort, TaskMessage
from app.agent import message_prompt
from app.connection import Connection
from app.messenger import (
    CONVERSATION_OUTPUT_PENDING_METADATA_KEY,
    CONVERSATION_ROUND_METADATA_KEY,
    DISPLAYED_DOCUMENT_METADATA_KEY,
    TASK_REQUESTED_METADATA_KEY,
    TASK_REASONING_EFFORT_METADATA_KEY,
    Message,
    Room,
    hydrate_messages,
    resolve_effective_topic_id,
)
from core.database import get_db, get_db_session
from core.i18n import current_language, render_prompt, t

from .contracts import ConversationLeaseLostError, ConversationOutcome, ConversationTurn
from .models import (
    ConversationProcessLink,
    ConversationRound,
    ConversationRoundAttempt,
    ConversationRoundMessage,
    ConversationTaskLink,
)


ACTIVE_ROUND_STATUSES = ("FROZEN", "CLAIMED", "RUNNING")
PROCESSING_ROUND_STATUSES = ("CLAIMED", "RUNNING")
TERMINAL_ROUND_STATUSES = ("SUCCEEDED", "SUPERSEDED", "ERROR_RESOLVED", "CANCELLED")
CONTEXT_SOFT_MAX_CHARS = 16_000
CONTEXT_SOFT_OVERFLOW_CHARS = 2_000
LEASE_SECONDS = 45
MAX_ATTEMPTS = 2
LINKED_WORK_OBJECTIVE_MAX_CHARS = 250
LINKED_WORK_PAUSED_MAX_AGE = timedelta(hours=24)
LINKED_WORK_TERMINAL_MAX_AGE = timedelta(hours=1)
LINKED_WORK_TERMINAL_LIMIT = 2

_LINKED_WORK_STATE_PRIORITY = {
    "RUNNING": 0,
    "WAITING": 1,
    "QUEUED": 2,
    "PAUSED": 3,
    "TERMINAL": 4,
}
_REASONING_EFFORTS = frozenset(
    {"none", "low", "medium", "high", "xhigh", "max"}
)


def _direct_task_requested(message: Message) -> bool:
    metadata = message.metadata_ or {}
    if metadata.get(TASK_REQUESTED_METADATA_KEY) is True:
        return True
    return re.search(
        r"(?<!\w)@(?:task|plan|effort)\b",
        message.text or "",
        re.IGNORECASE,
    ) is not None


def _conversation_response_text(outcome: ConversationOutcome) -> str:
    """Render the durable response from the same text ``AIMessage`` blocks as live UI."""

    if outcome.execution_result is None:
        return outcome.text.strip()
    rendered = "\n\n".join(
        message.content
        for message in outcome.execution_result.messages
        if message.type == "text" and message.content.strip()
    ).strip()
    return rendered or outcome.text.strip()


def _task_reasoning_effort(message: Message) -> ReasoningEffort | None:
    raw = str((message.metadata_ or {}).get(TASK_REASONING_EFFORT_METADATA_KEY) or "")
    raw = raw.strip().lower()
    if raw == "minimal":
        raw = "low"
    return cast(ReasoningEffort, raw) if raw in _REASONING_EFFORTS else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _prompt_timestamp(value: datetime) -> str:
    return _aware_utc(value).astimezone().isoformat(timespec="minutes")


async def _room_scope(room_id: UUID, *, lock: bool = False) -> tuple[Room, Connection]:
    statement = select(Room).where(Room.id == room_id)
    if lock:
        statement = statement.with_for_update()
    room = await get_db().scalar(statement)
    if room is None:
        raise LookupError(f"Messenger room {room_id} not found.")
    connection = await get_db().get(Connection, room.connection_id)
    if connection is None:
        raise LookupError(f"Messenger connection {room.connection_id} not found.")
    return room, connection


async def admit_message(
    message: Message,
    *,
    agent_id: int,
    connection_id: int,
    language: str | None = None,
) -> bool:
    """Attach one canonical inbound message to one pending room round exactly once."""

    if message.room is None or message.messenger_room_id is None:
        raise ValueError("A conversation input requires an exact canonical room.")
    room, connection = await _room_scope(message.messenger_room_id, lock=True)
    if room.connection_id != connection_id or connection.agent_id != agent_id:
        raise ValueError("The Messenger message does not belong to the requested agent scope.")
    existing = await get_db().scalar(
        select(ConversationRoundMessage.round_id).where(
            ConversationRoundMessage.message_id == message.id,
            ConversationRoundMessage.role == "input",
        )
    )
    if existing is not None:
        await get_db().commit()
        return False

    language = language or str((message.metadata_ or {}).get("language") or "")
    # A concurrent classifier may have committed after the inbound event was
    # loaded. Read the canonical projection while admission owns the room.
    current_message = await get_db().get(Message, message.id, populate_existing=True)
    topic_source = current_message if current_message is not None else message
    effective_topic_id = resolve_effective_topic_id(
        topic_source.topic_id,
        topic_overridden=topic_source.topic_overridden,
        room_topic_id=room.topic_id,
    )

    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.room_id == room.id,
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status == "FROZEN",
        )
        .with_for_update()
    )
    if round_ is None:
        round_ = ConversationRound(
            room_id=room.id,
            language=await current_language(language, user_id=message.requester_user_id),
            status="FROZEN",
            topic_id=effective_topic_id,
            contact_memory_item_id=topic_source.contact_memory_item_id,
            requester_user_id=message.requester_user_id,
        )
        get_db().add(round_)
        await get_db().flush()
    else:
        round_.language = await current_language(
            language or round_.language, user_id=message.requester_user_id,
        )
        round_.topic_id = effective_topic_id
        round_.contact_memory_item_id = (
            topic_source.contact_memory_item_id or round_.contact_memory_item_id
        )
        if round_.requester_user_id != message.requester_user_id:
            round_.requester_user_id = None

    sequence = int(
        await get_db().scalar(
            select(func.coalesce(func.max(ConversationRoundMessage.sequence), 0)).where(
                ConversationRoundMessage.round_id == round_.id,
                ConversationRoundMessage.role == "input",
            )
        )
        or 0
    ) + 1
    get_db().add(
        ConversationRoundMessage(
            round_id=round_.id,
            message_id=message.id,
            role="input",
            response_sequence=None,
            sequence=sequence,
        )
    )
    await get_db().commit()
    return True


async def _input_messages(round_id: UUID) -> list[Message]:
    rows = list(
        (
            await get_db().scalars(
                select(Message)
                .join(
                    ConversationRoundMessage,
                    ConversationRoundMessage.message_id == Message.id,
                )
                .where(
                    ConversationRoundMessage.round_id == round_id,
                    ConversationRoundMessage.role == "input",
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        ).all()
    )
    return await hydrate_messages(rows)


def _message_chars(message: TaskMessage) -> int:
    return len(message.text) + 80


def _project_recent_messages(
    messages: Sequence[TaskMessage],
) -> tuple[list[TaskMessage], int]:
    selected: list[TaskMessage] = []
    total = 0
    maximum = CONTEXT_SOFT_MAX_CHARS + CONTEXT_SOFT_OVERFLOW_CHARS
    for message in reversed(messages):
        size = _message_chars(message)
        if selected and total + size > maximum:
            break
        selected.append(message)
        total += size
        if total >= CONTEXT_SOFT_MAX_CHARS:
            break
    selected.reverse()
    return selected, max(0, len(messages) - len(selected))


async def _finish_attempt(
    round_: ConversationRound, status: str, error: str | None = None
) -> None:
    attempt = await get_db().scalar(
        select(ConversationRoundAttempt)
        .where(
            ConversationRoundAttempt.round_id == round_.id,
            ConversationRoundAttempt.attempt_number == round_.attempt_count,
        )
        .with_for_update()
    )
    if attempt is not None:
        attempt.status = status
        attempt.error = error
        attempt.finished_at = _now()


async def _mark_round_inputs_consumed(
    round_id: UUID, consumed_at: datetime | None = None
) -> None:
    await get_db().execute(
        update(ConversationRoundMessage)
        .where(
            ConversationRoundMessage.round_id == round_id,
            ConversationRoundMessage.role == "input",
            ConversationRoundMessage.consumed_at.is_(None),
        )
        .values(consumed_at=consumed_at or _now())
    )


def _clear_round_lease(round_: ConversationRound) -> None:
    round_.lease_token = None
    round_.lease_owner = None
    round_.lease_expires_at = None


async def _pending_successor(round_: ConversationRound) -> ConversationRound | None:
    return await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.room_id == round_.room_id,
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status == "FROZEN",
            ConversationRound.id != round_.id,
        )
        .order_by(ConversationRound.created_at.asc(), ConversationRound.id.asc())
        .limit(1)
        .with_for_update()
    )


async def _merge_inputs(source: ConversationRound, target: ConversationRound) -> None:
    ordered_ids = list(
        await get_db().scalars(
            select(Message.id)
            .join(
                ConversationRoundMessage,
                ConversationRoundMessage.message_id == Message.id,
            )
            .where(
                ConversationRoundMessage.round_id.in_((source.id, target.id)),
                ConversationRoundMessage.role == "input",
                ConversationRoundMessage.consumed_at.is_(None),
            )
            .order_by(Message.created_at, Message.id)
        )
    )
    message_ids = list(dict.fromkeys(ordered_ids))
    await get_db().execute(
        delete(ConversationRoundMessage).where(
            ConversationRoundMessage.round_id == target.id,
            ConversationRoundMessage.role == "input",
        )
    )
    get_db().add_all(
        [
            ConversationRoundMessage(
                round_id=target.id,
                message_id=message_id,
                role="input",
                response_sequence=None,
                sequence=sequence,
            )
            for sequence, message_id in enumerate(message_ids, start=1)
        ]
    )
    target.source_round_id = target.source_round_id or source.id
    target.contact_memory_item_id = (
        target.contact_memory_item_id or source.contact_memory_item_id
    )
    if target.requester_user_id != source.requester_user_id:
        target.requester_user_id = None
    source.resolved_by_round_id = target.id


async def _claim_round(round_: ConversationRound, worker_id: str) -> ConversationRound:
    token = uuid4()
    round_.status = "CLAIMED"
    round_.lease_token = token
    round_.lease_owner = worker_id
    round_.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
    round_.attempt_count += 1
    get_db().add(
        ConversationRoundAttempt(
            round_id=round_.id,
            attempt_number=round_.attempt_count,
            worker_id=worker_id,
            lease_token=token,
        )
    )
    await get_db().commit()
    await get_db().refresh(round_)
    return round_


async def claim_next_round(worker_id: str) -> ConversationRound | None:
    """Claim the oldest pending room round, reclaiming safe expired executions first."""

    now = _now()
    expired = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status.in_(PROCESSING_ROUND_STATUSES),
            ConversationRound.lease_expires_at < now,
        )
        .order_by(ConversationRound.lease_expires_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if expired is not None:
        successor = await _pending_successor(expired)
        if successor is not None and not expired.effect_started:
            await _merge_inputs(expired, successor)
            expired.status = "SUPERSEDED"
            expired.finished_at = now
            _clear_round_lease(expired)
            await _finish_attempt(expired, "SUPERSEDED")
            await get_db().commit()
            return None
        if expired.effect_started or expired.attempt_count >= MAX_ATTEMPTS:
            expired.status = "ERROR_RESOLVED"
            expired.delivery_state = "PENDING"
            expired.last_error = (
                "Conversation round lease expired after a potentially started effect."
            )
            expired.finished_at = now
            await _mark_round_inputs_consumed(expired.id, now)
            _clear_round_lease(expired)
            await _finish_attempt(expired, "ERROR", expired.last_error)
            await get_db().commit()
            return None
        return await _claim_round(expired, worker_id)

    processing_round = aliased(ConversationRound)
    pending_room_id = await get_db().scalar(
        select(Room.id)
        .join(
            ConversationRound,
            ConversationRound.room_id == Room.id,
        )
        .where(
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status == "FROZEN",
            ~exists(
                select(processing_round.id).where(
                    processing_round.room_id == Room.id,
                    processing_round.voice_session_id.is_(None),
                    processing_round.status.in_(PROCESSING_ROUND_STATUSES),
                )
            ),
        )
        .order_by(ConversationRound.created_at.asc(), ConversationRound.id.asc())
        .limit(1)
        .with_for_update(of=Room, skip_locked=True)
    )
    if pending_room_id is None:
        return None
    pending = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.room_id == pending_room_id,
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status == "FROZEN",
        )
        .order_by(ConversationRound.created_at.asc(), ConversationRound.id.asc())
        .limit(1)
        .with_for_update()
    )
    if pending is None:
        return None
    has_input = await get_db().scalar(
        select(ConversationRoundMessage.message_id).where(
            ConversationRoundMessage.round_id == pending.id,
            ConversationRoundMessage.role == "input",
        )
    )
    if has_input is None:
        pending.status = "CANCELLED"
        pending.finished_at = now
        await get_db().commit()
        return None
    return await _claim_round(pending, worker_id)


async def renew_round_lease(round_id: UUID, lease_token: UUID) -> bool:
    """Renew one live round claim only while its exact owner token remains valid."""

    now = _now()
    renewed_id = await get_db().scalar(
        update(ConversationRound)
        .where(
            ConversationRound.id == round_id,
            ConversationRound.lease_token == lease_token,
            ConversationRound.lease_expires_at > now,
            ConversationRound.status.in_(PROCESSING_ROUND_STATUSES),
        )
        .values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        .returning(ConversationRound.id)
    )
    await get_db().commit()
    return renewed_id is not None


async def round_attempt_succeeded(round_id: UUID, lease_token: UUID) -> bool:
    """Recognize a normal lease release only for this exact successful attempt."""

    return bool(await get_db().scalar(
        select(exists().where(
            ConversationRound.id == round_id,
            ConversationRound.status == "SUCCEEDED",
            ConversationRoundAttempt.round_id == ConversationRound.id,
            ConversationRoundAttempt.attempt_number == ConversationRound.attempt_count,
            ConversationRoundAttempt.lease_token == lease_token,
            ConversationRoundAttempt.status == "SUCCESS",
            ConversationRoundAttempt.finished_at.is_not(None),
        ))
    ))


async def reconcile_terminal_round_llm_calls() -> int:
    """Cancel provider traces orphaned by a process exit after a terminal round."""

    from app.llm import LLMCall

    calls = list(
        (
            await get_db().scalars(
                select(LLMCall)
                .join(
                    ConversationRound,
                    ConversationRound.id == LLMCall.conversation_round_id,
                )
                .where(
                    LLMCall.status == "running",
                    ConversationRound.status.in_(TERMINAL_ROUND_STATUSES),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not calls:
        return 0
    now = _now()
    for call in calls:
        call.status = "cancelled"
        call.completed_at = now
        call.duration = max(0.0, (now - call.started_at).total_seconds())
        call.error = call.error or (
            "Provider stream stopped after its conversation round became terminal."
        )
    await get_db().commit()
    return len(calls)


def _owns_round(round_: ConversationRound, lease_token: UUID) -> bool:
    return (
        round_.status in PROCESSING_ROUND_STATUSES
        and round_.lease_token == lease_token
        and round_.lease_expires_at is not None
        and round_.lease_expires_at > _now()
    )


async def _locked_owned_round(round_id: UUID, lease_token: UUID) -> ConversationRound:
    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(ConversationRound.id == round_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None:
        raise LookupError(f"Conversation round {round_id} has no canonical room.")
    if not _owns_round(round_, lease_token):
        raise ConversationLeaseLostError(f"Conversation round lease lost for {round_id}")
    return round_


async def build_turn(round_id: UUID, *, lease_token: UUID) -> ConversationTurn:
    round_ = await _locked_owned_round(round_id, lease_token)
    room, connection = await _room_scope(round_.room_id)
    hydrated = await _input_messages(round_.id)
    source_messages = [
        TaskMessage.from_messenger(message).model_copy(
            update={"text": message.conversation_text}
        )
        for message in hydrated
    ]
    source_request = "\n\n".join(message_prompt(message) for message in source_messages)
    task_messages, omitted = _project_recent_messages(source_messages)
    if not task_messages:
        raise RuntimeError(f"Conversation round {round_id} has no canonical input message.")
    # This is a snapshot of the sending tab, never a room-wide or historical default.
    # Only the newest input describes what its author currently has open.
    visible_uri = (hydrated[-1].metadata_ or {}).get(DISPLAYED_DOCUMENT_METADATA_KEY)
    if hydrated[-1].platform == "internal" and isinstance(visible_uri, str):
        try:
            document_id = UUID(visible_uri.removeprefix("document://"))
        except ValueError:
            document_id = None
        if document_id is not None and visible_uri == f"document://{document_id}":
            newest_input = task_messages[-1]
            task_messages[-1] = newest_input.model_copy(update={
                "text": newest_input.text + "\n\n[Chat display context: the user has "
                f"{visible_uri} open alongside this conversation when sending this message.]",
            })
    messages = tuple(
        cast(Mapping[str, object], message.model_dump(mode="json"))
        for message in task_messages
    )
    objective = "\n".join(
        f"[{message.sender_display_name or message.sender_external_id or 'User'}] "
        f"{message.text.strip()}"
        for message in task_messages
        if message.text.strip()
    ).strip()
    if not objective:
        objective = "The user sent one or more non-text attachments."

    round_.status = "RUNNING"
    await get_db().commit()
    newest = task_messages[-1]
    from app.messenger import list_pending_choices

    pending_choices = await list_pending_choices(
        agent_id=connection.agent_id,
        connection_id=room.connection_id,
        tool_id=newest.tool_id,
        room_id=str(room.id),
        user_id=newest.sender_external_id,
    )
    turn = ConversationTurn(
        room_id=room.id,
        round_id=round_.id,
        agent_id=connection.agent_id,
        language=round_.language,
        objective=objective,
        messages=messages,
        source_request=source_request,
        messaging_context={
            "connection_id": room.connection_id,
            "tool_id": newest.tool_id,
            "platform": newest.platform or "messenger",
            "room_id": str(room.id),
            "room_locator": newest.room_external_id,
            "room_label": room.label,
            "room_kind": room.kind,
            "tool_code": newest.tool_code,
            "participant_id": newest.sender_external_id,
        },
        linked_work=await linked_work_snapshot(room.id),
        pending_interactions=tuple(
            {
                "reference": choice.reference,
                "kind": choice.kind,
                "title": choice.title[:500],
                "body": choice.body[:2_000],
                "options": tuple(
                    {"id": option.id[:100], "label": option.label[:300]}
                    for option in choice.options[:20]
                ),
                "task_id": str(choice.metadata.get("task_id") or ""),
                "expires_at": choice.expires_at.isoformat(),
            }
            for choice in pending_choices
        ),
        omitted_input_count=omitted,
        topic_id=round_.topic_id,
        direct_task_requested=_direct_task_requested(hydrated[-1]),
        reasoning_effort_override=_task_reasoning_effort(hydrated[-1]),
        contact_memory_item_id=round_.contact_memory_item_id,
        assert_fresh_before_effect=lambda: mark_effect_if_fresh(round_id, lease_token=lease_token),
        should_interrupt=lambda: newer_input_pending(round_id, lease_token=lease_token),
        attempt=round_.attempt_count,
    )

    async def admit_explicit_task(
        objective: str,
        *,
        forced_route: Literal["EXEC", "BRIEFING", "PLAN"] | None = None,
        forced_effort: Literal["standard", "high"] | None = None,
        require_briefing: bool = False,
        auto_approve: bool = False,
    ) -> Mapping[str, object]:
        from .mcp import admit_background_task

        return await admit_background_task(
            turn,
            objective,
            forced_route=forced_route,
            forced_effort=forced_effort,
            require_briefing=require_briefing,
            auto_approve=auto_approve,
        )

    return replace(turn, admit_background_task=admit_explicit_task)


async def newer_input_pending(round_id: UUID, *, lease_token: UUID) -> bool:
    """Observe committed text admission across workers without claiming an effect."""
    successor = aliased(ConversationRound)
    async with get_db_session():
        return bool(await get_db().scalar(select(exists().where(
            ConversationRound.id == round_id,
            ConversationRound.voice_session_id.is_(None),
            ConversationRound.status.in_(PROCESSING_ROUND_STATUSES),
            ConversationRound.lease_token == lease_token,
            ConversationRound.lease_expires_at > _now(),
            successor.room_id == ConversationRound.room_id,
            successor.voice_session_id.is_(None),
            successor.status == "FROZEN",
            successor.id != ConversationRound.id,
        ))))


async def mark_effect_if_fresh(round_id: UUID, *, lease_token: UUID) -> bool:
    """Atomically mark the first durable effect only while no successor is pending."""

    # The freshness guard runs from inside the conversation controller's long-lived
    # model loop. Own a short session here so every return path releases the row lock
    # before the next correlated LLMCall checks its ConversationRound foreign key.
    async with get_db_session():
        return await _mark_effect_if_fresh(round_id, lease_token=lease_token)


async def _mark_effect_if_fresh(round_id: UUID, *, lease_token: UUID) -> bool:
    """Apply the freshness decision inside the guard's isolated transaction."""

    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(ConversationRound.id == round_id)
        .with_for_update()
    )
    if round_ is None or round_.status != "RUNNING" or not _owns_round(round_, lease_token):
        return False
    await _room_scope(round_.room_id, lock=True)
    if await _pending_successor(round_) is not None:
        return False
    if not round_.effect_started:
        round_.effect_started = True
        round_.effect_started_at = _now()
    return True


async def linked_work_snapshot(room_id: UUID) -> tuple[Mapping[str, object], ...]:
    """Return temporally relevant Tasks launched from one canonical room."""

    from app.task import Task, amendment_basis
    from app.task.operational_state import inspect_operational_state
    from app.task.working_set import parse_working_set

    linked_from_room = exists(
        select(ConversationTaskLink.id)
        .join(
            ConversationRound,
            ConversationRound.id == ConversationTaskLink.round_id,
        )
        .where(
            ConversationTaskLink.task_id == Task.id,
            ConversationRound.room_id == room_id,
        )
    )
    rows = list(
        (
            await get_db().scalars(
                Task.histo_filter(
                    select(Task).where(
                        or_(
                            linked_from_room,
                            Task.message_group_id == str(room_id),
                        )
                    )
                ).order_by(Task.created_at.desc(), Task.id.desc())
            )
        ).all()
    )
    processing_at = _aware_utc(_now())
    candidates: list[
        tuple[int, datetime, str, Task, Mapping[str, object]]
    ] = []
    for task in rows:
        operational = await inspect_operational_state(task)
        state = str(operational["operational_state"])
        activity_at = _aware_utc(cast(datetime, task.updated_at or task.created_at))
        if (
            state == "PAUSED"
            and activity_at < processing_at - LINKED_WORK_PAUSED_MAX_AGE
        ):
            continue
        if (
            state == "TERMINAL"
            and activity_at <= processing_at - LINKED_WORK_TERMINAL_MAX_AGE
        ):
            continue
        candidates.append(
            (
                _LINKED_WORK_STATE_PRIORITY.get(state, len(_LINKED_WORK_STATE_PRIORITY)),
                activity_at,
                str(task.id),
                task,
                cast(Mapping[str, object], operational),
            )
        )

    candidates.sort(key=lambda item: (item[0], -item[1].timestamp(), item[2]))
    snapshots: list[Mapping[str, object]] = []
    terminal_count = 0
    for _priority, activity_at, _task_id, task, operational in candidates:
        state = str(operational["operational_state"])
        if state == "TERMINAL":
            if terminal_count >= LINKED_WORK_TERMINAL_LIMIT:
                continue
            terminal_count += 1
        result = task.get_execution_result()
        working_set = parse_working_set(task)
        created_at = _aware_utc(task.created_at)
        snapshots.append(
            {
                "task_id": str(task.id),
                "resource_uri": f"galaris://task/{task.id}",
                "label": task.label,
                "status": task.status.value,
                "paused": task.paused,
                "revision": task.revision,
                "amendment_basis": amendment_basis(task),
                "objective": str(task.objective or "")[:LINKED_WORK_OBJECTIVE_MAX_CHARS],
                "created_at": _prompt_timestamp(created_at),
                "state_since": _prompt_timestamp(activity_at),
                "updated_at": activity_at.isoformat(),
                "result_available": result is not None,
                "working_set": [
                    resource.model_dump(mode="json")
                    for resource in working_set.active()[:25]
                ],
                **operational,
            }
        )
    return tuple(snapshots)


async def complete_round(
    round_id: UUID, outcome: ConversationOutcome, *, lease_token: UUID,
) -> str:
    """Apply the final freshness barrier and deliver through canonical Messenger."""

    round_ = await _locked_owned_round(round_id, lease_token)
    room, _connection = await _room_scope(round_.room_id, lock=True)
    successor = await _pending_successor(round_)
    round_.execution_result = (
        outcome.execution_result.model_dump(mode="json")
        if outcome.execution_result is not None
        else None
    )
    round_.effect_started = round_.effect_started or outcome.effect_started
    interrupted = outcome.metadata.get("interrupted") is True
    if interrupted and successor is None and not round_.effect_started:
        # Administrative cancellation of the successor must not turn a partial
        # draft into a final answer or consume the still-unanswered original input.
        round_.status = "FROZEN"
        round_.last_error = None
        _clear_round_lease(round_)
        await _finish_attempt(round_, "SUPERSEDED")
        await get_db().commit()
        return "INTERRUPTED"
    if successor is not None and not round_.effect_started:
        await _merge_inputs(round_, successor)
        round_.status = "SUPERSEDED"
        round_.last_error = None
        round_.finished_at = _now()
        _clear_round_lease(round_)
        await _finish_attempt(round_, "SUPERSEDED")
        await get_db().commit()
        return "SUPERSEDED"
    if successor is not None or interrupted:
        round_.status = "SUCCEEDED"
        round_.last_error = None
        round_.finished_at = _now()
        await _mark_round_inputs_consumed(round_.id, round_.finished_at)
        _clear_round_lease(round_)
        await _finish_attempt(round_, "SUCCESS")
        await get_db().commit()
        return "STALE_AFTER_EFFECT"

    text = _conversation_response_text(outcome)
    sent_message: Message | None = None
    publish_message: Message | None = None
    if text:
        from app.messenger import get_messenger

        if not round_.effect_started:
            # Linearize the first outbound effect against admission while the room is locked.
            # The commit releases that row lock before Messenger journals through its own session.
            round_.effect_started = True
            round_.effect_started_at = _now()
        await get_db().commit()
        try:
            messenger = await get_messenger(room.connection_id)
            # The generic Messenger event must not expose the durable response before
            # its round link is committed. Chat uses that link for an atomic live-to-
            # durable handoff and would otherwise render both representations briefly.
            sent_message = await messenger.send_to_room(
                room.id,
                text,
                publish_event=False,
                journal_metadata={
                    CONVERSATION_OUTPUT_PENDING_METADATA_KEY: True,
                    CONVERSATION_ROUND_METADATA_KEY: str(round_id),
                },
            )
        except ConversationLeaseLostError:
            raise
        except Exception as exc:
            round_ = await _locked_owned_round(round_id, lease_token)
            round_.status = "ERROR_RESOLVED"
            round_.delivery_state = "UNKNOWN"
            round_.last_error = str(exc)[:2_000]
            round_.finished_at = _now()
            await _mark_round_inputs_consumed(round_.id, round_.finished_at)
            _clear_round_lease(round_)
            await _finish_attempt(round_, "ERROR", round_.last_error)
            await get_db().commit()
            return "DELIVERY_UNKNOWN"
        round_ = await _locked_owned_round(round_id, lease_token)
        await _link_output(round_.id, sent_message.id)
        publish_message = await get_db().get(
            Message,
            sent_message.id,
            populate_existing=True,
        )
        if publish_message is None:
            raise RuntimeError(
                f"Conversation output message {sent_message.id} disappeared before commit."
            )
        # Publish a fully loaded, detached snapshot. Some test and integration
        # sessions expire ORM instances on commit; signal receivers must never
        # trigger an implicit asynchronous reload while rendering the handoff.
        await get_db().refresh(publish_message)
        get_db().expunge(publish_message)
    round_.status = "SUCCEEDED"
    round_.last_error = None
    round_.delivery_state = "DELIVERED" if text else "SKIPPED"
    round_.finished_at = _now()
    await _mark_round_inputs_consumed(round_.id, round_.finished_at)
    _clear_round_lease(round_)
    await _finish_attempt(round_, "SUCCESS")
    await get_db().commit()
    if publish_message is not None:
        from app.messenger import message_sent

        await message_sent.send_async(publish_message)
    return "SUCCEEDED"


async def _link_output(round_id: UUID, message_id: UUID) -> None:
    contact_memory_item_id = await get_db().scalar(
        select(ConversationRound.contact_memory_item_id).where(
            ConversationRound.id == round_id
        )
    )
    await get_db().execute(
        update(Message)
        .where(Message.id == message_id)
        .values(
            contact_memory_item_id=contact_memory_item_id,
            metadata_=Message.metadata_.op("-")(
                CONVERSATION_OUTPUT_PENDING_METADATA_KEY
            ),
        )
    )
    next_sequence = int(
        await get_db().scalar(
            select(func.coalesce(func.max(ConversationRoundMessage.sequence), 0)).where(
                ConversationRoundMessage.round_id == round_id,
                ConversationRoundMessage.role == "output",
            )
        )
        or 0
    ) + 1
    await get_db().execute(
        pg_insert(ConversationRoundMessage)
        .values(
            round_id=round_id,
            message_id=message_id,
            role="output",
            response_sequence=1,
            sequence=next_sequence,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ConversationRoundMessage.round_id,
                ConversationRoundMessage.message_id,
            ]
        )
    )
    from .facade import inherit_reply_topics

    await inherit_reply_topics(round_id)


def _merge_failed_execution_result(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
    *,
    attempt_count: int,
) -> dict[str, object]:
    merged = dict(current)
    previous_messages = previous.get("messages") if previous else None
    current_messages = current.get("messages")
    merged["messages"] = [
        *(previous_messages if isinstance(previous_messages, list) else []),
        *(current_messages if isinstance(current_messages, list) else []),
    ]
    for key in ("execution_time", "cost"):
        previous_value = previous.get(key) if previous else 0
        current_value = current.get(key)
        merged[key] = sum(
            float(value)
            for value in (previous_value, current_value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
    previous_tools = previous.get("tools_used") if previous else None
    current_tools = current.get("tools_used")
    tool_names: list[str] = []
    for values in (previous_tools, current_tools):
        if isinstance(values, list):
            tool_names.extend(str(value) for value in cast(list[object], values))
    merged["tools_used"] = list(dict.fromkeys(tool_names))
    metadata: dict[str, object] = {}
    for values in (
        previous.get("metadata") if previous else None,
        current.get("metadata"),
    ):
        if isinstance(values, Mapping):
            metadata.update(
                {str(key): value for key, value in cast(Mapping[object, object], values).items()}
            )
    metadata["conversation_attempt_count"] = attempt_count
    merged["metadata"] = metadata
    merged["success"] = False
    return merged


def _degraded_reason_key(error: str | None) -> str:
    """Classify an internal error for a short user-facing explanation."""

    normalized = str(error or "").casefold()
    categories = (
        (
            "content_filter",
            ("content_filter", "content filter", "safety filter", "safety policy"),
        ),
        (
            "rate_limit",
            (
                "429",
                "rate limit",
                "rate_limit",
                "too many requests",
                "quota",
                "resource exhausted",
            ),
        ),
        (
            "authentication",
            (
                "401",
                "403",
                "unauthorized",
                "forbidden",
                "authentication",
                "api key",
                "api_key",
            ),
        ),
        (
            "timeout",
            ("timeout", "timed out", "deadline exceeded", "deadline_exceeded"),
        ),
        (
            "configuration",
            (
                "not configured",
                "no conversation controller",
                "conversation model",
                "model not found",
                "model was not found",
            ),
        ),
        (
            "admission",
            (
                "background work was required",
                "task or process admission",
                "admission tool",
            ),
        ),
        (
            "budget",
            (
                "request_limit",
                "tool_calls_limit",
                "usage limit",
                "usage_limit",
            ),
        ),
        (
            "incomplete_response",
            (
                "incomplete model response",
                "finish_reason=length",
                "terminal response",
                "provider stream ended",
            ),
        ),
        (
            "provider_unavailable",
            (
                "connection refused",
                "connection error",
                "connecterror",
                "network error",
                "name resolution",
                "service unavailable",
                "bad gateway",
                "502",
                "503",
                "504",
            ),
        ),
    )
    for key, markers in categories:
        if any(marker in normalized for marker in markers):
            return key
    return "internal"


_SENSITIVE_ERROR_VALUE_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|password|token)"
    r"\b\s*[=:]\s*[\"']?)([^\s\"',;&}]+)"
)
_BEARER_CREDENTIAL_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def _sanitized_llm_error(error: str | None, language: str) -> str:
    """Keep the provider error useful while redacting common credential shapes."""

    detail = str(error or "").strip()
    if not detail:
        return t("conversation.failure_notification.missing_detail", language)
    detail = _BEARER_CREDENTIAL_RE.sub(r"\1[redacted]", detail)
    detail = _SENSITIVE_ERROR_VALUE_RE.sub(r"\1[redacted]", detail)
    return _OPENAI_KEY_RE.sub("[redacted]", detail)


def _degraded_response(*, language: str, error: str | None) -> str:
    reason_key = _degraded_reason_key(error)
    return render_prompt(
        t("conversation.failure_notification.message", language),
        reason=t(f"conversation.failure_notification.reasons.{reason_key}", language),
        detail=_sanitized_llm_error(error, language),
    )


async def fail_round(
    round_id: UUID,
    error: str,
    *,
    lease_token: UUID,
    execution_result: AIResult | None = None,
) -> None:
    """Resolve, supersede, or retry a failed room round without losing inputs."""

    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(ConversationRound.id == round_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if round_ is None or not _owns_round(round_, lease_token):
        return
    await _room_scope(round_.room_id, lock=True)
    message = error[:2_000]
    round_.last_error = message
    if execution_result is not None:
        round_.execution_result = _merge_failed_execution_result(
            round_.execution_result,
            execution_result.model_dump(mode="json"),
            attempt_count=round_.attempt_count,
        )
    await _finish_attempt(round_, "ERROR", message)
    successor = await _pending_successor(round_)
    if successor is not None and not round_.effect_started:
        await _merge_inputs(round_, successor)
        round_.status = "SUPERSEDED"
        round_.finished_at = _now()
        _clear_round_lease(round_)
    elif not round_.effect_started and round_.attempt_count < MAX_ATTEMPTS:
        round_.status = "FROZEN"
        _clear_round_lease(round_)
    else:
        round_.status = "ERROR_RESOLVED"
        round_.delivery_state = "PENDING"
        round_.finished_at = _now()
        await _mark_round_inputs_consumed(round_.id, round_.finished_at)
        _clear_round_lease(round_)
    await get_db().commit()


async def claim_next_round_notification() -> UUID | None:
    """Lease one failed-round fallback response without replaying ambiguous sends."""

    now = _now()
    expired = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.delivery_state == "SENDING",
            ConversationRound.lease_expires_at < now,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if expired is not None:
        expired.delivery_state = "UNKNOWN"
        expired.last_error = (
            "Delivery worker lease expired after dispatch may have started."
        )
        _clear_round_lease(expired)
    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.status == "ERROR_RESOLVED",
            ConversationRound.delivery_state == "PENDING",
            ConversationRound.room_id.is_not(None),
        )
        .order_by(ConversationRound.finished_at.asc().nullslast())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if round_ is None:
        if expired is not None:
            await get_db().commit()
        return None
    round_.delivery_state = "SENDING"
    round_.lease_token = uuid4()
    round_.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    await get_db().commit()
    return round_.id


async def deliver_round_notification(round_id: UUID) -> None:
    round_ = await get_db().scalar(
        select(ConversationRound)
        .where(ConversationRound.id == round_id)
        .with_for_update(of=ConversationRound)
    )
    if (
        round_ is None
        or round_.delivery_state != "SENDING"
        or round_.lease_token is None
    ):
        return
    lease_token = round_.lease_token
    room, _connection = await _room_scope(round_.room_id)
    room_id = room.id
    connection_id = room.connection_id
    text = _degraded_response(
        language=round_.language,
        error=round_.last_error,
    )
    # Messenger journals through an independent transaction. Release the claim
    # lock before dispatch so the native provider can update the same room.
    await get_db().commit()
    try:
        from app.messenger import get_messenger

        messenger = await get_messenger(connection_id)
        sent = await messenger.send_to_room(room_id, text)
    except Exception as exc:
        await get_db().rollback()
        current = await get_db().scalar(
            select(ConversationRound)
            .where(
                ConversationRound.id == round_id,
                ConversationRound.delivery_state == "SENDING",
                ConversationRound.lease_token == lease_token,
            )
            .with_for_update(of=ConversationRound)
        )
        if current is not None:
            current.delivery_state = "UNKNOWN"
            current.last_error = str(exc)[:2_000]
            _clear_round_lease(current)
        await get_db().commit()
        raise
    await get_db().commit()
    current = await get_db().scalar(
        select(ConversationRound)
        .where(
            ConversationRound.id == round_id,
            ConversationRound.delivery_state == "SENDING",
            ConversationRound.lease_token == lease_token,
        )
        .with_for_update(of=ConversationRound)
    )
    if current is None:
        await get_db().commit()
        raise RuntimeError(
            f"Conversation notification lease was lost after dispatch for {round_id}."
        )
    await _link_output(current.id, sent.id)
    current.delivery_state = "DELIVERED"
    _clear_round_lease(current)
    await get_db().commit()


async def claim_next_process_notification() -> UUID | None:
    """Lease one terminal Process notification directly from its lineage link."""

    from app.process import ProcessRun

    now = _now()
    expired = await get_db().scalar(
        select(ConversationProcessLink)
        .where(
            ConversationProcessLink.notification_state == "SENDING",
            ConversationProcessLink.notification_lease_expires_at < now,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if expired is not None:
        expired.notification_state = "UNKNOWN"
        expired.notification_error = (
            "Delivery worker lease expired after dispatch may have started."
        )
        expired.notification_lease_token = None
        expired.notification_lease_expires_at = None
    link = await get_db().scalar(
        select(ConversationProcessLink)
        .join(ProcessRun, ProcessRun.id == ConversationProcessLink.process_run_id)
        .join(ConversationRound, ConversationRound.id == ConversationProcessLink.round_id)
        .where(
            ConversationProcessLink.notification_state == "PENDING",
            ProcessRun.status.in_(("success", "error", "cancelled")),
            ConversationRound.room_id.is_not(None),
        )
        .order_by(ConversationProcessLink.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if link is None:
        if expired is not None:
            await get_db().commit()
        return None
    link.notification_state = "SENDING"
    link.notification_attempt_count += 1
    link.notification_lease_token = uuid4()
    link.notification_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    await get_db().commit()
    return link.id


async def claim_next_task_notification() -> UUID | None:
    """Lease one terminal Task notification from its conversation link.

    The latest Task attempt must already be durably terminal and its scheduler lease
    released. Recording the Task attempt number at claim time prevents an ambiguous
    delivery from being replayed, while still allowing a later explicit Task retry to
    produce a new notification. A successful run whose terminal result is already
    proven delivered is durably skipped instead of being sent twice.
    """

    from app.task import Task, TaskAttemptStatus, TaskStatus
    from app.task.models import TaskAttempt

    now = _now()
    expired = await get_db().scalar(
        select(ConversationTaskLink)
        .where(
            ConversationTaskLink.notification_state == "SENDING",
            ConversationTaskLink.notification_lease_expires_at < now,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if expired is not None:
        expired.notification_state = "UNKNOWN"
        expired.notification_error = (
            "Delivery worker lease expired after dispatch may have started."
        )
        expired.notification_lease_token = None
        expired.notification_lease_expires_at = None

    while True:
        latest_attempt = aliased(TaskAttempt)
        row = (
            await get_db().execute(
                select(ConversationTaskLink, Task, ConversationRound, Room)
                .join(Task, Task.id == ConversationTaskLink.task_id)
                .join(
                    latest_attempt,
                    (latest_attempt.task_id == Task.id)
                    & (latest_attempt.attempt_number == Task.attempt_count),
                )
                .join(
                    ConversationRound,
                    ConversationRound.id == ConversationTaskLink.round_id,
                )
                .join(Room, Room.id == ConversationRound.room_id)
                .where(
                    ConversationTaskLink.notification_state.in_(
                        ("IDLE", "DELIVERED", "UNKNOWN", "SKIPPED")
                    ),
                    Task.lease_token.is_(None),
                    or_(
                        and_(
                            Task.status == TaskStatus.SUCCESS,
                            latest_attempt.status == TaskAttemptStatus.SUCCESS.value,
                        ),
                        and_(
                            Task.status == TaskStatus.ERROR,
                            latest_attempt.status == TaskAttemptStatus.ERROR.value,
                        ),
                    ),
                    Task.attempt_count
                    > ConversationTaskLink.notification_task_attempt_count,
                    ConversationRound.room_id.is_not(None),
                )
                .order_by(ConversationTaskLink.created_at.asc())
                .limit(1)
                .with_for_update(of=ConversationTaskLink, skip_locked=True)
            )
        ).one_or_none()
        if row is None:
            if expired is not None:
                await get_db().commit()
            return None

        link, task, _round, room = row
        task_attempt_count = task.attempt_count
        execution_result = task.get_execution_result()
        if task.status == TaskStatus.SUCCESS and execution_result is not None:
            from app.task import parse_working_set
            from .artifact_delivery import presented_artifacts, was_delivered_to_room

            artifacts = presented_artifacts(
                parse_working_set(task),
                str(execution_result.result or "").strip(),
            )
            room_ids = (str(room.id), str(room.external_id))
            pending_artifacts = any(
                not was_delivered_to_room(
                    parse_working_set(task),
                    artifact,
                    room.connection_id,
                    room_ids,
                )
                for artifact in artifacts
            )
            if (
                _terminal_text_was_delivered_to_room(
                    execution_result,
                    room_ids,
                )
                and not pending_artifacts
            ):
                link.notification_state = "SKIPPED"
                link.notification_task_attempt_count = task_attempt_count
                link.notification_message_id = None
                link.notification_error = None
                link.notification_lease_token = None
                link.notification_lease_expires_at = None
                await get_db().commit()
                expired = None
                continue

        link.notification_state = "SENDING"
        link.notification_attempt_count += 1
        link.notification_task_attempt_count = task_attempt_count
        link.notification_message_id = None
        link.notification_error = None
        link.notification_lease_token = uuid4()
        link.notification_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        await get_db().commit()
        return link.id


def _process_notification_text(
    *, language: str, label: str, status: str, result: object, error: str
) -> str:
    rendered_result = (
        json.dumps(result, ensure_ascii=False, indent=2)
        if isinstance(result, (dict, list))
        else str(result or "").strip()
    )
    if status.upper() in {"SUCCESS", "SUCCEEDED"}:
        text = f"{label} — terminé." if language == "fr" else f"{label} — completed."
        return f"{text}\n\n{rendered_result}" if rendered_result else text
    text = (
        f"{label} — arrêté avec l’état {status or 'ERROR'}."
        if language == "fr"
        else f"{label} — stopped with status {status or 'ERROR'}."
    )
    return f"{text}\n\n{error}" if error else text


def _terminal_text_was_delivered_to_room(
    execution_result: AIResult,
    room_ids: tuple[str, ...],
) -> bool:
    """Prove that the exact terminal text reached this room, not another target."""

    result_text = str(execution_result.result or "").strip()
    if not result_text:
        return False
    targets = {item for item in room_ids if item}
    for message in reversed(execution_result.messages or []):
        if (
            message.type != "tool"
            or not message.success
            or message.tool_name
            not in {"messenger_room_send_message", "messenger_room_send_file"}
        ):
            continue
        arguments = message.tool_arguments or {}
        if str(arguments.get("room_id") or "") not in targets:
            continue
        if any(
            str(arguments.get(key) or "").strip() == result_text
            for key in ("message", "text")
        ):
            return True
    return False


def _task_failure_notification_text(
    *, language: str, label: str, error: str
) -> str:
    detail = _sanitized_llm_error(error, language)[:2_000]
    return render_prompt(
        t("conversation.task_failure_notification.message", language),
        label=label,
        detail=detail,
    )


async def deliver_task_notification(link_id: UUID) -> None:
    """Create the canonical room message for one claimed terminal Task."""

    from app.task import Task, TaskStatus, parse_working_set
    from .artifact_delivery import PresentedArtifact

    row = (
        await get_db().execute(
            select(ConversationTaskLink, Task, ConversationRound, Room)
            .join(Task, Task.id == ConversationTaskLink.task_id)
            .join(ConversationRound, ConversationRound.id == ConversationTaskLink.round_id)
            .join(Room, Room.id == ConversationRound.room_id)
            .where(ConversationTaskLink.id == link_id)
            .with_for_update(of=ConversationTaskLink)
        )
    ).one_or_none()
    if row is None:
        return
    link, task, round_, room = row
    if link.notification_state != "SENDING" or link.notification_lease_token is None:
        return
    if task.attempt_count != link.notification_task_attempt_count:
        return
    lease_token = link.notification_lease_token
    room_id = room.id
    connection_id = room.connection_id
    execution_result = task.get_execution_result()
    working_set = parse_working_set(task)
    if task.status == TaskStatus.SUCCESS:
        text = (
            str(execution_result.result or "").strip()
            if execution_result is not None and execution_result.success
            else ""
        ) or str(task.feedback or "").strip()
        if not text:
            text = t(
                "conversation.task_success_notification.missing_detail",
                round_.language,
            )
    else:
        error = (
            str(execution_result.result or "").strip()
            if execution_result is not None and not execution_result.success
            else ""
        ) or str(task.last_error or task.feedback or "").strip()
        text = _task_failure_notification_text(
            language=round_.language,
            label=str(task.label or task.id),
            error=error,
        )
    # The canonical journal uses its own transaction and may need to update this
    # room. Keeping the lineage lock while dispatching self-deadlocks Chat.
    await get_db().commit()
    try:
        from app.agent.contracts import WorkingResource
        from app.file_share import ResourceContext, deliver_resource_to_messenger
        from app.messenger import get_messenger
        from app.task import upsert_working_resource
        from .artifact_delivery import (
            AUTO_DELIVERY_TOOL,
            clean_artifact_references,
            delivery_receipt_role,
            resolve_presented_artifacts,
            was_delivered_to_room,
        )

        messenger = await get_messenger(connection_id)
        dispatch = task.get_dispatch_result()
        runtime = dispatch.driver_code if dispatch is not None else "internal"
        resource_ctx = ResourceContext(
            agent_id=task.agent_id,
            runtime=runtime or "internal",
            task_id=task.id,
            language=round_.language,
        )
        artifacts = await resolve_presented_artifacts(resource_ctx, working_set, text)
        delivered_artifacts: list[PresentedArtifact] = []
        room_ids = (str(room.id), str(room.external_id))
        for artifact in artifacts:
            if was_delivered_to_room(
                working_set,
                artifact,
                connection_id,
                room_ids,
            ):
                delivered_artifacts.append(artifact)
                continue
            try:
                delivered = await deliver_resource_to_messenger(
                    resource_ctx,
                    messenger,
                    room_id,
                    artifact.source_uri,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "Conversation Task {} could not attach {} to room {}: {}",
                    task.id,
                    artifact.source_uri,
                    room_id,
                    exc,
                )
                continue
            await upsert_working_resource(
                task.id,
                WorkingResource(
                    resource_type="delivery_receipt",
                    role=delivery_receipt_role(
                        artifact.source_uri,
                        connection_id,
                        room.id,
                    ),
                    reference=delivered.uri,
                    label=delivered.name,
                    producer_task_id=task.id,
                    metadata={
                        "tool": AUTO_DELIVERY_TOOL,
                        "source": artifact.source_uri,
                        "destination": str(room.external_id),
                        "destination_room_id": str(room.id),
                        "connection_id": connection_id,
                        "uri": delivered.uri,
                        "size": delivered.size,
                        "media_type": delivered.media_type,
                        "delivered": True,
                    },
                ),
            )
            await get_db().commit()
            delivered_artifacts.append(artifact)
        text = clean_artifact_references(text, tuple(delivered_artifacts))
        sent = await messenger.send_to_room(room_id, text)
    except Exception as exc:
        await get_db().rollback()
        current = await get_db().scalar(
            select(ConversationTaskLink)
            .where(
                ConversationTaskLink.id == link_id,
                ConversationTaskLink.notification_state == "SENDING",
                ConversationTaskLink.notification_lease_token == lease_token,
            )
            .with_for_update(of=ConversationTaskLink)
        )
        if current is not None:
            current.notification_state = "UNKNOWN"
            current.notification_error = str(exc)[:2_000]
            current.notification_lease_token = None
            current.notification_lease_expires_at = None
        await get_db().commit()
        raise
    await get_db().commit()
    current = await get_db().scalar(
        select(ConversationTaskLink)
        .where(
            ConversationTaskLink.id == link_id,
            ConversationTaskLink.notification_state == "SENDING",
            ConversationTaskLink.notification_lease_token == lease_token,
        )
        .with_for_update(of=ConversationTaskLink)
    )
    if current is None:
        await get_db().commit()
        raise RuntimeError(
            f"Conversation Task notification lease was lost after dispatch for {link_id}."
        )
    current.notification_state = "DELIVERED"
    current.notification_message_id = sent.id
    current.notification_error = None
    current.notification_lease_token = None
    current.notification_lease_expires_at = None
    await get_db().commit()


async def deliver_process_notification(link_id: UUID) -> None:
    from app.process import ProcessRun

    row = (
        await get_db().execute(
            select(ConversationProcessLink, ProcessRun, ConversationRound, Room)
            .join(ProcessRun, ProcessRun.id == ConversationProcessLink.process_run_id)
            .join(ConversationRound, ConversationRound.id == ConversationProcessLink.round_id)
            .join(Room, Room.id == ConversationRound.room_id)
            .where(ConversationProcessLink.id == link_id)
            .with_for_update(of=ConversationProcessLink)
        )
    ).one_or_none()
    if row is None:
        return
    link, run, round_, room = row
    if link.notification_state != "SENDING" or link.notification_lease_token is None:
        return
    lease_token = link.notification_lease_token
    room_id = room.id
    connection_id = room.connection_id
    label = str(
        run.launch_snapshot.get("process_label")
        or run.launch_snapshot.get("workflow_id")
        or run.id
    )
    text = _process_notification_text(
        language=round_.language,
        label=label,
        status=run.status,
        result=run.output or {},
        error=str(run.error_message or "")[:2_000],
    )
    await get_db().commit()
    try:
        from app.messenger import get_messenger

        messenger = await get_messenger(connection_id)
        sent = await messenger.send_to_room(room_id, text)
    except Exception as exc:
        await get_db().rollback()
        current = await get_db().scalar(
            select(ConversationProcessLink)
            .where(
                ConversationProcessLink.id == link_id,
                ConversationProcessLink.notification_state == "SENDING",
                ConversationProcessLink.notification_lease_token == lease_token,
            )
            .with_for_update(of=ConversationProcessLink)
        )
        if current is not None:
            current.notification_state = "UNKNOWN"
            current.notification_error = str(exc)[:2_000]
            current.notification_lease_token = None
            current.notification_lease_expires_at = None
        await get_db().commit()
        raise
    await get_db().commit()
    current = await get_db().scalar(
        select(ConversationProcessLink)
        .where(
            ConversationProcessLink.id == link_id,
            ConversationProcessLink.notification_state == "SENDING",
            ConversationProcessLink.notification_lease_token == lease_token,
        )
        .with_for_update(of=ConversationProcessLink)
    )
    if current is None:
        await get_db().commit()
        raise RuntimeError(
            f"Conversation Process notification lease was lost after dispatch for {link_id}."
        )
    current.notification_state = "DELIVERED"
    current.notification_message_id = sent.id
    current.notification_error = None
    current.notification_lease_token = None
    current.notification_lease_expires_at = None
    await get_db().commit()


__all__ = [
    "admit_message",
    "build_turn",
    "claim_next_process_notification",
    "claim_next_task_notification",
    "claim_next_round",
    "claim_next_round_notification",
    "complete_round",
    "deliver_process_notification",
    "deliver_round_notification",
    "deliver_task_notification",
    "fail_round",
    "linked_work_snapshot",
    "mark_effect_if_fresh",
]
