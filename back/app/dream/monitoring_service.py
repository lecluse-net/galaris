"""Read-only projections used by the Dream monitoring interface."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast as type_cast
from uuid import UUID

from sqlalchemy import String, and_, case, cast, exists, false, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH

from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.connection import Connection
from app.llm import LLMCall, llm_call_service
from app.llm.schemas import LLMCallRead
from app.messenger import Interaction, Message, Room
from app.task import Task, TaskStatus
from app.voice import VoiceConversationSession
from core.database import get_db

from .models import DreamReceipt
from .registry import mechanisms as registered_mechanisms
from .scheduler import runtime_snapshot
from .service import receipt_correlation_ref
from .schemas import (
    DreamMechanismSummary,
    DreamOverview,
    DreamReceiptDetail,
    DreamReceiptPage,
    DreamReceiptSummary,
    DreamRuntimeView,
    DreamTopicAssignmentAudit,
    TopicAssignmentAction,
    TopicAssignmentSubjectKind,
)


_TASK_MEMORY_KEY = "memory.extract_task"
_SUBJECT_PREVIEW_MAX_CHARS = 240
_MEMORY_EXTRACTION_KEYS = (
    _TASK_MEMORY_KEY,
    "memory.extract_conversation_round",
    "memory.extract_voice_turn",
)
_TOPIC_APPROVAL_INTERACTION = "topic_creation_approval"
_TOPIC_SUBJECT_LIMIT = 200


def _payload_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return type_cast(dict[str, Any], value)


def _payload_topic_id(payload: dict[str, Any]) -> UUID | None:
    diagnostics = _payload_mapping(payload.get("diagnostics"))
    decision = _payload_mapping(payload.get("decision"))
    raw_topic_id = diagnostics.get("topic_id") or decision.get("topic_id")
    try:
        return UUID(str(raw_topic_id)) if raw_topic_id else None
    except ValueError:
        return None


def _decision_audit_fields(
    payload: dict[str, Any],
    *,
    forced_action: str | None = None,
) -> tuple[TopicAssignmentAction | None, str | None, float | None]:
    diagnostics = _payload_mapping(payload.get("diagnostics"))
    decision = _payload_mapping(payload.get("decision"))
    classification = _payload_mapping(diagnostics.get("classification"))
    semantic = _payload_mapping(diagnostics.get("semantic_continuity"))
    raw_action = forced_action or diagnostics.get("resolution") or decision.get("action")
    action: TopicAssignmentAction | None = (
        raw_action if raw_action in ("continuity", "reuse", "create") else None
    )
    if action == "continuity":
        raw_reason = semantic.get("reason")
        raw_confidence = semantic.get("same_topic_probability")
    else:
        raw_reason = decision.get("reason") or classification.get("reason")
        raw_confidence = decision.get("confidence")
        if raw_confidence is None:
            raw_confidence = classification.get("confidence")
    reason = str(raw_reason).strip()[:500] if raw_reason else None
    try:
        confidence = float(raw_confidence) if raw_confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        confidence = None
    return action, reason, confidence


async def _append_round_subjects(
    round_id: UUID,
    *,
    refs: list[tuple[str, str]],
    seen: set[tuple[str, str]],
    round_queue: list[UUID],
) -> None:
    key = ("conversation_round", str(round_id))
    if key in seen or len(refs) >= _TOPIC_SUBJECT_LIMIT:
        return
    seen.add(key)
    refs.append(key)
    round_ = await get_db().get(ConversationRound, round_id)
    if round_ is not None and round_.source_round_id is not None:
        round_queue.append(round_.source_round_id)
    message_ids = list(
        (
            await get_db().scalars(
                select(ConversationRoundMessage.message_id)
                .where(ConversationRoundMessage.round_id == round_id)
                .order_by(ConversationRoundMessage.sequence)
            )
        ).all()
    )
    for message_id in message_ids:
        message_key = ("message", str(message_id))
        if message_key not in seen and len(refs) < _TOPIC_SUBJECT_LIMIT:
            seen.add(message_key)
            refs.append(message_key)


async def _topic_subject_refs(
    subject_kind: TopicAssignmentSubjectKind,
    subject_id: UUID,
) -> list[tuple[str, str]]:
    """Return direct then inherited subjects which may own the Dream decision."""

    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    round_queue: list[UUID] = []

    def append(kind: str, identifier: UUID) -> None:
        key = (kind, str(identifier))
        if key not in seen and len(refs) < _TOPIC_SUBJECT_LIMIT:
            seen.add(key)
            refs.append(key)

    if subject_kind == "task":
        task_queue = [subject_id]
        visited_tasks: set[UUID] = set()
        while task_queue and len(refs) < _TOPIC_SUBJECT_LIMIT:
            task_id = task_queue.pop(0)
            if task_id in visited_tasks:
                continue
            visited_tasks.add(task_id)
            append("task", task_id)
            task = await get_db().get(Task, task_id)
            if task is not None:
                for related_id in (task.parent_id, task.source_task_id):
                    if related_id is not None:
                        task_queue.append(related_id)
            round_queue.extend(
                list(
                    (
                        await get_db().scalars(
                            select(ConversationTaskLink.round_id).where(
                                ConversationTaskLink.task_id == task_id
                            )
                        )
                    ).all()
                )
            )
    elif subject_kind == "message":
        append("message", subject_id)
        round_queue.extend(
            list(
                (
                    await get_db().scalars(
                        select(ConversationRoundMessage.round_id).where(
                            ConversationRoundMessage.message_id == subject_id
                        )
                    )
                ).all()
            )
        )
    elif subject_kind == "conversation_round":
        round_queue.append(subject_id)
    else:
        append("voice_session", subject_id)
        round_queue.extend(
            list(
                (
                    await get_db().scalars(
                        select(ConversationRound.id).where(
                            ConversationRound.voice_session_id == subject_id
                        )
                    )
                ).all()
            )
        )

    visited_rounds: set[UUID] = set()
    while round_queue and len(refs) < _TOPIC_SUBJECT_LIMIT:
        round_id = round_queue.pop(0)
        if round_id in visited_rounds:
            continue
        visited_rounds.add(round_id)
        await _append_round_subjects(
            round_id,
            refs=refs,
            seen=seen,
            round_queue=round_queue,
        )
    return refs


def _interaction_topic_id(interaction: Interaction) -> tuple[UUID | None, str | None]:
    resolution = _payload_mapping(interaction.resolution)
    option_id = str(resolution.get("option_id") or "")
    metadata = _payload_mapping(interaction.metadata_)
    topic_payload = _payload_mapping(metadata.get("topic_payload"))
    if option_id == "create":
        return _payload_topic_id(topic_payload), "create"
    if option_id.startswith("reuse:"):
        try:
            return UUID(option_id.removeprefix("reuse:")), "reuse"
        except ValueError:
            return None, None
    return None, None


def _interaction_receipt_id(interaction: Interaction) -> UUID | None:
    metadata = _payload_mapping(interaction.metadata_)
    value = str(metadata.get("idempotency_key") or "")
    prefix = "topic-approval:"
    if not value.startswith(prefix):
        return None
    try:
        return UUID(value.removeprefix(prefix))
    except ValueError:
        return None


async def get_topic_assignment_audit(
    *,
    topic_id: UUID,
    subject_kind: TopicAssignmentSubjectKind,
    subject_id: UUID,
) -> DreamTopicAssignmentAudit:
    """Explain the current Topic using direct and inherited Dream evidence."""

    refs = await _topic_subject_refs(subject_kind, subject_id)
    rank = {key: index for index, key in enumerate(refs)}
    if not refs:
        return DreamTopicAssignmentAudit(
            topic_id=topic_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            origin="manual",
        )
    subject_filter = or_(
        *(
            and_(
                DreamReceipt.subject_kind == kind,
                DreamReceipt.subject_id == identifier,
            )
            for kind, identifier in refs
        )
    )
    receipts = list(
        (
            await get_db().scalars(
                select(DreamReceipt)
                .where(
                    DreamReceipt.status == "success",
                    DreamReceipt.mechanism_key.like("topic.classify_%"),
                    subject_filter,
                )
                .order_by(DreamReceipt.updated_at.desc(), DreamReceipt.id)
            )
        ).all()
    )
    matching_receipts = [
        receipt
        for receipt in receipts
        if receipt.prepared_payload is not None
        and _payload_topic_id(dict(receipt.prepared_payload)) == topic_id
    ]

    interaction_filter = or_(
        *(
            and_(
                Interaction.metadata_["subject_kind"].as_string() == kind,
                Interaction.metadata_["subject_id"].as_string() == identifier,
            )
            for kind, identifier in refs
        )
    )
    interactions = list(
        (
            await get_db().scalars(
                select(Interaction)
                .where(
                    Interaction.kind == _TOPIC_APPROVAL_INTERACTION,
                    Interaction.status == "RESOLVED",
                    interaction_filter,
                )
                .order_by(Interaction.resolved_at.desc(), Interaction.id)
            )
        ).all()
    )
    matching_interactions: list[tuple[Interaction, str]] = []
    for interaction in interactions:
        resolved_topic_id, forced_action = _interaction_topic_id(interaction)
        if resolved_topic_id == topic_id and forced_action is not None:
            matching_interactions.append((interaction, forced_action))
    if matching_interactions:
        interaction, forced_action = min(
            matching_interactions,
            key=lambda item: rank.get(
                (
                    str(item[0].metadata_.get("subject_kind") or ""),
                    str(item[0].metadata_.get("subject_id") or ""),
                ),
                _TOPIC_SUBJECT_LIMIT,
            ),
        )
        receipt_id = _interaction_receipt_id(interaction)
        receipt = (
            next((item for item in receipts if item.id == receipt_id), None)
            if receipt_id is not None
            else None
        )
        payload = _payload_mapping(interaction.metadata_.get("topic_payload"))
        action, reason, confidence = _decision_audit_fields(
            payload,
            forced_action=forced_action,
        )
        return DreamTopicAssignmentAudit(
            topic_id=topic_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            origin="dream",
            reason=reason,
            action=action,
            confidence=confidence,
            human_confirmed=True,
            dream_receipt_id=receipt_id,
            dream_mechanism_key=receipt.mechanism_key if receipt else None,
            dream_subject_kind=receipt.subject_kind if receipt else None,
            dream_subject_id=receipt.subject_id if receipt else None,
            decided_at=interaction.resolved_at,
        )
    if matching_receipts:
        receipt = min(
            matching_receipts,
            key=lambda item: rank.get(
                (item.subject_kind, item.subject_id), _TOPIC_SUBJECT_LIMIT
            ),
        )
        action, reason, confidence = _decision_audit_fields(
            dict(receipt.prepared_payload or {})
        )
        return DreamTopicAssignmentAudit(
            topic_id=topic_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            origin="dream",
            reason=reason,
            action=action,
            confidence=confidence,
            dream_receipt_id=receipt.id,
            dream_mechanism_key=receipt.mechanism_key,
            dream_subject_kind=receipt.subject_kind,
            dream_subject_id=receipt.subject_id,
            decided_at=receipt.updated_at,
        )
    return DreamTopicAssignmentAudit(
        topic_id=topic_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        origin="manual",
    )


async def get_topic_assignment_agent_id(
    *,
    subject_kind: TopicAssignmentSubjectKind,
    subject_id: UUID,
) -> int | None:
    """Resolve the Agent owning a topic-assignment subject."""

    if subject_kind == "task":
        return await get_db().scalar(
            select(Task.agent_id).where(Task.id == subject_id)
        )
    if subject_kind == "message":
        return await get_db().scalar(
            select(Connection.agent_id)
            .join(Message, Message.connection_id == Connection.id)
            .where(Message.id == subject_id)
        )
    if subject_kind == "conversation_round":
        return await get_db().scalar(
            select(Connection.agent_id)
            .join(Room, Room.connection_id == Connection.id)
            .join(ConversationRound, ConversationRound.room_id == Room.id)
            .where(ConversationRound.id == subject_id)
        )
    return await get_db().scalar(
        select(Connection.agent_id)
        .join(Room, Room.connection_id == Connection.id)
        .join(
            VoiceConversationSession,
            VoiceConversationSession.messenger_room_id == Room.id,
        )
        .where(VoiceConversationSession.id == subject_id)
    )


def _effective_result_count(receipt: DreamReceipt) -> int:
    """Return only the result count persisted by the applying mechanism."""

    return max(0, int(receipt.result_count))


async def get_runtime() -> DreamRuntimeView:
    """Expose the current in-process scheduler state."""

    snapshot = await runtime_snapshot()
    return DreamRuntimeView(
        status=snapshot.status,
        phase=snapshot.phase,
        reason=snapshot.reason,
        worker_running=snapshot.worker_running,
        current_mechanism=snapshot.current_mechanism,
        current_subject_kind=snapshot.current_subject_kind,
        current_subject_id=snapshot.current_subject_id,
        last_cycle_at=snapshot.last_cycle_at,
        last_cycle_finished_at=snapshot.last_cycle_finished_at,
        next_cycle_at=snapshot.next_cycle_at,
        state_changed_at=snapshot.state_changed_at,
        cycle_count=snapshot.cycle_count,
        last_error_type=snapshot.last_error_type,
    )


async def get_overview() -> DreamOverview:
    """Summarize persisted receipts and the current in-process scheduler state."""

    runtime = await get_runtime()
    active_mechanisms = tuple(
        mechanism
        for mechanism in registered_mechanisms()
        if getattr(mechanism, "monitoring_visible", True)
    )
    active_receipts = (
        DreamReceipt.mechanism_key.in_(
            mechanism.key for mechanism in active_mechanisms
        )
        if active_mechanisms
        else false()
    )
    aggregate_rows = (
        await get_db().execute(
            select(
                DreamReceipt.mechanism_key,
                DreamReceipt.status,
                func.count(DreamReceipt.id),
                func.coalesce(func.sum(DreamReceipt.result_count), 0),
                func.coalesce(func.sum(DreamReceipt.cost), 0.0),
            )
            .where(active_receipts)
            .group_by(
                DreamReceipt.mechanism_key,
                DreamReceipt.status,
            )
            .order_by(DreamReceipt.mechanism_key)
        )
    ).all()
    terminal_tasks = int(
        await get_db().scalar(
            select(func.count(Task.id)).where(
                Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR))
            )
        )
        or 0
    )
    applied_operations = DreamReceipt.prepared_payload["application"]["operations"]
    create_operation_count = case(
        (
            func.jsonb_typeof(applied_operations) == "array",
            func.jsonb_array_length(
                func.jsonb_path_query_array(
                    applied_operations,
                    cast('$[*] ? (@.action == "CREATE")', JSONPATH),
                )
            ),
        ),
        else_=0,
    )
    link_operation_count = case(
        (
            func.jsonb_typeof(applied_operations) == "array",
            func.jsonb_array_length(
                func.jsonb_path_query_array(
                    applied_operations,
                    cast('$[*] ? (@.action == "LINK")', JSONPATH),
                )
            ),
        ),
        else_=0,
    )
    memories_created, memories_linked = (
        await get_db().execute(
            select(
                func.coalesce(func.sum(create_operation_count), 0),
                func.coalesce(func.sum(link_operation_count), 0),
            ).where(
                DreamReceipt.status == "success",
                DreamReceipt.mechanism_key.in_(_MEMORY_EXTRACTION_KEYS),
            )
        )
    ).one()

    grouped: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {
            "pending": 0,
            "running": 0,
            "retry": 0,
            "success": 0,
            "error": 0,
            "result_count": 0,
            "cost": 0.0,
        }
    )
    for key, status, count, result_count, cost in aggregate_rows:
        values = grouped[str(key)]
        values[str(status)] = int(count)
        values["result_count"] = int(values["result_count"]) + int(result_count)
        values["cost"] = float(values["cost"]) + float(cost)

    for mechanism in active_mechanisms:
        grouped[mechanism.key]["pending"] = await mechanism.count_pending()

    mechanisms: list[DreamMechanismSummary] = []
    for mechanism in active_mechanisms:
        values = grouped[mechanism.key]
        mechanisms.append(
            DreamMechanismSummary(
                mechanism_key=mechanism.key,
                pending=int(values["pending"]),
                running=int(values["running"]),
                retry=int(values["retry"]),
                success=int(values["success"]),
                error=int(values["error"]),
                result_count=int(values["result_count"]),
                cost=float(values["cost"]),
            )
        )
    completed_operations = sum(
        item.success + item.error for item in mechanisms
    )
    pending_operations = sum(
        item.pending + item.running + item.retry for item in mechanisms
    )
    task_memory_values = grouped[_TASK_MEMORY_KEY]
    unscanned_tasks = sum(
        int(task_memory_values[state]) for state in ("pending", "running", "retry")
    )
    return DreamOverview(
        runtime=runtime,
        total_operations=completed_operations + pending_operations,
        completed_operations=completed_operations,
        pending_operations=pending_operations,
        terminal_tasks=terminal_tasks,
        unscanned_tasks=unscanned_tasks,
        running_receipts=sum(item.running for item in mechanisms),
        retry_receipts=sum(item.retry for item in mechanisms),
        successful_receipts=sum(item.success for item in mechanisms),
        error_receipts=sum(item.error for item in mechanisms),
        memories_created=int(memories_created),
        memories_linked=int(memories_linked),
        total_cost=sum(item.cost for item in mechanisms),
        mechanisms=mechanisms,
    )


def _receipt_filters(
    *,
    status: str | None,
    active: bool | None,
    date_from: date | None,
    date_to: date | None,
    mechanism: str | None,
    search: str | None,
) -> list[Any]:
    filters: list[Any] = []
    if status:
        filters.append(DreamReceipt.status == status)
    if active is True:
        filters.append(DreamReceipt.status == "running")
    elif active is False:
        filters.append(DreamReceipt.status != "running")
    if date_from is not None:
        filters.append(
            DreamReceipt.created_at
            >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        filters.append(
            DreamReceipt.created_at
            < datetime.combine(
                date_to + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
        )
    if mechanism:
        filters.append(DreamReceipt.mechanism_key == mechanism)
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        task_matches = exists(
            select(Task.id).where(
                DreamReceipt.subject_kind.in_(("task", "task_outcome")),
                cast(Task.id, String)
                == func.split_part(DreamReceipt.subject_id, ":", 1),
                or_(Task.label.ilike(pattern), Task.objective.ilike(pattern)),
            )
        )
        conversation_round_matches = exists(
            select(ConversationRoundMessage.round_id)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .where(
                DreamReceipt.subject_kind == "conversation_round",
                cast(ConversationRoundMessage.round_id, String)
                == DreamReceipt.subject_id,
                ConversationRoundMessage.role == "input",
                Message.text.ilike(pattern),
            )
        )
        message_matches = exists(
            select(Message.id).where(
                DreamReceipt.subject_kind == "message",
                cast(Message.id, String) == DreamReceipt.subject_id,
                Message.text.ilike(pattern),
            )
        )
        filters.append(
            or_(
                DreamReceipt.mechanism_key.ilike(pattern),
                DreamReceipt.subject_id.ilike(pattern),
                and_(
                    DreamReceipt.subject_kind.in_(("task", "task_outcome")),
                    task_matches,
                ),
                conversation_round_matches,
                message_matches,
            )
        )
    return filters


async def list_receipts(
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    active: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    mechanism: str | None = None,
    search: str | None = None,
) -> DreamReceiptPage:
    filters = _receipt_filters(
        status=status,
        active=active,
        date_from=date_from,
        date_to=date_to,
        mechanism=mechanism,
        search=search,
    )
    total = int(
        await get_db().scalar(
            select(func.count(DreamReceipt.id)).where(*filters)
        )
        or 0
    )
    receipts = list(
        (
            await get_db().scalars(
                select(DreamReceipt)
                .where(*filters)
                .order_by(
                    DreamReceipt.updated_at.desc(),
                    DreamReceipt.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    task_details = await _load_task_details(receipts)
    subject_previews = await _load_subject_previews(receipts)
    items = [
        _receipt_summary(
            receipt,
            task_details.get(receipt.subject_id.split(":", 1)[0]),
            subject_previews.get((receipt.subject_kind, receipt.subject_id)),
        )
        for receipt in receipts
    ]
    return DreamReceiptPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_receipt(receipt_id: UUID) -> DreamReceiptDetail | None:
    receipt = await get_db().get(DreamReceipt, receipt_id)
    if receipt is None:
        return None
    task_details = await _load_task_details([receipt])
    subject_previews = await _load_subject_previews([receipt])
    summary = _receipt_summary(
        receipt,
        task_details.get(receipt.subject_id.split(":", 1)[0]),
        subject_previews.get((receipt.subject_kind, receipt.subject_id)),
    )
    llm_calls = await _load_llm_calls(receipt)
    return DreamReceiptDetail(
        **summary.model_dump(),
        lease_owner=receipt.lease_owner,
        lease_expires_at=receipt.lease_expires_at,
        last_error=receipt.last_error,
        prepared_payload=receipt.prepared_payload,
        llm_calls=llm_calls,
    )


async def _load_llm_calls(receipt: DreamReceipt) -> list[LLMCallRead]:
    """Load every inference explicitly correlated with one Dream receipt.

    Older receipts predate explicit correlation. Their closed execution window remains a
    read-only compatibility path. Calls with an agent-run, conversation-round, process-run or
    incompatible Task lineage are excluded so foreground inference cannot leak into the detail.
    """

    calls = list(
        (
            await get_db().scalars(
                select(LLMCall)
                .where(
                    LLMCall.correlation_ref
                    == receipt_correlation_ref(receipt.id),
                )
                .order_by(LLMCall.started_at.desc(), LLMCall.id.desc())
                .limit(50)
            )
        ).all()
    )
    if calls:
        return await llm_call_service.serialize_calls(calls)

    legacy_filters = [
        LLMCall.correlation_ref.is_(None),
        LLMCall.started_at >= receipt.created_at,
        LLMCall.started_at <= receipt.updated_at,
        LLMCall.agent_run_id.is_(None),
        LLMCall.conversation_round_id.is_(None),
        LLMCall.process_run_id.is_(None),
    ]
    if receipt.subject_kind in ("task", "task_outcome"):
        try:
            task_id = UUID(receipt.subject_id.split(":", 1)[0])
        except ValueError:
            return []
        legacy_filters.append(LLMCall.task_id == task_id)
    else:
        legacy_filters.append(LLMCall.task_id.is_(None))
    legacy_calls = list(
        (
            await get_db().scalars(
                select(LLMCall)
                .where(*legacy_filters)
                .order_by(LLMCall.started_at.desc(), LLMCall.id.desc())
                .limit(50)
            )
        ).all()
    )
    return await llm_call_service.serialize_calls(legacy_calls)


async def _load_task_details(
    receipts: list[DreamReceipt],
) -> dict[str, tuple[str, str | None, str, int | None]]:
    task_ids: list[UUID] = []
    for receipt in receipts:
        if receipt.subject_kind not in ("task", "task_outcome"):
            continue
        try:
            task_ids.append(UUID(receipt.subject_id.split(":", 1)[0]))
        except ValueError:
            continue
    if not task_ids:
        return {}
    rows = (
        await get_db().execute(
            select(
                Task.id,
                Task.label,
                func.left(Task.objective, _SUBJECT_PREVIEW_MAX_CHARS),
                Task.status,
                Task.agent_id,
            ).where(Task.id.in_(task_ids))
        )
    ).all()
    return {
        str(task_id): (
            str(label),
            str(objective) if objective is not None else None,
            status.value,
            agent_id,
        )
        for task_id, label, objective, status, agent_id in rows
    }


async def _load_subject_previews(
    receipts: list[DreamReceipt],
) -> dict[tuple[str, str], str]:
    identifiers: dict[str, list[UUID]] = {
        "conversation_round": [],
        "message": [],
    }
    for receipt in receipts:
        if receipt.subject_kind not in identifiers:
            continue
        try:
            identifiers[receipt.subject_kind].append(UUID(receipt.subject_id))
        except ValueError:
            continue

    previews: dict[tuple[str, str], str] = {}
    round_ids = identifiers["conversation_round"]
    if round_ids:
        rows = (
            await get_db().execute(
                select(
                    ConversationRoundMessage.round_id,
                    func.left(Message.text, _SUBJECT_PREVIEW_MAX_CHARS),
                )
                .distinct(ConversationRoundMessage.round_id)
                .join(Message, Message.id == ConversationRoundMessage.message_id)
                .where(
                    ConversationRoundMessage.round_id.in_(round_ids),
                    ConversationRoundMessage.role == "input",
                    func.length(func.trim(Message.text)) > 0,
                )
                .order_by(
                    ConversationRoundMessage.round_id,
                    ConversationRoundMessage.sequence,
                    Message.created_at,
                    Message.id,
                )
            )
        ).all()
        previews.update(
            {
                ("conversation_round", str(round_id)): str(text)
                for round_id, text in rows
            }
        )

    message_ids = identifiers["message"]
    if message_ids:
        rows = (
            await get_db().execute(
                select(
                    Message.id,
                    func.left(Message.text, _SUBJECT_PREVIEW_MAX_CHARS),
                ).where(
                    Message.id.in_(message_ids),
                    func.length(func.trim(Message.text)) > 0,
                )
            )
        ).all()
        previews.update(
            {("message", str(message_id)): str(text) for message_id, text in rows}
        )
    return previews


def _receipt_summary(
    receipt: DreamReceipt,
    task_detail: tuple[str, str | None, str, int | None] | None,
    subject_preview: str | None,
) -> DreamReceiptSummary:
    effective_preview = subject_preview
    if task_detail is not None:
        effective_preview = task_detail[1] or task_detail[0]
    elif receipt.subject_kind == "attachment":
        source = (receipt.prepared_payload or {}).get("source", {})
        if isinstance(source, dict):
            name = type_cast(dict[str, object], source).get("name")
            effective_preview = name[:_SUBJECT_PREVIEW_MAX_CHARS] if isinstance(name, str) else None
    return DreamReceiptSummary(
        id=receipt.id,
        mechanism_key=receipt.mechanism_key,
        subject_kind=receipt.subject_kind,
        subject_id=receipt.subject_id,
        status=receipt.status,
        attempts=receipt.attempts,
        result_count=_effective_result_count(receipt),
        cost=receipt.cost,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
        available_at=receipt.available_at,
        subject_preview=effective_preview,
        task_label=task_detail[0] if task_detail is not None else None,
        task_status=task_detail[2] if task_detail is not None else None,
        agent_id=task_detail[3] if task_detail is not None else None,
    )


__all__ = [
    "get_overview",
    "get_receipt",
    "get_runtime",
    "get_topic_assignment_agent_id",
    "list_receipts",
]
