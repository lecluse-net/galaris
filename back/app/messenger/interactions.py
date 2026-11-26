"""Portable, persistent human interactions for messaging transports."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast as sql_cast, delete, or_, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.messenger.facade import MessengerFacade
from app.messenger.interface import ChoiceRejected
from app.messenger.models import Interaction, Message, MessengerUser, RoomUser
from app.messenger.events import interaction_changed
from core.database import get_db
from core.i18n import default_language, is_supported, render_prompt, t


class ChoiceOption(BaseModel):
    """Option presented to a user."""

    id: str
    label: str
    aliases: list[str] = Field(default_factory=lambda: [])

    model_config = ConfigDict(extra="ignore")


class ChoiceRequest(BaseModel):
    """Transport-independent choice request.

    ``free_text=True`` accepts free-form answers and makes options optional.
    ``body_html`` is an optional editorial rendering for the native recipient.
    """

    kind: str
    title: str
    body: str = ""
    body_html: str | None = None
    options: list[ChoiceOption] = Field(default_factory=lambda: [])
    free_text: bool = False
    interpretation_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=lambda: {})
    timeout_seconds: int | None = 300
    reminder_delays: tuple[Annotated[int, Field(gt=0)], ...] = ()
    language: str = ""

    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True)
class ChoiceResolution:
    """Resolved interaction containing a selected option and/or free text."""

    interaction_id: UUID
    kind: str
    option_id: Optional[str]
    metadata: dict[str, Any]
    text: Optional[str] = None


@dataclass
class PendingChoice:
    id: UUID
    kind: str
    agent_id: Optional[int]
    service_id: Optional[int]
    room_id: Optional[str]
    user_id: Optional[str]
    title: str
    body: str
    options: list[ChoiceOption]
    metadata: dict[str, Any]
    expires_at: datetime | None
    connection_id: Optional[int] = None
    reference: str = ""
    free_text: bool = False
    prompt_message_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


ChoiceHandler = Callable[[PendingChoice, ChoiceResolution], Awaitable[None]]
ReminderGuard = Callable[[PendingChoice], Awaitable[bool]]
_choice_handlers: dict[str, ChoiceHandler] = {}
_choice_privileges: dict[str, tuple[str, ...]] = {}
_reminder_guards: dict[str, ReminderGuard] = {}
_PROCESSING_TIMEOUT_SECONDS = 30
_REFERENCE_RE = re.compile(r"#([A-F0-9]{8,12})\b", re.IGNORECASE)
_BODY_HTML_KEY = "_body_html"
_REMINDER_DELAYS_KEY = "_reminder_delays"
_REMINDER_DUE_KEY = "_reminder_due"
_REMINDER_PROMPT_KEY = "interaction_reminder_prompt"


def register_choice_handler(
    kind: str, handler: ChoiceHandler, *, required_privileges: tuple[str, ...] = (),
    reminder_pending: ReminderGuard | None = None,
) -> None:
    """Register a domain handler for an interaction kind."""
    _choice_handlers[kind] = handler
    _choice_privileges[kind] = required_privileges
    if reminder_pending is not None:
        _reminder_guards[kind] = reminder_pending


def choice_is_authorization(kind: str) -> bool:
    return "PERMISSION_DECIDE" in _choice_privileges.get(kind, ())


async def choice_authorized(kind: str, user_id: int | None, *, assigned: bool = False) -> bool:
    """Recheck server-registered rights before capturing or replaying a decision."""
    required = _choice_privileges.get(kind, ())
    if not required:
        return True
    if user_id is None:
        return False
    from core.authorize import check_assigned_privilege, check_privilege
    from core.user import get_user_record
    if assigned:
        return all([await check_assigned_privilege(user_id, code, get_db()) for code in required])
    user = await get_user_record(user_id)
    return all([await check_privilege(user, code, get_db()) for code in required])


async def _recipient_authorized(record: Interaction) -> bool:
    identity = record.user_id or ""
    user_id = int(identity[5:]) if identity.startswith("user:") and identity[5:].isdigit() else None
    from core.user import get_current_user_id
    return await choice_authorized(record.kind, user_id, assigned=get_current_user_id() != user_id)


def _normalize_answer(text: str) -> str:
    value = (text or "").strip().lower()
    value = re.sub(r"^[#>\-\s]+", "", value)
    value = re.sub(r"[\s.):-]+$", "", value)
    return value


def _language(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if is_supported(normalized) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"messenger_interactions.{key}", language), **values)


def _render_choice_text(request: ChoiceRequest, reference: str | None = None) -> str:
    language = _language(request.language)
    lines: list[str] = [f"**{request.title.strip()}**"]
    body = request.body.strip()
    if body:
        lines.extend(["", body])
    if request.options:
        instruction = _message(
            language,
            "choose_or_text" if request.free_text else "choose",
        )
        lines.extend(["", instruction])
        for index, option in enumerate(request.options, start=1):
            lines.append(f"{index}. {option.label}")
    if reference:
        lines.extend(["", _message(language, "reference", reference=reference)])
    return "\n".join(lines).strip()


def _option_from_answer(options: list[ChoiceOption], text: str) -> Optional[ChoiceOption]:
    answer = _normalize_answer(text)
    if not answer:
        return None
    if answer.isdigit():
        index = int(answer)
        if 1 <= index <= len(options):
            return options[index - 1]
    for option in options:
        values = {option.id.lower(), option.label.lower(), *[a.lower() for a in option.aliases]}
        if answer in values or any(
            answer.startswith(f"{value} ") or answer.startswith(f"{value},")
            for value in values
            if len(value) >= 4
        ):
            return option
    return None


def _message_scope(message: Message) -> tuple[Optional[str], Optional[str]]:
    room_id = str(message.room.id) if message.room else None
    user_id = message.sender.external_id if message.sender else None
    return room_id, user_id


async def _reply_prompt_id(message: Message) -> str | None:
    room_id, _ = _message_scope(message)
    if not message.reply_to or not room_id:
        return None
    row = (await get_db().execute(select(
        sql_cast(Message.id, String), Message.metadata_[_REMINDER_PROMPT_KEY].as_string(),
    ).where(
        Message.connection_id == message.connection_id,
        sql_cast(Message.messenger_room_id, String) == room_id,
        Message.direction == "outbound",
        Message.remote_message_id == message.reply_to,
    ))).one_or_none()
    return (row[1] or row[0]) if row is not None else None


def _explicit_references(message: Message) -> set[str]:
    return {value.upper() for value in _REFERENCE_RE.findall(message.text or "")}


async def explicit_reply_reference(message: Message, choices: list[PendingChoice]) -> str | None:
    """Identify a reply against the caller's live, scoped choices without inference."""
    references = _explicit_references(message)
    if references:
        return next((choice.reference for choice in choices if references == {choice.reference.upper()}), None)
    prompt_id = await _reply_prompt_id(message)
    return next((choice.reference for choice in choices if prompt_id and choice.prompt_message_id == prompt_id), None)


