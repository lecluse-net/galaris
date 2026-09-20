"""Read-only projections for phone-call execution monitoring."""

from __future__ import annotations

from collections.abc import Collection
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from app.agent import Agent
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.llm import LLMCall
from app.messenger import Message, MessengerUser, Room, RoomUser
from app.tools import ToolModel
from core.database import get_db

from .models import VoiceConversationSession, VoiceConversationStatus, VoiceTurnStatus
from .schemas import (
    VoiceConversationDetail,
    VoiceConversationOverview,
    VoiceConversationPage,
    VoiceConversationSummary,
    VoiceConversationTurnDetail,
    VoiceConversationTurnRead,
)


def _duration_seconds(started_at: datetime, finished_at: datetime | None) -> float:
    end = finished_at or datetime.now(timezone.utc)
    return max(0.0, (end - started_at).total_seconds())


def _round_stats():
    return (
        select(
            ConversationRound.voice_session_id.label("session_id"),
            func.count(ConversationRound.id).label("turn_count"),
            func.count(ConversationRound.id)
            .filter(ConversationRound.status == VoiceTurnStatus.INTERRUPTED.value)
            .label("interrupted_count"),
            func.count(ConversationRound.id)
            .filter(ConversationRound.status == VoiceTurnStatus.FAILED.value)
            .label("failed_count"),
        )
        .where(ConversationRound.voice_session_id.is_not(None))
        .group_by(ConversationRound.voice_session_id)
        .subquery()
    )


def _latest_topic_id():
    return (
        select(ConversationRound.topic_id)
        .where(
            ConversationRound.voice_session_id == VoiceConversationSession.id,
            ConversationRound.topic_id.is_not(None),
        )
        .order_by(ConversationRound.sequence.desc())
        .limit(1)
        .correlate(VoiceConversationSession)
        .scalar_subquery()
    )


