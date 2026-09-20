"""Portable, persistent human interactions for messaging transports."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.messenger.facade import MessengerFacade
from app.messenger.models import Interaction, Message
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
    """

    kind: str
    title: str
    body: str = ""
    options: list[ChoiceOption] = Field(default_factory=lambda: [])
    free_text: bool = False
    metadata: dict[str, Any] = Field(default_factory=lambda: {})
    timeout_seconds: int = 300
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
    tool_id: Optional[int]
    room_id: Optional[str]
    user_id: Optional[str]
    title: str
    body: str
    options: list[ChoiceOption]
    metadata: dict[str, Any]
    expires_at: datetime
    connection_id: Optional[int] = None
    reference: str = ""
    free_text: bool = False
    prompt_message_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


ChoiceHandler = Callable[[PendingChoice, ChoiceResolution], Awaitable[None]]
_choice_handlers: dict[str, ChoiceHandler] = {}
_PROCESSING_TIMEOUT_SECONDS = 30
_REFERENCE_RE = re.compile(r"#([A-F0-9]{8,12})\b", re.IGNORECASE)


def register_choice_handler(kind: str, handler: ChoiceHandler) -> None:
    """Register a domain handler for an interaction kind."""
    _choice_handlers[kind] = handler


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
            return _pending_from_record(existing)

    reference = uuid4().hex[:8].upper()
    metadata = dict(request.metadata)
    if normalized_key:
        metadata["idempotency_key"] = normalized_key
    record = Interaction(
        id=uuid4(),
        reference=reference,
        kind=request.kind,
        agent_id=agent_id,
        connection_id=int(getattr(messenger, "connection_id", 0) or 0) or None,
        tool_id=getattr(messenger, "tool_id", None) or None,
        room_id=room_id,
        user_id=user_id,
        title=request.title,
        body=request.body,
        options=[option.model_dump() for option in request.options],
        free_text=request.free_text,
        metadata_=metadata,
        expires_at=now + timedelta(seconds=max(1, request.timeout_seconds)),
    )
    db.add(record)
    await db.commit()

    try:
        sent = await messenger.send_to_room(
            room_id,
            _render_choice_text(request, reference),
            reply_to=reply_to,
        )
        record.prompt_message_id = str(sent.id)
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
    query = (
        select(Interaction)
        .where(
            Interaction.status == "PENDING",
            Interaction.expires_at > now,
            Interaction.tool_id == message.tool_id,
            *scope_clauses,
        )
        .order_by(Interaction.created_at.desc())
        .with_for_update(skip_locked=True)
    )
    query = query.where(Interaction.connection_id == connection_id)
    if agent_id is not None:
        query = query.where(Interaction.agent_id == agent_id)
    records = list((await db.execute(query)).scalars().all())

    reference_match = _REFERENCE_RE.search(message.text or "")
    reference = reference_match.group(1).upper() if reference_match else None
    answer_text = _REFERENCE_RE.sub("", message.text or "").strip()
    compatible: list[tuple[Interaction, PendingChoice, Optional[ChoiceOption]]] = []
    for record in records:
        if reference is not None and record.reference.upper() != reference:
            continue
        choice = _pending_from_record(record)
        option = _option_from_answer(choice.options, answer_text)
        if option is None and not (choice.free_text and answer_text):
            continue
        compatible.append((record, choice, option))

    if not compatible:
        return None
    if reference is None and len(compatible) > 1:
        logger.warning(
            "Multiple interactions match a message in room {}; an explicit reference is required",
            room_id,
        )
        return None

    record, choice, option = compatible[0]
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
    tool_id: int | None,
    room_id: str,
    user_id: str | None,
    limit: int = 10,
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
    query = (
        select(Interaction)
        .where(
            Interaction.status == "PENDING",
            Interaction.expires_at > now,
            Interaction.agent_id == agent_id,
            Interaction.connection_id == connection_id,
            Interaction.tool_id == tool_id,
            Interaction.room_id == room_id,
            user_clause,
        )
        .order_by(Interaction.created_at.desc())
        .limit(max(1, min(limit, 20)))
    )
    return [
        _pending_from_record(record)
        for record in (await get_db().scalars(query)).all()
    ]


async def resolve_pending_choice(
    *,
    reference: str,
    option_id: str,
    response_text: str,
    agent_id: int,
    connection_id: int | None,
    tool_id: int | None,
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
        raise ValueError("reference is required")
    if not normalized_option:
        raise ValueError("option_id is required")
    if not room_id.strip():
        raise ValueError("room_id is required")

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
            Interaction.tool_id == tool_id,
            Interaction.room_id == room_id,
            user_clause,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise ValueError("Pending choice not found in this conversation scope.")

    option = next(
        (
            candidate
            for candidate in _pending_from_record(record).options
            if candidate.id == normalized_option
        ),
        None,
    )
    if option is None:
        raise ValueError("option_id is not available for this pending choice.")

    existing = _resolution_from_record(record)
    if record.status in {"PROCESSING", "RESOLVED"}:
        if existing is None or existing.option_id != option.id:
            raise ValueError("This choice was already captured with another option.")
        return existing, record.status == "RESOLVED"
    if record.status != "PENDING" or record.expires_at <= datetime.now(timezone.utc):
        raise ValueError("This choice is no longer pending.")

    if capture_response is not None:
        await capture_response()

    resolution = ChoiceResolution(
        interaction_id=record.id,
        kind=record.kind,
        option_id=option.id,
        metadata=dict(record.metadata_ or {}),
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
        tool_id=record.tool_id,
        room_id=record.room_id,
        user_id=record.user_id,
        title=record.title,
        body=record.body,
        options=[ChoiceOption.model_validate(option) for option in record.options],
        metadata=dict(record.metadata_ or {}),
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