async def create_choice(
    messenger: MessengerFacade,
    *,
    agent_id: Optional[int],
    room_id: str,
    user_id: Optional[str] = None,
    request: ChoiceRequest,
    reply_to: Optional[str] = None,
    idempotency_key: str | None = None,
) -> PendingChoice:
    """Persist a pending interaction and send its rendered prompt to a room."""
    if not request.options and not request.free_text:
        raise ValueError(_message(_language(request.language), "requires_option"))

    now = datetime.now(timezone.utc)
    db = get_db()
    normalized_key = (idempotency_key or "").strip()
    if normalized_key:
        existing = await db.scalar(
            select(Interaction)
            .where(
                Interaction.kind == request.kind,
                Interaction.metadata_["idempotency_key"].as_string()
                == normalized_key,
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            if (existing.agent_id != agent_id or existing.connection_id != (messenger.connection_id or None)
                    or existing.service_id != (messenger.service_id or None) or existing.room_id != room_id
                    or existing.user_id != user_id):
                raise PermissionError("The existing request belongs to another messaging scope")
            if existing.prompt_message_id is None and existing.status == "PENDING" and not existing.has_expired(now):
                return await _send_choice_prompt(messenger, existing, request, reply_to=reply_to)
            return _pending_from_record(existing)

    reference = uuid4().hex[:8].upper()
    metadata = dict(request.metadata)
    metadata.pop(_BODY_HTML_KEY, None)
    metadata.pop(_REMINDER_DUE_KEY, None)
    metadata.pop(_REMINDER_DELAYS_KEY, None)
    if request.body_html:
        metadata[_BODY_HTML_KEY] = request.body_html
    metadata["interpretation_required"] = request.interpretation_required
    metadata["language"] = _language(request.language)
    if request.reminder_delays:
        metadata[_REMINDER_DELAYS_KEY] = list(request.reminder_delays)
    if normalized_key:
        metadata["idempotency_key"] = normalized_key
    record = Interaction(
        id=uuid4(),
        reference=reference,
        kind=request.kind,
        agent_id=agent_id,
        connection_id=int(getattr(messenger, "connection_id", 0) or 0) or None,
        service_id=getattr(messenger, "service_id", None) or None,
        room_id=room_id,
        user_id=user_id,
        title=request.title,
        body=request.body,
        options=[option.model_dump() for option in request.options],
        free_text=request.free_text,
        metadata_=metadata,
        expires_at=(now + timedelta(seconds=max(1, request.timeout_seconds))
                    if request.timeout_seconds is not None else None),
    )
    db.add(record)
    await db.commit()

    return await _send_choice_prompt(messenger, record, request, reply_to=reply_to)


def choice_body_html(record: Interaction) -> str | None:
    """Return the optional editorial projection stored alongside the text body."""
    value = (record.metadata_ or {}).get(_BODY_HTML_KEY)
    return value if isinstance(value, str) else None


def _choice_metadata(record: Interaction) -> dict[str, Any]:
    metadata = dict(record.metadata_ or {})
    metadata.pop(_BODY_HTML_KEY, None)
    metadata.pop(_REMINDER_DUE_KEY, None)
    metadata.pop(_REMINDER_DELAYS_KEY, None)
    return metadata


def _schedule_choice_reminder(record: Interaction, now: datetime) -> None:
    metadata = dict(record.metadata_)
    delays = metadata.pop(_REMINDER_DELAYS_KEY, [])
    metadata.pop(_REMINDER_DUE_KEY, None)
    if delays:
        due = now + timedelta(seconds=delays[0])
        if record.expires_at is None or due < record.expires_at:
            metadata[_REMINDER_DUE_KEY] = due.isoformat()
            metadata[_REMINDER_DELAYS_KEY] = delays[1:]
    record.metadata_ = metadata


async def _send_choice_prompt(
    messenger: MessengerFacade, record: Interaction, request: ChoiceRequest,
    *, reply_to: str | None = None,
) -> PendingChoice:
    """Send a persisted prompt, including a domain's recovery of an unsent choice."""
    db = get_db()
    try:
        sent = await messenger.send_to_room(
            str(record.room_id),
            _render_choice_text(request, record.reference),
            reply_to=reply_to,
        )
        record.prompt_message_id = str(sent.id)
        if record.metadata_.get(_REMINDER_DELAYS_KEY):
            _schedule_choice_reminder(record, datetime.now(timezone.utc))
        await db.commit()
    except Exception:
        await db.delete(record)
        await db.commit()
        raise

    await interaction_changed.send_async(record)
    return _pending_from_record(record)


async def resolve_from_message(
    message: Message, *, agent_id: Optional[int]
) -> Optional[ChoiceResolution]:
    """Resolve a matching pending interaction, or return ``None`` for normal routing."""
    now = datetime.now(timezone.utc)
    db = get_db()
    room_id, user_id = _message_scope(message)
    connection_id = message.connection_id
    scope_clauses: list[ColumnElement[bool]] = []
    if room_id:
        scope_clauses.append(Interaction.room_id == room_id)
        scope_clauses.append(
            or_(
                Interaction.user_id.is_(None),
                Interaction.user_id == user_id,
            )
            if user_id
            else Interaction.user_id.is_(None)
        )
    elif user_id:
        scope_clauses.append(Interaction.user_id == user_id)
    if not scope_clauses:
        return None
    references = _explicit_references(message)
    if len(references) > 1:
        return None
    reference = next(iter(references), None)
    prompt_id = await _reply_prompt_id(message) if message.reply_to and reference is None else None
    if message.reply_to and reference is None and prompt_id is None:
        return None
    targeted = reference is not None or prompt_id is not None
    query = (
        select(Interaction)
        .where(
            Interaction.status == "PENDING",
            Interaction.unexpired_at(now),
            Interaction.service_id == message.service_id,
            *scope_clauses,
        )
        .order_by(Interaction.created_at.desc())
        .with_for_update(skip_locked=not targeted)
    )
    query = query.where(Interaction.connection_id == connection_id)
    if agent_id is not None:
        query = query.where(Interaction.agent_id == agent_id)
    if reference is not None:
        query = query.where(Interaction.reference == reference)
    elif prompt_id is not None:
        query = query.where(Interaction.prompt_message_id == prompt_id)
    records = list((await db.execute(query)).scalars().all())

    answer_text = _REFERENCE_RE.sub("", message.text or "").strip()
    if not targeted and any(record.metadata_.get("interpretation_required") for record in records):
        # The same "yes" or file can concern a Process instead of another pending
        # approval. Let the conversation controller disambiguate before any effect.
        return None
    compatible: list[tuple[Interaction, PendingChoice, Optional[ChoiceOption]]] = []
    for record in records:
        # Text and files need interpretation: proximity alone is never an answer.
        if record.metadata_.get("interpretation_required"):
            continue
        choice = _pending_from_record(record)
        option = _option_from_answer(choice.options, answer_text)
        if option is None and not (choice.free_text and answer_text):
            continue
        compatible.append((record, choice, option))

    if not compatible:
        return None
    if len(compatible) > 1:
        logger.warning(
            "Multiple interactions match a message in room {}; an explicit reference is required",
            room_id,
        )
        return None

    record, choice, option = compatible[0]
    if not await _recipient_authorized(record):
        return None
    resolution = ChoiceResolution(
        interaction_id=choice.id,
        kind=choice.kind,
        option_id=option.id if option is not None else None,
        metadata=dict(choice.metadata or {}),
        text=answer_text or None,
    )
    processing_token = uuid4()
    record.status = "PROCESSING"
    record.processing_token = processing_token
    record.processing_expires_at = now + timedelta(seconds=_PROCESSING_TIMEOUT_SECONDS)
    record.resolution = _resolution_payload(resolution)
    await db.commit()

    await interaction_changed.send_async(record)

    await _deliver_record(record.id, processing_token)

    return resolution


async def list_pending_choices(
    *,
    agent_id: int,
    connection_id: int | None,
    service_id: int | None,
    room_id: str,
    user_id: str | None,
    limit: int = 10,
    offset: int = 0,
    kind: str | None = None,
    prioritize_reply: Message | None = None,
) -> list[PendingChoice]:
    """Return live choices visible to one exact conversation participant.

    This read surface lets the conversation controller understand a natural-language
    response that the deterministic option matcher could not classify. It deliberately
    preserves the same connection, Tool, room, user, and agent scope as
    :func:`resolve_from_message`.
    """

    if not room_id.strip():
        return []
    now = datetime.now(timezone.utc)
    user_clause: ColumnElement[bool] = (
        or_(Interaction.user_id.is_(None), Interaction.user_id == user_id)
        if user_id
        else Interaction.user_id.is_(None)
    )
    priority: ColumnElement[bool] | None = None
    if prioritize_reply is not None:
        references = _explicit_references(prioritize_reply)
        if len(references) == 1:
            priority = Interaction.reference == next(iter(references))
        elif not references:
            prompt_id = await _reply_prompt_id(prioritize_reply)
            if prompt_id is not None:
                priority = Interaction.prompt_message_id == prompt_id
    query = (
        select(Interaction)
        .where(
            Interaction.status == "PENDING",
            Interaction.unexpired_at(now),
            Interaction.agent_id == agent_id,
            Interaction.connection_id == connection_id,
            Interaction.service_id == service_id,
            Interaction.room_id == room_id,
            user_clause,
        )
    )
    if kind is not None:
        query = query.where(Interaction.kind == kind)
    if priority is not None:
        query = query.order_by(priority.desc().nulls_last())
    query = query.order_by(Interaction.created_at.desc()).offset(max(0, offset)).limit(max(1, min(limit, 20)))
    return [
        _pending_from_record(record)
        for record in (await get_db().scalars(query)).all()
    ]


async def apply_interpreted_response(
    *, reference: str, kind: str, agent_id: int, connection_id: int,
    service_id: int | None, room_id: str, user_id: str,
    response: dict[str, Any], apply: Callable[[PendingChoice], Awaitable[None]],
    normalize_response: Callable[[PendingChoice, dict[str, Any]], dict[str, Any]] | None = None,
) -> bool:
    """Apply a validated domain answer and settle its exact messaging request atomically.

    ``apply`` only mutates the contextual transaction; it must not commit or send.
    Invalid or incomplete answers leave the request pending for a clarification.
    """
    db = get_db()
    record = await db.scalar(select(Interaction).where(
        Interaction.reference == reference.strip().lstrip("#").upper(),
        Interaction.kind == kind, Interaction.agent_id == agent_id,
        Interaction.connection_id == connection_id, Interaction.service_id == service_id,
        Interaction.room_id == room_id, Interaction.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))
    if record is None or not record.metadata_.get("interpretation_required"):
        raise PermissionError("No matching request for this conversation participant")
    if normalize_response is not None:
        response = normalize_response(_pending_from_record(record), response)
    if record.status == "RESOLVED":
        if (record.resolution or {}).get("data") != response:
            raise ValueError("This request already has a different response")
        return False
    if record.status != "PENDING" or record.has_expired(datetime.now(timezone.utc)):
        raise ValueError("This request is no longer pending")
    await apply(_pending_from_record(record))
    record.resolution = {"data": response}
    record.status = "RESOLVED"
    record.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await interaction_changed.send_async(record)
    return True


async def resolve_pending_choice(
    *,
    reference: str,
    option_id: str,
    response_text: str,
    agent_id: int,
    connection_id: int | None,
    service_id: int | None,
    room_id: str,
    user_id: str | None,
    capture_response: Callable[[], Awaitable[None]] | None = None,
) -> tuple[ChoiceResolution, bool]:
    """Resolve one scoped pending choice selected by the conversation controller.

    The option must be one of the server-persisted choices. Repeating the same action is
    idempotent; choosing a different option after capture is rejected. The boolean reports
    whether the domain handler has completed, as opposed to being durably queued for replay.
    A button transport can journal its response through ``capture_response`` in the same
    transaction as capture, before the handler resumes work. It must not commit.
    """

    normalized_reference = reference.strip().lstrip("#").upper()
    normalized_option = option_id.strip()
    if not normalized_reference:
        raise ChoiceRejected("reference is required")
    if not normalized_option:
        raise ChoiceRejected("option_id is required")
    if not room_id.strip():
        raise ChoiceRejected("room_id is required")

    user_clause: ColumnElement[bool] = (
        or_(Interaction.user_id.is_(None), Interaction.user_id == user_id)
        if user_id
        else Interaction.user_id.is_(None)
    )
    record = await get_db().scalar(
        select(Interaction)
        .where(
            Interaction.reference == normalized_reference,
            Interaction.agent_id == agent_id,
            Interaction.connection_id == connection_id,
            Interaction.service_id == service_id,
            Interaction.room_id == room_id,
            user_clause,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise ChoiceRejected("Pending choice not found in this conversation scope.")

    option = next(
        (
            candidate
            for candidate in _pending_from_record(record).options
            if candidate.id == normalized_option
        ),
        None,
    )
    if option is None:
        raise ChoiceRejected("option_id is not available for this pending choice.")

    existing = _resolution_from_record(record)
    if record.status in {"PROCESSING", "RESOLVED"}:
        if existing is None or existing.option_id != option.id:
            raise ChoiceRejected("This choice was already captured with another option.")
        return existing, record.status == "RESOLVED"
    if record.status != "PENDING" or record.has_expired(datetime.now(timezone.utc)):
        raise ChoiceRejected("This choice is no longer pending.")

    if not await _recipient_authorized(record):
        raise PermissionError("Permission decision access is required.")

    if capture_response is not None:
        await capture_response()

    resolution = ChoiceResolution(
        interaction_id=record.id,
        kind=record.kind,
        option_id=option.id,
        metadata=_choice_metadata(record),
        text=response_text.strip() or None,
    )
    processing_token = uuid4()
    record.status = "PROCESSING"
    record.processing_token = processing_token
    record.processing_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=_PROCESSING_TIMEOUT_SECONDS
    )
    record.resolution = _resolution_payload(resolution)
    await get_db().commit()
    await interaction_changed.send_async(record)
    delivered = await _deliver_record(record.id, processing_token)
    return resolution, delivered


def _pending_from_record(record: Interaction) -> PendingChoice:
    return PendingChoice(
        id=record.id,
        kind=record.kind,
        agent_id=record.agent_id,
        connection_id=record.connection_id,
        service_id=record.service_id,
        room_id=record.room_id,
        user_id=record.user_id,
        title=record.title,
        body=record.body,
        options=[ChoiceOption.model_validate(option) for option in record.options],
        metadata=_choice_metadata(record),
        expires_at=record.expires_at,
        reference=record.reference,
        free_text=record.free_text,
        prompt_message_id=record.prompt_message_id,
        created_at=record.created_at,
    )


def _resolution_payload(resolution: ChoiceResolution) -> dict[str, Any]:
    return {
        "interaction_id": str(resolution.interaction_id),
        "kind": resolution.kind,
        "option_id": resolution.option_id,
        "metadata": resolution.metadata,
        "text": resolution.text,
    }


def _resolution_from_record(record: Interaction) -> ChoiceResolution | None:
    if not isinstance(record.resolution, dict):
        return None
    payload = record.resolution
    return ChoiceResolution(
        interaction_id=record.id,
        kind=record.kind,
        option_id=payload.get("option_id"),
        metadata=dict(payload.get("metadata") or {}),
        text=payload.get("text"),
    )


async def _deliver_record(interaction_id: UUID, processing_token: UUID) -> bool:
    """Deliver a resolution; ``PROCESSING`` state enables replay after a crash."""
    db = get_db()
    record = await db.get(Interaction, interaction_id)
    if (
        record is None
        or record.status != "PROCESSING"
        or record.processing_token != processing_token
    ):
        return False
    resolution = _resolution_from_record(record)
    handler = _choice_handlers.get(record.kind)
    if resolution is None or handler is None:
        logger.warning(
            "Handler or resolution is unavailable for interaction '{}'", record.kind
        )
        return False

    if not await _recipient_authorized(record):
        # A captured answer must not execute later after authority was revoked.
        changed = await db.scalar(update(Interaction).where(
            Interaction.id == interaction_id,
            Interaction.status == "PROCESSING",
            Interaction.processing_token == processing_token,
        ).values(status="PENDING", resolution=None, processing_token=None,
            processing_expires_at=None).returning(Interaction.id)
            .execution_options(synchronize_session="fetch"))
        await db.commit()
        if changed is not None:
            await interaction_changed.send_async(record)
        return False

    try:
        await handler(_pending_from_record(record), resolution)
    except Exception:
        logger.exception(
            "Interaction {} was captured but handler '{}' failed; replay deferred",
            record.id,
            record.kind,
        )
        record.processing_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=_PROCESSING_TIMEOUT_SECONDS
        )
        await db.commit()
        return False

    record.status = "RESOLVED"
    record.resolved_at = datetime.now(timezone.utc)
    record.processing_token = None
    record.processing_expires_at = None
    await db.commit()
    await interaction_changed.send_async(record)
    return True


async def retry_pending_interactions() -> None:
    """Replay handlers whose ``PROCESSING`` lease expired after an error or crash."""
    db = get_db()
    now = datetime.now(timezone.utc)
    records = list(
        (
            await db.execute(
                select(Interaction)
                .where(
                    Interaction.status == "PROCESSING",
                    Interaction.processing_expires_at <= now,
                    Interaction.resolution.is_not(None),
                )
                .order_by(Interaction.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    claimed: list[tuple[UUID, UUID]] = []
    for record in records:
        token = uuid4()
        record.processing_token = token
        record.processing_expires_at = now + timedelta(seconds=_PROCESSING_TIMEOUT_SECONDS)
        claimed.append((record.id, token))
    await db.commit()
    for interaction_id, token in claimed:
        await _deliver_record(interaction_id, token)


async def deliver_choice_reminders(*, now: datetime | None = None) -> None:
    """Claim due reminders durably before calling the transport."""
    from .service import messenger_for_agent_connection

    db = get_db()
    due = Interaction.metadata_[_REMINDER_DUE_KEY].as_string()
    for _ in range(5):
        current = now or datetime.now(timezone.utc)
        record = await db.scalar(select(Interaction).where(
            Interaction.status == "PENDING", Interaction.unexpired_at(current),
            Interaction.prompt_message_id.is_not(None),
            due <= current.isoformat(),
        ).order_by(due, Interaction.id).limit(1).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True))
        if record is None:
            return
        # Advance before the external send. Other workers or restarts cannot send
        # the same slot again, even if its transport receipt was lost.
        _schedule_choice_reminder(record, current)
        await db.commit()
        choice = _pending_from_record(record)
        try:
            async with asyncio.timeout(10):
                guard = _reminder_guards.get(choice.kind)
                if (guard is None or choice.agent_id is None or choice.connection_id is None
                        or not choice.room_id or not choice.prompt_message_id
                        or not await _recipient_authorized(record) or not await guard(choice)):
                    continue
                messenger = await messenger_for_agent_connection(choice.agent_id, choice.connection_id)
                prompt = await db.scalar(select(Message.remote_message_id).where(
                    sql_cast(Message.id, String) == choice.prompt_message_id,
                    Message.connection_id == choice.connection_id,
                    sql_cast(Message.messenger_room_id, String) == choice.room_id,
                    Message.direction == "outbound",
                ))
                if prompt is None or await db.scalar(select(Interaction.id).where(
                    Interaction.id == choice.id, Interaction.status == "PENDING",
                    Interaction.unexpired_at(now or datetime.now(timezone.utc)),
                )) is None:
                    continue
                language = _language(choice.metadata.get("language"))
                reminder = ChoiceRequest(
                    kind=choice.kind, title=_message(language, "reminder", title=choice.title),
                    body=choice.body, options=choice.options, free_text=choice.free_text, language=language,
                )
                await messenger.send_to_room(
                    choice.room_id, _render_choice_text(reminder, choice.reference), reply_to=prompt,
                    journal_metadata={_REMINDER_PROMPT_KEY: choice.prompt_message_id},
                )
        except Exception:
            await db.rollback()
            logger.exception("Could not send reminder for Messenger interaction {}", choice.id)


async def request_user_choice(
    *, agent_id: int, user_id: int, request: ChoiceRequest, idempotency_key: str,
) -> PendingChoice:
    """Deliver a choice only to this human's private internal conversation.

    The domain owns authorization and concurrent notification claims. Reusing the key
    recovers a previously delivered choice without sending another prompt.
    """
    from .native_facade import create_internal_room, internal_direct_room_observation
    from .service import messenger_for_agent_kind

    db = get_db()
    messenger = await messenger_for_agent_kind(agent_id, "internal")
    external_user = f"user:{user_id}"
    existing = await db.scalar(select(Interaction).where(
        Interaction.agent_id == agent_id, Interaction.kind == request.kind,
        Interaction.metadata_["idempotency_key"].as_string() == idempotency_key,
    ).order_by(Interaction.created_at.desc()).limit(1))
    if existing is not None:
        if (existing.user_id != external_user or existing.connection_id != messenger.connection_id):
            raise PermissionError("The existing choice belongs to another conversation scope")
        if (existing.prompt_message_id is None and existing.status == "PENDING"
                and not existing.has_expired(datetime.now(timezone.utc))):
            return await _send_choice_prompt(messenger, existing, ChoiceRequest(
                kind=existing.kind, title=existing.title, body=existing.body,
                options=[ChoiceOption.model_validate(option) for option in existing.options],
                free_text=existing.free_text, language=request.language,
                interpretation_required=bool(existing.metadata_.get("interpretation_required")),
            ))
        return _pending_from_record(existing)
    room = await internal_direct_room_observation(messenger.connection_id, external_user)
    room_id = room.local_id if room is not None else None
    if room_id is not None:
        archived = await db.scalar(select(RoomUser.archived).join(
            MessengerUser, MessengerUser.id == RoomUser.user_id,
        ).where(RoomUser.room_id == room_id, MessengerUser.galaris_user_id == user_id))
        members = (await db.scalars(select(MessengerUser).join(
            RoomUser, RoomUser.user_id == MessengerUser.id,
        ).where(RoomUser.room_id == room_id))).all()
        if archived or any(member.galaris_user_id != user_id and member.agent_id != agent_id for member in members):
            room_id = None
    if room_id is None:
        created = await create_internal_room(actor_user_id=user_id, agent_id=agent_id)
        if created is None:
            raise LookupError("No private Chat channel for this approver")
        room_id = created.id
    return await create_choice(
        messenger, agent_id=agent_id, room_id=str(room_id), user_id=external_user,
        request=request, idempotency_key=idempotency_key,
    )


async def expire_user_choice(*, agent_id: int, kind: str, idempotency_key: str) -> None:
    """Withdraw an unanswered prompt after its domain action was handled elsewhere."""
    db = get_db()
    record = await db.scalar(select(Interaction).where(
        Interaction.agent_id == agent_id, Interaction.kind == kind,
        Interaction.metadata_["idempotency_key"].as_string() == idempotency_key,
        Interaction.status == "PENDING",
    ).with_for_update().execution_options(populate_existing=True))
    if record is None or record.has_expired(datetime.now(timezone.utc)):
        return
    record.expires_at = datetime.now(timezone.utc)
    await db.commit()
    await interaction_changed.send_async(record)


async def settle_user_choice(*, agent_id: int, kind: str, idempotency_key: str, option_id: str,
                             committed_option: ChoiceOption | None = None) -> None:
    """Reflect an already committed domain decision without executing its handler again."""
    db = get_db()
    record = await db.scalar(select(Interaction).where(
        Interaction.agent_id == agent_id, Interaction.kind == kind,
        Interaction.metadata_["idempotency_key"].as_string() == idempotency_key,
        Interaction.status.in_(("PENDING", "PROCESSING")),
    ).with_for_update().execution_options(populate_existing=True))
    if record is None:
        return
    option = next((option for option in record.options if option.get("id") == option_id), None)
    # A committed domain decision may introduce an option absent from an older question.
    # This trusted server projection never makes that option available for human resolution.
    if option is None and committed_option is not None and committed_option.id == option_id:
        option = committed_option.model_dump()
    if option is None:
        raise ValueError("The committed choice must match a persisted option.")
    record.resolution = _resolution_payload(ChoiceResolution(
        interaction_id=record.id, kind=record.kind, option_id=option_id,
        metadata=_choice_metadata(record), text=option["label"],
    ))
    record.status = "RESOLVED"
    record.resolved_at = datetime.now(timezone.utc)
    record.processing_token = None
    record.processing_expires_at = None
    await db.commit()
    await interaction_changed.send_async(record)


async def _reset_for_tests() -> None:  # pyright: ignore[reportUnusedFunction]
    db = get_db()
    await db.execute(
        delete(Interaction).where(
            Interaction.kind.in_(
                ("free-test", "closed-test", "ambiguous", "retry-handler")
            )
        )
    )
    await db.commit()