def _session_filters(
    *,
    agent_id: int | None,
    status: str | None,
    active: bool | None,
    transport_kind: str | None,
    topic_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
) -> list[Any]:
    filters: list[Any] = []
    if agent_id is not None:
        filters.append(Connection.agent_id == agent_id)
    if status:
        filters.append(VoiceConversationSession.status == status)
    if active is not None:
        is_active = VoiceConversationSession.status == VoiceConversationStatus.ACTIVE.value
        filters.append(is_active if active else ~is_active)
    if transport_kind:
        filters.append(ToolModel.code == transport_kind)
    if topic_id is not None:
        filters.append(
            select(ConversationRound.id)
            .where(
                ConversationRound.voice_session_id == VoiceConversationSession.id,
                ConversationRound.topic_id == topic_id,
            )
            .exists()
        )
    if date_from is not None:
        filters.append(
            VoiceConversationSession.started_at
            >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        filters.append(
            VoiceConversationSession.started_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )

    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        matching_participant = (
            select(RoomUser.room_id)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(
                RoomUser.room_id == VoiceConversationSession.messenger_room_id,
                or_(
                    MessengerUser.display_name.ilike(pattern),
                    MessengerUser.external_id.ilike(pattern),
                ),
            )
            .exists()
        )
        matching_message = (
            select(ConversationRoundMessage.round_id)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .join(
                ConversationRound,
                ConversationRound.id == ConversationRoundMessage.round_id,
            )
            .where(
                ConversationRound.voice_session_id == VoiceConversationSession.id,
                Message.text.ilike(pattern),
            )
            .exists()
        )
        filters.append(
            or_(
                Room.external_id.ilike(pattern),
                Room.label.ilike(pattern),
                ToolModel.code.ilike(pattern),
                Agent.first_name.ilike(pattern),
                Agent.last_name.ilike(pattern),
                Agent.code.ilike(pattern),
                matching_participant,
                matching_message,
            )
        )
    return filters


def _session_joins(statement: Any) -> Any:
    return (
        statement.outerjoin(Room, Room.id == VoiceConversationSession.messenger_room_id)
        .outerjoin(Connection, Connection.id == Room.connection_id)
        .outerjoin(ToolModel, ToolModel.id == Connection.tool_id)
        .outerjoin(Agent, Agent.id == Connection.agent_id)
    )


async def _round_texts(
    round_ids: list[UUID],
) -> dict[UUID, tuple[str | None, str | None]]:
    grouped: dict[UUID, dict[str, list[tuple[int, int, str]]]] = defaultdict(
        lambda: {"input": [], "output": []}
    )
    if not round_ids:
        return {}
    rows = (
        await get_db().execute(
            select(
                ConversationRoundMessage.round_id,
                ConversationRoundMessage.role,
                ConversationRoundMessage.response_sequence,
                ConversationRoundMessage.sequence,
                Message.text,
            )
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .where(ConversationRoundMessage.round_id.in_(round_ids))
        )
    ).all()
    for round_id, role, response_sequence, sequence, text in rows:
        grouped[round_id][role].append(
            (int(response_sequence or 0), int(sequence), str(text))
        )
    result: dict[UUID, tuple[str | None, str | None]] = {}
    for round_id, roles in grouped.items():
        inputs = "\n".join(item[2] for item in sorted(roles["input"])) or None
        outputs = "\n".join(item[2] for item in sorted(roles["output"])) or None
        result[round_id] = inputs, outputs
    return result


async def _caller_names(session_ids: list[UUID]) -> dict[UUID, str]:
    """Resolve remote audio-room members without confusing them with the agent."""

    if not session_ids:
        return {}
    rows = (
        await get_db().execute(
            select(
                VoiceConversationSession.id,
                MessengerUser.id,
                MessengerUser.display_name,
                MessengerUser.external_id,
                MessengerUser.agent_id,
                Connection.agent_id,
            )
            .join(Room, Room.id == VoiceConversationSession.messenger_room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .join(RoomUser, RoomUser.room_id == Room.id)
            .join(MessengerUser, MessengerUser.id == RoomUser.user_id)
            .where(VoiceConversationSession.id.in_(session_ids))
            .execution_options(include_historized=True)
        )
    ).all()
    grouped: dict[UUID, list[str]] = defaultdict(list)
    for session_id, _user_id, display_name, external_id, member_agent_id, agent_id in rows:
        if member_agent_id == agent_id:
            continue
        name = str(display_name or external_id or "").strip()
        if name and name not in grouped[session_id]:
            grouped[session_id].append(name)
    return {
        session_id: ", ".join(names)
        for session_id, names in grouped.items()
        if names
    }


async def _turns_by_session(
    session_ids: list[UUID],
) -> dict[UUID, list[VoiceConversationTurnRead]]:
    if not session_ids:
        return {}
    llm_counts = (
        select(
            LLMCall.conversation_round_id.label("round_id"),
            func.count(LLMCall.id).label("llm_call_count"),
        )
        .where(LLMCall.conversation_round_id.is_not(None))
        .group_by(LLMCall.conversation_round_id)
        .subquery()
    )
    rows = (
        await get_db().execute(
            select(ConversationRound, func.coalesce(llm_counts.c.llm_call_count, 0))
            .outerjoin(llm_counts, llm_counts.c.round_id == ConversationRound.id)
            .where(ConversationRound.voice_session_id.in_(session_ids))
            .order_by(
                ConversationRound.voice_session_id.asc(),
                ConversationRound.sequence.asc(),
            )
        )
    ).all()
    texts = await _round_texts([round_.id for round_, _count in rows])
    grouped: dict[UUID, list[VoiceConversationTurnRead]] = {
        session_id: [] for session_id in session_ids
    }
    for round_, llm_call_count in rows:
        session_id = round_.voice_session_id
        if session_id is None:
            continue
        transcript, assistant_response = texts.get(round_.id, (None, None))
        grouped[session_id].append(
            VoiceConversationTurnRead(
                id=round_.id,
                sequence=int(round_.sequence or 0),
                run_id=round_.id,
                source_turn_id=round_.source_round_id,
                resolved_by_turn_id=round_.resolved_by_round_id,
                topic_id=round_.topic_id,
                transcript=transcript,
                effective_objective=round_.effective_objective,
                assistant_response=assistant_response,
                status=round_.status,
                error=round_.last_error,
                started_at=round_.created_at,
                first_text_at=round_.first_text_at,
                first_audio_at=round_.first_audio_at,
                interrupted_at=round_.interrupted_at,
                completed_at=round_.finished_at,
                llm_call_count=int(llm_call_count),
            )
        )
    return grouped


def _summary_from_row(
    row: Any,
    *,
    caller_name: str | None = None,
) -> VoiceConversationSummary:
    (
        session,
        connection_id,
        external_room_id,
        transport_kind,
        agent_id,
        first_name,
        last_name,
        agent_code,
        topic_id,
        turn_count,
        interrupted_count,
        failed_count,
    ) = row
    return VoiceConversationSummary(
        id=session.id,
        agent_id=int(agent_id) if agent_id is not None else None,
        agent_name=f"{first_name or ''} {last_name or ''}".strip() or None,
        agent_code=agent_code,
        caller_name=caller_name,
        connection_id=int(connection_id) if connection_id is not None else None,
        topic_id=topic_id,
        transport_kind=str(transport_kind or ""),
        room_id=str(external_room_id or ""),
        language="fr",
        status=session.status,
        started_at=session.started_at,
        finished_at=session.finished_at,
        duration=_duration_seconds(session.started_at, session.finished_at),
        turn_count=int(turn_count),
        interrupted_count=int(interrupted_count),
        failed_count=int(failed_count),
    )


def _summary_statement(stats: Any) -> Any:
    return _session_joins(
        select(
            VoiceConversationSession,
            Room.connection_id,
            Room.external_id,
            ToolModel.code,
            Connection.agent_id,
            Agent.first_name,
            Agent.last_name,
            Agent.code,
            _latest_topic_id(),
            func.coalesce(stats.c.turn_count, 0),
            func.coalesce(stats.c.interrupted_count, 0),
            func.coalesce(stats.c.failed_count, 0),
        )
    ).outerjoin(stats, stats.c.session_id == VoiceConversationSession.id)


async def list_conversations(
    *,
    page: int,
    page_size: int,
    agent_id: int | None = None,
    status: str | None = None,
    active: bool | None = None,
    transport_kind: str | None = None,
    topic_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> VoiceConversationPage:
    """Return the newest durable voice sessions matching monitoring filters."""

    filters = _session_filters(
        agent_id=agent_id,
        status=status,
        active=active,
        transport_kind=transport_kind,
        topic_id=topic_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    if agent_ids is not None:
        filters.append(Connection.agent_id.in_(agent_ids))
    db = get_db()
    total = int(
        await db.scalar(
            _session_joins(select(func.count(VoiceConversationSession.id))).where(*filters)
        )
        or 0
    )
    summary_filters = _session_filters(
        agent_id=agent_id,
        status=None,
        active=None,
        transport_kind=transport_kind,
        topic_id=topic_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    if agent_ids is not None:
        summary_filters.append(Connection.agent_id.in_(agent_ids))
    active_count, completed, cancelled, errors = (
        await db.execute(
            _session_joins(
                select(
                    func.count(VoiceConversationSession.id).filter(
                        VoiceConversationSession.status
                        == VoiceConversationStatus.ACTIVE.value
                    ),
                    func.count(VoiceConversationSession.id).filter(
                        VoiceConversationSession.status
                        == VoiceConversationStatus.COMPLETED.value
                    ),
                    func.count(VoiceConversationSession.id).filter(
                        VoiceConversationSession.status
                        == VoiceConversationStatus.CANCELLED.value
                    ),
                    func.count(VoiceConversationSession.id).filter(
                        VoiceConversationSession.status
                        == VoiceConversationStatus.ERROR.value
                    ),
                )
            ).where(*summary_filters)
        )
    ).one()
    stats = _round_stats()
    rows = (
        await db.execute(
            _summary_statement(stats)
            .where(*filters)
            .order_by(
                VoiceConversationSession.started_at.desc(),
                VoiceConversationSession.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .execution_options(include_historized=True)
        )
    ).all()
    session_ids = [row[0].id for row in rows]
    turns_by_session = await _turns_by_session(session_ids)
    caller_names = await _caller_names(session_ids)
    items: list[VoiceConversationDetail] = []
    for row in rows:
        session = row[0]
        items.append(
            VoiceConversationDetail(
                **_summary_from_row(
                    row,
                    caller_name=caller_names.get(session.id),
                ).model_dump(),
                error=session.error,
                turns=turns_by_session[session.id],
            )
        )
    return VoiceConversationPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        summary=VoiceConversationOverview(
            active=int(active_count),
            completed=int(completed),
            cancelled=int(cancelled),
            errors=int(errors),
        ),
    )


async def get_conversation(conversation_id: UUID) -> VoiceConversationDetail | None:
    """Return one call with every persisted round in chronological order."""

    stats = _round_stats()
    row = (
        await get_db().execute(
            _summary_statement(stats)
            .where(VoiceConversationSession.id == conversation_id)
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if row is None:
        return None
    session = row[0]
    turns = await _turns_by_session([conversation_id])
    caller_names = await _caller_names([conversation_id])
    return VoiceConversationDetail(
        **_summary_from_row(
            row,
            caller_name=caller_names.get(conversation_id),
        ).model_dump(),
        error=session.error,
        turns=turns[conversation_id],
    )


async def get_turn(turn_id: UUID) -> VoiceConversationTurnDetail | None:
    """Load one audio round and its complete driver result on demand."""

    llm_count = (
        select(func.count(LLMCall.id))
        .where(LLMCall.conversation_round_id == turn_id)
        .scalar_subquery()
    )
    row = (
        await get_db().execute(
            _session_joins(
                select(
                    ConversationRound,
                    VoiceConversationSession,
                    Room.connection_id,
                    Room.external_id,
                    ToolModel.code,
                    Connection.agent_id,
                    Agent.first_name,
                    Agent.last_name,
                    func.coalesce(llm_count, 0),
                ).join(
                    VoiceConversationSession,
                    VoiceConversationSession.id == ConversationRound.voice_session_id,
                )
            )
            .where(ConversationRound.id == turn_id)
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if row is None:
        return None
    (
        round_,
        session,
        connection_id,
        external_room_id,
        transport_kind,
        agent_id,
        first_name,
        last_name,
        llm_call_count,
    ) = row
    transcript, assistant_response = (
        await _round_texts([round_.id])
    ).get(round_.id, (None, None))
    caller_names = await _caller_names([session.id])
    return VoiceConversationTurnDetail(
        id=round_.id,
        session_id=session.id,
        sequence=int(round_.sequence or 0),
        run_id=round_.id,
        source_turn_id=round_.source_round_id,
        resolved_by_turn_id=round_.resolved_by_round_id,
        topic_id=round_.topic_id,
        transcript=transcript,
        effective_objective=round_.effective_objective,
        assistant_response=assistant_response,
        status=round_.status,
        error=round_.last_error,
        started_at=round_.created_at,
        first_text_at=round_.first_text_at,
        first_audio_at=round_.first_audio_at,
        interrupted_at=round_.interrupted_at,
        completed_at=round_.finished_at,
        llm_call_count=int(llm_call_count),
        agent_id=int(agent_id) if agent_id is not None else None,
        agent_name=f"{first_name or ''} {last_name or ''}".strip() or None,
        caller_name=caller_names.get(session.id),
        connection_id=int(connection_id) if connection_id is not None else None,
        transport_kind=str(transport_kind or ""),
        room_id=str(external_room_id or ""),
        language="fr",
        execution_result=round_.execution_result,
    )


__all__ = ["get_conversation", "get_turn", "list_conversations"]
