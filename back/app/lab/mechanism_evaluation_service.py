"""Durable, side-effect-free benchmarks for the Lab's AI mechanisms."""

from __future__ import annotations

from collections.abc import Collection
from app.llm import model_usages

import json
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select

from app.agent import Agent
from app.agent.evaluation import (
    PlannerLabConfiguration,
    planner_evaluation_system_prompt,
    default_planner_lab_configuration,
    resolve_planner_lab_configuration,
)
from app.connection import Connection
from app.conversation import inspect_conversation_round
from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
)
from app.dream.evaluation import (
    MemoryExtractionInput,
    MemoryExtractionLabConfiguration,
    MemoryExtractionLabOutput,
    default_memory_extraction_lab_configuration,
    resolve_memory_extraction_lab_configuration,
)
from app.dream.contracts import (
    MAX_MEMORY_EXTRACTION_CANDIDATES,
)
from app.dream.mechanisms.conversation_memory import (
    build_conversation_extraction_input,
    round_execution_context,
)
from app.dream.mechanisms.memory_extraction import existing_memories_from_hits
from app.dream.mechanisms.task_memory import (
    NOVELTY_MEMORY_TYPES,
    build_task_extraction_input,
)
from app.llm import LLM, LLMCall, LLMCallPurpose, llm_service
from app.llm import StructuredOutputRetry, run_structured
from app.memory import search_memory_detailed
from app.messenger import Message, Room
from app.process import ProcessRun
from app.task import Task, TaskMessage, TaskStatus, get_conversation_followup
from app.topic import Topic, service as topic_service
from app.topic.evaluation import (
    TopicDetectionLabConfiguration,
    TopicDetectionLabInput,
    TopicDetectionLabTopic,
    default_topic_lab_configuration,
    resolve_topic_lab_configuration,
)
from app.topic.sequential_detection import MAX_MESSAGES
from app.voice import inspect_voice_turn
from core.database import get_db
from .transactions import publish
from core.i18n import tr

from .mechanism_registry import (
    MECHANISMS,
    MechanismDefinition,
    build_executor_benchmark_prompt,
    evaluate_mechanism,
    get_mechanism,
)
from . import executor_prompt_service
from .run_publication import finish_owned_run, publish_case, publish_judgment
from .inference_profile import model_binding, benchmark_fingerprints
from .run_lease import keep_lease
from .mechanism_rubrics import get_rubric
from .run_claims import claim_next_run
from .run_inference import evaluate_claim, evaluate_judgment
from .capture_service import check_capture
from .contracts import CONTRACTS, LabInput, capture_input, resolve_input, validate_parameters
from .schemas import LabInputPreview
from .models import (
    LabEvaluationCase,
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
)
from .schemas import (
    BenchmarkAnalysisContent,
    DispatcherCaseImport,
    EvaluationCaseCreate,
    EvaluationCaseRead,
    EvaluationDatasetRead,
    EvaluationDatasetUpdate,
    ExecutorCaseImport,
    EvaluationMechanism,
    EvaluationRunAnalysisRequest,
    EvaluationRunCaseRead,
    EvaluationRunDetail,
    EvaluationRunRead,
    EvaluationRunStart,
    MechanismCaseImport,
    MechanismCaseUpdate,
    MechanismDatasetCreate,
    MechanismDescriptorRead,
    MechanismExpectedGenerate,
    MechanismExpectedGenerated,
    MemoryExtractionDatasetConfigurationUpdate,
    MemoryExtractionPromptDefaultRead,
    MechanismSourceCandidate,
    TopicMessageAgentRead,
    TopicMessagePersonRead,
    TopicMessagePreview,
    TopicMessageRangeImport,
    TopicMessageRangePreview,
    TopicDatasetConfigurationUpdate,
    PlannerDatasetConfigurationUpdate,
    PlannerPromptDefaultRead,
)


_TERMINAL_RUN_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
# LLMCall uses ``completed``; ``success`` remains readable for legacy captures.
_SUCCESS_CALL_STATUSES = ("completed", "success")
_AUTOMATIC_CASE_NAME_MAX_LENGTH = 96


class RevisionConflictError(RuntimeError):
    """Raised when an editor attempts to overwrite a newer revision."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compact_automatic_case_name(*parts: str) -> str:
    """Build a readable list label without copying a full source payload into it."""
    label = " · ".join(normalized for part in parts if (normalized := " ".join(part.split())))
    if len(label) <= _AUTOMATIC_CASE_NAME_MAX_LENGTH:
        return label
    return f"{label[: _AUTOMATIC_CASE_NAME_MAX_LENGTH - 1].rstrip()}…"


def _llm_snapshot(llm: LLM | None) -> dict[str, Any]:
    if llm is None:
        return {}
    return {
        "id": llm.id,
        "binding": model_binding(llm),
        "code": llm.code,
        "label": llm.label,
        "model": llm.llm_name,
        "provider": llm.provider.name,
    }


def _topic_configuration_dump(
    configuration: TopicDetectionLabConfiguration,
) -> dict[str, Any]:
    return configuration.model_dump(mode="json", by_alias=True)


async def _topic_configuration(
    dataset: LabEvaluationDataset,
) -> TopicDetectionLabConfiguration:
    return await resolve_topic_lab_configuration(dataset.configuration)


def _memory_extraction_configuration_dump(
    configuration: MemoryExtractionLabConfiguration,
) -> dict[str, Any]:
    return configuration.model_dump(mode="json", by_alias=True)


async def _memory_extraction_configuration(
    dataset: LabEvaluationDataset,
) -> MemoryExtractionLabConfiguration:
    return await resolve_memory_extraction_lab_configuration(dataset.configuration)


def _planner_configuration_dump(
    configuration: PlannerLabConfiguration,
) -> dict[str, Any]:
    return configuration.model_dump(mode="json", by_alias=True)


async def _planner_configuration(
    dataset: LabEvaluationDataset,
) -> PlannerLabConfiguration:
    return await resolve_planner_lab_configuration(dataset.configuration)


def list_mechanisms() -> list[MechanismDescriptorRead]:
    return [
        MechanismDescriptorRead(
            key=definition.key,
            contract=CONTRACTS[definition.key].descriptor(),
            configuration_schema=configuration_schema(definition.key),
            algorithm=algorithm_description(definition.key),
            input_format=definition.input_format,
            output_format=definition.output_format,
            source_import=definition.source_import and definition.executor is None,
            executor=definition.executor,
        )
        for definition in MECHANISMS.values()
    ]


async def dataset_read(dataset: LabEvaluationDataset) -> EvaluationDatasetRead:
    counts = (
        await get_db().execute(
            select(
                func.count(LabEvaluationCase.id),
                func.count(LabEvaluationCase.id).filter(
                    LabEvaluationCase.readiness == "ready",
                    LabEvaluationCase.enabled.is_(True),
                ),
            ).where(
                LabEvaluationCase.dataset_id == dataset.id,
                LabEvaluationCase.deleted_at.is_(None),
            )
        )
    ).one()
    configuration = dataset.configuration
    if dataset.mechanism == "planner":
        configuration = _planner_configuration_dump(await _planner_configuration(dataset))
    elif dataset.mechanism == "topic_classification":
        configuration = _topic_configuration_dump(await _topic_configuration(dataset))
    elif dataset.mechanism == "memory_extraction":
        configuration = _memory_extraction_configuration_dump(
            await _memory_extraction_configuration(dataset)
        )
    return EvaluationDatasetRead(
        id=dataset.id,
        revision=dataset.revision,
        mechanism=dataset.mechanism,
        name=dataset.name,
        description=dataset.description,
        purpose=dataset.purpose,
        prompt_suffix=dataset.prompt_suffix,
        configuration=configuration,
        parameters=dataset.parameters,
        case_count=int(counts[0] or 0),
        ready_case_count=int(counts[1] or 0),
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


async def _dataset(mechanism: str, dataset_id: UUID) -> LabEvaluationDataset:
    dataset = await get_db().scalar(
        LabEvaluationDataset.histo_filter(
            select(LabEvaluationDataset).where(
                LabEvaluationDataset.id == dataset_id,
                LabEvaluationDataset.mechanism == mechanism,
            )
        )
    )
    if dataset is None:
        raise LookupError(await tr("evaluation_api.errors.dataset_not_found"))
    return dataset


async def _case(mechanism: str, case_id: UUID) -> LabEvaluationCase:
    row = await get_db().scalar(
        LabEvaluationCase.histo_filter(
            select(LabEvaluationCase)
            .join(LabEvaluationDataset, LabEvaluationDataset.id == LabEvaluationCase.dataset_id)
            .where(
                LabEvaluationCase.id == case_id,
                LabEvaluationDataset.mechanism == mechanism,
            )
        )
    )
    if row is None:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    return row


async def list_datasets(mechanism: EvaluationMechanism) -> list[EvaluationDatasetRead]:
    get_mechanism(mechanism)
    rows = list(
        (
            await get_db().scalars(
                LabEvaluationDataset.histo_filter(select(LabEvaluationDataset))
                .where(LabEvaluationDataset.mechanism == mechanism)
                .order_by(
                    LabEvaluationDataset.updated_at.desc().nullslast(),
                    LabEvaluationDataset.created_at.desc(),
                )
            )
        ).all()
    )
    return [await dataset_read(row) for row in rows]


async def create_dataset(
    mechanism: EvaluationMechanism, data: MechanismDatasetCreate
) -> EvaluationDatasetRead:
    dataset = await prepare_dataset(mechanism, data)
    get_db().add(dataset)
    await publish()
    await get_db().refresh(dataset)
    return await dataset_read(dataset)


async def prepare_dataset(
    mechanism: EvaluationMechanism, data: MechanismDatasetCreate
) -> LabEvaluationDataset:
    """Build the current Lab defaults without publishing an empty dataset."""
    definition = get_mechanism(mechanism)
    prompt_suffix: str | None = None
    if definition.executor is not None:
        prompt_suffix = (
            data.prompt_suffix.strip()
            if data.prompt_suffix is not None
            else await executor_prompt_service.default_suffix(definition.executor)
        )
    configuration: dict[str, Any] = {}
    if mechanism == "planner":
        configuration = _planner_configuration_dump(await default_planner_lab_configuration())
    elif mechanism == "topic_classification":
        configuration = _topic_configuration_dump(await default_topic_lab_configuration())
    elif mechanism == "memory_extraction":
        configuration = _memory_extraction_configuration_dump(
            await default_memory_extraction_lab_configuration()
        )
    return LabEvaluationDataset(
        mechanism=mechanism,
        name=data.name.strip(),
        description=data.description.strip(),
        purpose=data.purpose,
        prompt_suffix=prompt_suffix,
        configuration=configuration
        if definition.executor
        else configuration or {"system_prompt": definition.system_prompt},
        parameters=validate_parameters(mechanism, {}),
    )


async def update_dataset(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationDatasetUpdate,
) -> EvaluationDatasetRead:
    dataset = await _dataset(mechanism, dataset_id)
    if dataset.revision != data.revision:
        raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
    dataset.name = data.name.strip()
    dataset.description = data.description.strip()
    if "purpose" in data.model_fields_set:
        dataset.purpose = data.purpose
    dataset.parameters = validate_parameters(mechanism, data.parameters)
    if data.configuration is not None:
        dataset.configuration = validate_configuration(mechanism, data.configuration)
    definition = get_mechanism(mechanism)
    if definition.executor is not None and "prompt_suffix" in data.model_fields_set:
        dataset.prompt_suffix = (
            data.prompt_suffix.strip() if data.prompt_suffix is not None else None
        )
    await publish()
    await get_db().refresh(dataset)
    return await dataset_read(dataset)


async def update_topic_dataset_configuration(
    dataset_id: UUID,
    data: TopicDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    dataset = await _dataset("topic_classification", dataset_id)
    if dataset.revision != data.revision:
        raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
    dataset.configuration = _topic_configuration_dump(data.configuration)
    await publish()
    await get_db().refresh(dataset)
    return await dataset_read(dataset)


async def update_planner_dataset_configuration(
    dataset_id: UUID,
    data: PlannerDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    dataset = await _dataset("planner", dataset_id)
    if dataset.revision != data.revision:
        raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
    dataset.configuration = _planner_configuration_dump(data.configuration)
    await publish()
    await get_db().refresh(dataset)
    return await dataset_read(dataset)


async def planner_prompt_default() -> PlannerPromptDefaultRead:
    return PlannerPromptDefaultRead(configuration=await default_planner_lab_configuration())


async def update_memory_extraction_dataset_configuration(
    dataset_id: UUID,
    data: MemoryExtractionDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    dataset = await _dataset("memory_extraction", dataset_id)
    if dataset.revision != data.revision:
        raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
    dataset.configuration = _memory_extraction_configuration_dump(data.configuration)
    await publish()
    await get_db().refresh(dataset)
    return await dataset_read(dataset)


async def memory_extraction_prompt_default() -> MemoryExtractionPromptDefaultRead:
    return MemoryExtractionPromptDefaultRead(
        configuration=await default_memory_extraction_lab_configuration()
    )


async def delete_dataset(mechanism: EvaluationMechanism, dataset_id: UUID) -> bool:
    try:
        dataset = await _dataset(mechanism, dataset_id)
    except LookupError:
        return False
    dataset.soft_delete()
    rows = list(
        (
            await get_db().scalars(
                LabEvaluationCase.histo_filter(select(LabEvaluationCase)).where(
                    LabEvaluationCase.dataset_id == dataset_id
                )
            )
        ).all()
    )
    for row in rows:
        row.soft_delete()
    await publish()
    return True


async def list_cases(mechanism: EvaluationMechanism, dataset_id: UUID) -> list[EvaluationCaseRead]:
    await _dataset(mechanism, dataset_id)
    rows = list(
        (
            await get_db().scalars(
                LabEvaluationCase.histo_filter(select(LabEvaluationCase))
                .where(LabEvaluationCase.dataset_id == dataset_id)
                .order_by(LabEvaluationCase.created_at.desc())
            )
        ).all()
    )
    return [EvaluationCaseRead.model_validate(row) for row in rows]


async def create_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationCaseCreate,
) -> EvaluationCaseRead:
    await _dataset(mechanism, dataset_id)
    definition = get_mechanism(mechanism)
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        name=data.name.strip(),
        enabled=True,
        readiness="draft",
        input_data=capture_input(mechanism, definition.default_input),
        expected_output=definition.default_output,
        reference={},
        source_capture={},
    )
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


def _parse_json_text(value: str) -> Any:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [position for position in (text.find("{"), text.find("[")) if position >= 0]
        if not starts:
            raise
        start = min(starts)
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
        raise


def _topic_input(prompt: str) -> dict[str, Any]:
    prefix = "Existing thematic dossiers (JSON):\n"
    separator = "\n\nCompleted activity to classify:\n"
    if not prompt.startswith(prefix) or separator not in prompt:
        raise ValueError("The recorded topic-classification input is incomplete")
    candidates, activity = prompt[len(prefix) :].split(separator, 1)
    return {
        "existing_topics": _parse_json_text(candidates),
        "completed_activity": activity,
    }


def _source_input(mechanism: EvaluationMechanism, prompt: str) -> Any:
    definition = get_mechanism(mechanism)
    if definition.input_format == "text":
        return prompt
    if mechanism == "topic_classification":
        return _topic_input(prompt)
    return _parse_json_text(prompt)


def _source_output(call: LLMCall) -> Any:
    if call.response_text.strip():
        return _parse_json_text(call.response_text)
    for raw_tool in reversed(call.tool_calls or []):
        arguments = raw_tool.get("arguments")
        if isinstance(arguments, str):
            try:
                return _parse_json_text(arguments)
            except json.JSONDecodeError:
                continue
        if isinstance(arguments, (dict, list)):
            return cast(Any, arguments)
    raise ValueError("The recorded inference has no importable output")


def _matches_mechanism_call(definition: MechanismDefinition, call: LLMCall) -> bool:
    system_prompt = call.system_prompt.casefold()
    return any(
        marker.casefold() in system_prompt
        for marker in (definition.marker, *definition.marker_aliases)
    )


async def list_source_candidates(
    mechanism: EvaluationMechanism,
    *,
    search: str | None = None,
    limit: int = 50,
    agent_ids: Collection[int] | None = None,
) -> list[MechanismSourceCandidate]:
    definition = get_mechanism(mechanism)
    if mechanism == "topic_classification":
        return await _list_topic_message_candidates(
            search=search,
            limit=limit,
            agent_ids=agent_ids,
        )
    if mechanism == "memory_extraction":
        return await _list_memory_extraction_candidates(
            search=search,
            limit=limit,
            agent_ids=agent_ids,
        )
    if not definition.source_import:
        return []
    marker_filters = [
        LLMCall.system_prompt.ilike(f"%{marker}%")
        for marker in (definition.marker, *definition.marker_aliases)
    ]
    query = select(LLMCall).where(
        LLMCall.status.in_(_SUCCESS_CALL_STATUSES),
        or_(*marker_filters),
    )
    if agent_ids is not None:
        query = query.where(
            or_(
                LLMCall.agent_id.in_(agent_ids),
                LLMCall.task_id.in_(select(Task.id).where(Task.agent_id.in_(agent_ids))),
                LLMCall.conversation_round_id.in_(
                    select(ConversationRound.id)
                    .join(Room, Room.id == ConversationRound.room_id)
                    .join(Connection, Connection.id == Room.connection_id)
                    .where(Connection.agent_id.in_(agent_ids))
                ),
                LLMCall.process_run_id.in_(
                    select(ProcessRun.id).where(ProcessRun.launcher_agent_id.in_(agent_ids))
                ),
            )
        )
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        query = query.where(
            or_(
                LLMCall.prompt.ilike(pattern),
                LLMCall.requested_model.ilike(pattern),
                LLMCall.effective_model.ilike(pattern),
            )
        )
    calls = list(
        (
            await get_db().scalars(
                query.order_by(LLMCall.created_at.desc()).limit(min(500, limit * 4))
            )
        ).all()
    )
    result: list[MechanismSourceCandidate] = []
    for call in calls:
        try:
            _source_input(mechanism, call.prompt)
            definition.validate_output(_source_output(call))
        except ValueError:
            continue
        task = await get_db().get(Task, call.task_id) if call.task_id else None
        label = (
            task.label if task is not None else f"{mechanism} · {call.created_at:%Y-%m-%d %H:%M}"
        )
        result.append(
            MechanismSourceCandidate(
                source_id=call.id,
                source_kind="llm_call",
                call_id=call.id,
                task_id=call.task_id,
                label=label,
                model=call.effective_model or call.requested_model,
                created_at=call.created_at,
                input_preview=" ".join(call.prompt.split())[:300],
            )
        )
        if len(result) >= limit:
            break
    return result


async def _list_memory_extraction_candidates(
    *,
    search: str | None,
    limit: int,
    agent_ids: Collection[int] | None = None,
) -> list[MechanismSourceCandidate]:
    """List real classified sources; importing one captures its full memory corpus."""

    normalized = (search or "").strip()
    pattern = f"%{normalized}%"
    task_query = select(Task).where(
        Task.status == TaskStatus.SUCCESS,
        Task.agent_id.is_not(None),
        Task.topic_id.is_not(None),
        Task.deleted_at.is_(None),
    )
    if agent_ids is not None:
        task_query = task_query.where(Task.agent_id.in_(agent_ids))
    if normalized:
        task_query = task_query.where(or_(Task.label.ilike(pattern), Task.objective.ilike(pattern)))
    tasks = list(
        (await get_db().scalars(task_query.order_by(Task.created_at.desc()).limit(limit))).all()
    )
    first_input_text = (
        select(Message.text)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "input",
        )
        .order_by(ConversationRoundMessage.sequence)
        .limit(1)
        .scalar_subquery()
    )
    round_query = (
        select(ConversationRound, Room, first_input_text)
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(
            ConversationRound.status.in_(("SUCCEEDED", "ERROR_RESOLVED", "COMPLETED")),
            ConversationRound.topic_id.is_not(None),
            ConversationRound.contact_memory_item_id.is_not(None),
        )
    )
    if agent_ids is not None:
        round_query = round_query.where(Connection.agent_id.in_(agent_ids))
    if normalized:
        linked_text = exists(
            select(ConversationRoundMessage.message_id)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .where(
                ConversationRoundMessage.round_id == ConversationRound.id,
                Message.text.ilike(pattern),
            )
        )
        round_query = round_query.where(
            or_(
                ConversationRound.effective_objective.ilike(pattern),
                linked_text,
            )
        )
    rounds = list(
        (
            await get_db().execute(
                round_query.order_by(ConversationRound.created_at.desc()).limit(limit)
            )
        ).all()
    )
    result = [
        MechanismSourceCandidate(
            source_id=task.id,
            source_kind="task",
            task_id=task.id,
            label=task.label,
            model="Task",
            created_at=task.created_at,
            input_preview=" ".join(str(task.objective or "").split())[:300],
        )
        for task in tasks
    ]
    result.extend(
        MechanismSourceCandidate(
            source_id=round_.id,
            source_kind="conversation_round",
            label=(
                f"Messenger · {room.label}"
                if room is not None
                else f"Voice · {str(round_.effective_objective or '')[:120]}"
            ),
            model="Voice" if round_.voice_session_id is not None else "Conversation",
            created_at=cast(datetime, round_.finished_at or round_.created_at),
            input_preview=" ".join(str(round_.effective_objective or input_text or "").split())[
                :300
            ],
        )
        for round_, room, input_text in rounds
    )
    result.sort(key=lambda item: item.created_at, reverse=True)
    return result[:limit]


def _journal_message_time(row: Message) -> int:
    """Return the canonical timestamp persisted for the message."""

    return int(row.created_at.timestamp())


def _topic_message(row: Message, *, owner_agent_id: int) -> TaskMessage:
    outbound = row.direction == "outbound"
    return TaskMessage(
        messenger_message_id=row.id,
        external_message_id=row.remote_message_id,
        platform="lab",
        sender_id=row.messenger_user_id,
        sender_external_id="assistant" if outbound else "human",
        sender_agent_id=owner_agent_id if outbound else None,
        sender_is_ai=outbound,
        room_id=row.messenger_room_id,
        room_external_id="exchange",
        text=row.text,
        reply_to_external_id=row.reply_to,
        timestamp=_journal_message_time(row),
    )


async def list_topic_message_agents(
    *,
    agent_ids: Collection[int] | None = None,
) -> list[TopicMessageAgentRead]:
    query = (
        select(
            Agent.id,
            Agent.first_name,
            Agent.last_name,
            func.count(Message.id),
        )
        .join(Connection, Connection.agent_id == Agent.id)
        .join(Message, Message.connection_id == Connection.id)
        .where(
            Agent.deleted_at.is_(None),
            func.length(func.trim(Message.text)) > 0,
        )
        .group_by(Agent.id, Agent.first_name, Agent.last_name)
        .order_by(Agent.first_name, Agent.last_name, Agent.id)
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    rows = list((await get_db().execute(query)).all())
    return [
        TopicMessageAgentRead(
            id=agent_id,
            label=(f"{first_name} {last_name}".strip() or f"IA {agent_id}"),
            message_count=message_count,
        )
        for agent_id, first_name, last_name, message_count in rows
    ]


async def list_topic_message_people(agent_id: int) -> list[TopicMessagePersonRead]:
    rows = list(
        (
            await get_db().execute(
                select(
                    Message.connection_id,
                    Message.user_id,
                    Message.platform,
                    func.count(Message.id),
                )
                .join(Connection, Connection.id == Message.connection_id)
                .where(
                    Connection.agent_id == agent_id,
                    Message.direction == "inbound",
                    Message.user_id.is_not(None),
                    func.length(func.trim(Message.text)) > 0,
                )
                .group_by(
                    Message.connection_id,
                    Message.user_id,
                    Message.platform,
                )
                .order_by(
                    Message.platform,
                    Message.user_id,
                )
                .limit(500)
            )
        ).all()
    )
    return [
        TopicMessagePersonRead(
            connection_id=connection_id,
            user_id=str(user_id),
            label=str(user_id),
            platform=platform,
            message_count=message_count,
        )
        for connection_id, user_id, platform, message_count in rows
    ]


async def _topic_range_rows(
    *,
    agent_id: int,
    connection_id: int,
    user_id: str,
    date_from: datetime,
    date_to: datetime,
) -> tuple[list[Message], int]:
    connection = await get_db().get(Connection, connection_id)
    if connection is None or connection.agent_id != agent_id:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    room_ids = list(
        (
            await get_db().scalars(
                select(Message.room_id)
                .where(
                    Message.connection_id == connection_id,
                    Message.direction == "inbound",
                    Message.user_id == user_id,
                    Message.room_id.is_not(None),
                )
                .distinct()
            )
        ).all()
    )
    if not room_ids:
        return [], 0
    occurred_at = Message.created_at
    filters = (
        Message.connection_id == connection_id,
        Message.room_id.in_(room_ids),
        or_(
            Message.direction == "outbound",
            Message.user_id == user_id,
        ),
        occurred_at >= date_from,
        occurred_at <= date_to,
        func.length(func.trim(Message.text)) > 0,
    )
    total_count = int(await get_db().scalar(select(func.count(Message.id)).where(*filters)) or 0)
    rows = list(
        (
            await get_db().scalars(
                select(Message)
                .where(*filters)
                .order_by(
                    occurred_at,
                    Message.id,
                )
                .limit(500)
            )
        ).all()
    )
    return rows, total_count


async def _topic_titles_by_message(
    rows: list[Message],
    *,
    agent_id: int,
    date_from: datetime,
    date_to: datetime,
) -> dict[tuple[int, str], str]:
    message_ids = {row.remote_message_id for row in rows}
    if not message_ids:
        return {}
    tasks = list(
        (
            await get_db().execute(
                select(Task, Topic.title)
                .join(Topic, Topic.id == Task.topic_id)
                .where(
                    Task.agent_id == agent_id,
                    Task.topic_id.is_not(None),
                    Task.deleted_at.is_(None),
                    Topic.deleted_at.is_(None),
                    Task.created_at >= date_from - timedelta(days=1),
                    Task.created_at <= date_to + timedelta(days=1),
                )
                .order_by(Task.created_at)
            )
        ).all()
    )
    result: dict[tuple[int, str], str] = {}
    for task, title in tasks:
        if task.messenger_connection_id is None:
            continue
        for message in cast(list[TaskMessage] | None, task.messages) or []:
            if message.external_message_id in message_ids:
                result[(task.messenger_connection_id, message.external_message_id)] = title
    return result


async def preview_topic_message_range(
    data: TopicMessageRangeImport,
) -> TopicMessageRangePreview:
    rows, total_count = await _topic_range_rows(
        agent_id=data.agent_id,
        connection_id=data.connection_id,
        user_id=data.user_id,
        date_from=data.date_from,
        date_to=data.date_to,
    )
    detected_topics = await _topic_titles_by_message(
        rows,
        agent_id=data.agent_id,
        date_from=data.date_from,
        date_to=data.date_to,
    )
    messages = [
        TopicMessagePreview(
            journal_message_id=row.id,
            message=_topic_message(row, owner_agent_id=data.agent_id)
            .model_copy(
                update={
                    "external_message_id": f"message-{index + 1}",
                    "reply_to_external_id": None,
                }
            )
            .model_dump(mode="json"),
            role="assistant" if row.direction == "outbound" else "human",
            occurred_at=row.created_at,
            detected_topic=detected_topics.get((row.connection_id, row.remote_message_id)),
        )
        for index, row in enumerate(rows)
    ]
    return TopicMessageRangePreview(
        agent_id=data.agent_id,
        connection_id=data.connection_id,
        user_id=data.user_id,
        date_from=data.date_from,
        date_to=data.date_to,
        total_count=total_count,
        truncated=total_count > len(messages),
        messages=messages,
    )


async def import_topic_message_range(
    dataset_id: UUID,
    data: TopicMessageRangeImport,
) -> EvaluationCaseRead:
    await _dataset("topic_classification", dataset_id)
    preview = await preview_topic_message_range(data)
    if not preview.messages:
        raise ValueError(await tr("evaluation_api.errors.message_range_empty"))
    if preview.truncated:
        raise ValueError(await tr("evaluation_api.errors.message_range_too_large"))
    input_data = TopicDetectionLabInput(
        messages=[TaskMessage.model_validate(item.message) for item in preview.messages],
        initial_topic=None,
    ).model_dump(mode="json")
    topics = [item.detected_topic or "" for item in preview.messages]
    agent = await get_db().get(Agent, data.agent_id)
    agent_label = (
        f"{agent.first_name} {agent.last_name}".strip()
        if agent is not None
        else f"IA {data.agent_id}"
    )
    automatic_name = (
        f"{agent_label} · {data.user_id} · {data.date_from:%Y-%m-%d} → {data.date_to:%Y-%m-%d}"
    )
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "exact_input_without_reference_output",
        "input_data": input_data,
        "reference_output_available": any(topics),
        "import_filter": data.model_dump(mode="json", exclude={"name"}),
        "messages": [item.model_dump(mode="json") for item in preview.messages],
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        name=(data.name.strip() if data.name else automatic_name)[:400],
        enabled=True,
        readiness="draft",
        input_data=capture_input("topic_classification", input_data),
        expected_output={"topics": topics},
        reference={"source_kind": "messenger_message_range"},
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def _list_topic_message_candidates(
    *,
    search: str | None,
    limit: int,
    agent_ids: Collection[int] | None = None,
) -> list[MechanismSourceCandidate]:
    query = (
        select(Message)
        .join(Connection, Connection.id == Message.connection_id)
        .where(
            Message.room_id.is_not(None),
            func.length(func.trim(Message.text)) > 0,
        )
    )
    if agent_ids is not None:
        query = query.where(Connection.agent_id.in_(agent_ids))
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        query = query.where(
            or_(
                Message.text.ilike(pattern),
                Message.remote_message_id.ilike(pattern),
                Message.room_id.ilike(pattern),
                Message.user_id.ilike(pattern),
                Message.platform.ilike(pattern),
            )
        )
    rows = list(
        (
            await get_db().scalars(
                query.order_by(
                    Message.created_at.desc(),
                    Message.id.desc(),
                ).limit(limit)
            )
        ).all()
    )
    return [
        MechanismSourceCandidate(
            source_id=row.id,
            source_kind="messenger_message",
            label=(f"{row.platform} · {row.room_id} · {row.user_id or row.direction}")[:400],
            model="Messenger",
            created_at=row.created_at,
            input_preview=" ".join(row.text.split())[:300],
        )
        for row in rows
    ]


async def _topic_message_window(
    target: Message,
) -> tuple[list[Message], bool]:
    rows_desc = list(
        (
            await get_db().scalars(
                select(Message)
                .where(
                    Message.connection_id == target.connection_id,
                    Message.room_id == target.room_id,
                    or_(
                        Message.created_at < target.created_at,
                        and_(
                            Message.created_at == target.created_at,
                            Message.id <= target.id,
                        ),
                    ),
                )
                .order_by(
                    Message.created_at.desc(),
                    Message.id.desc(),
                )
                .limit(MAX_MESSAGES + 1)
            )
        ).all()
    )
    truncated = len(rows_desc) > MAX_MESSAGES
    rows_desc = rows_desc[:MAX_MESSAGES]
    rows_desc.reverse()
    return rows_desc, truncated


async def _previous_scoped_topics(
    target: Message,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await get_db().execute(
                select(
                    Task.id,
                    Task.label,
                    Task.created_at,
                    Topic.title,
                    Topic.description,
                    Topic.keywords,
                )
                .join(Topic, Topic.id == Task.topic_id)
                .where(
                    Task.messenger_connection_id == target.connection_id,
                    Task.message_group_id == target.room_id,
                    Task.topic_id.is_not(None),
                    Task.deleted_at.is_(None),
                    Topic.deleted_at.is_(None),
                    Task.created_at < target.created_at,
                )
                .order_by(Task.created_at.desc(), Task.id.desc())
                .limit(MAX_MESSAGES)
            )
        ).all()
    )
    return [
        {
            "task_uri": f"galaris://task/{task_id}",
            "topic_title": topic_title,
            "topic_description": topic_description,
            "topic_keywords": list(topic_keywords),
            "task_label": task_label,
            "task_created_at": task_created_at.isoformat(),
        }
        for (
            task_id,
            task_label,
            task_created_at,
            topic_title,
            topic_description,
            topic_keywords,
        ) in rows
    ]


async def _import_topic_message_case(
    dataset_id: UUID,
    data: MechanismCaseImport,
    *,
    agent_ids: Collection[int] | None = None,
) -> EvaluationCaseRead:
    target = await get_db().get(Message, data.resolved_source_id)
    if target is None or target.room_id is None or not target.text.strip():
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    connection = await get_db().get(Connection, target.connection_id)
    if connection is None:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    if agent_ids is not None and connection.agent_id not in agent_ids:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    rows, truncated = await _topic_message_window(target)
    if not rows or rows[-1].id != target.id:
        raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))
    previous_topics = await _previous_scoped_topics(target)
    current_topic = (
        TopicDetectionLabTopic(
            title=str(previous_topics[0]["topic_title"]),
            description=str(previous_topics[0]["topic_description"]),
            keywords=[str(value) for value in previous_topics[0]["topic_keywords"]],
        )
        if previous_topics
        else None
    )
    detector_input = TopicDetectionLabInput(
        messages=[_topic_message(row, owner_agent_id=connection.agent_id) for row in rows],
        initial_topic=current_topic,
    )
    input_data = detector_input.model_dump(mode="json")
    message_capture = [
        {
            "journal_message_id": str(row.id),
            "remote_message_id": row.remote_message_id,
            "direction": row.direction,
            "created_at": row.created_at.isoformat(),
            "attachment_count": len(row.attachments),
        }
        for row in rows
    ]
    reference = {
        "source_kind": "messenger_message",
        "source_id": str(target.id),
        "platform": target.platform,
    }
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "exact_input_without_reference_output",
        "input_data": input_data,
        "reference_output_available": False,
        "ecosystem": {
            "conversation": {
                "connection_id": target.connection_id,
                "platform": target.platform,
                "room_id": target.room_id,
            },
            "target_journal_message_id": str(target.id),
            "history_truncated": truncated,
            "messages": message_capture,
            "previous_topics": previous_topics,
            "current_topic_provenance": (
                "latest_prior_scoped_task" if previous_topics else "unavailable"
            ),
        },
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        name=(
            data.name.strip()
            if data.name
            else _compact_automatic_case_name(
                target.platform,
                target.room_id,
                target.text,
            )
        ),
        enabled=True,
        readiness="draft",
        input_data=capture_input("topic_classification", input_data),
        expected_output={"topics": [""] * len(rows)},
        reference=reference,
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def _memory_extraction_corpus(
    *,
    agent_id: int,
    contact_item_id: UUID | None,
    topic_item_id: UUID | None,
    query: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    recalled = await search_memory_detailed(
        query[:4_000],
        agent_id=agent_id,
        limit=MAX_MEMORY_EXTRACTION_CANDIDATES,
        memory_types=NOVELTY_MEMORY_TYPES,
        memory_role="ordinary",
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        record_llm_access=False,
        telemetry_kind="lab",
    )
    memories: list[dict[str, Any]] = []
    identities: list[dict[str, str]] = []
    for index, item in enumerate(existing_memories_from_hits(recalled.hits), start=1):
        local_id = f"memory-{index:03d}"
        production_memory_id = item.id
        memories.append(item.model_copy(update={"id": local_id}).model_dump(mode="json"))
        identities.append({"local_id": local_id, "production_memory_id": production_memory_id})
    return memories, identities


async def _import_memory_extraction_source_case(
    dataset_id: UUID,
    data: MechanismCaseImport,
    *,
    agent_ids: Collection[int] | None = None,
) -> EvaluationCaseRead:
    source_id = data.resolved_source_id
    task = await get_db().get(Task, source_id)
    source_kind: str
    name: str
    agent_id: int
    contact_item_id: UUID | None
    topic: Topic | None
    extraction_input: MemoryExtractionInput
    source_revision: int | None = None
    source_task_id: UUID | None = None

    if (
        task is not None
        and task.status == TaskStatus.SUCCESS
        and task.agent_id is not None
        and task.topic_id is not None
    ):
        topic = await get_db().get(Topic, task.topic_id)
        if topic is None:
            raise ValueError("The Task Topic is no longer available.")
        followup = await get_conversation_followup(task)
        extraction_input = build_task_extraction_input(
            task,
            followup=followup,
            topic=topic,
        )
        source_kind = "task"
        name = task.label
        agent_id = task.agent_id
        contact_item_id = task.contact_memory_item_id
        source_revision = int(task.revision or 1)
        source_task_id = task.id
    else:
        round_ = await get_db().get(ConversationRound, source_id)
        if round_ is not None and round_.topic_id is not None:
            context = await round_execution_context(round_)
            topic = await get_db().get(Topic, round_.topic_id)
            if context is None or topic is None or round_.contact_memory_item_id is None:
                raise ValueError("The conversation source is incomplete.")
            agent_id, _language = context
            extraction_input = await build_conversation_extraction_input(round_, topic)
            room = await get_db().get(Room, round_.room_id)
            source_kind = "conversation_round"
            name = (
                f"Messenger · {room.label}"
                if room is not None
                else f"Voice · {str(round_.effective_objective or '')[:120]}"
            )
            contact_item_id = round_.contact_memory_item_id
        else:
            raise LookupError(await tr("evaluation_api.errors.case_not_found"))

    if agent_ids is not None and agent_id not in agent_ids:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))

    if topic.memory_item_id is None:
        await topic_service.project_memory(topic)
    query = " ".join(message.text for message in extraction_input.current)[:4_000]
    memories, memory_identities = await _memory_extraction_corpus(
        agent_id=agent_id,
        contact_item_id=contact_item_id,
        topic_item_id=(topic.memory_item_id if contact_item_id is not None else None),
        query=query,
    )
    extraction_input = MemoryExtractionInput.model_validate(
        {
            **extraction_input.model_dump(mode="json"),
            "existing_memories": memories,
        }
    )
    expected = MemoryExtractionLabOutput().model_dump(mode="json")
    input_data = extraction_input.model_dump(mode="json")
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "exact_source_and_top_10_recalled_memories",
        "input_data": input_data,
        "output": expected,
        "source_kind": source_kind,
        "source_id": str(source_id),
        "production_memory_identities": memory_identities,
        "memory_corpus_count": len(memories),
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        source_task_id=source_task_id,
        source_task_revision=source_revision,
        name=(data.name.strip() if data.name else name)[:400],
        enabled=True,
        readiness="draft",
        input_data=capture_input("memory_extraction", input_data),
        expected_output=expected,
        reference={"source_kind": source_kind, "source_id": str(source_id)},
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def import_source_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: MechanismCaseImport,
    *,
    agent_ids: Collection[int] | None = None,
) -> EvaluationCaseRead:
    await _dataset(mechanism, dataset_id)
    definition = get_mechanism(mechanism)
    if mechanism == "topic_classification":
        return await _import_topic_message_case(
            dataset_id,
            data,
            agent_ids=agent_ids,
        )
    if mechanism == "memory_extraction":
        return await _import_memory_extraction_source_case(
            dataset_id,
            data,
            agent_ids=agent_ids,
        )
    call = await get_db().get(LLMCall, data.resolved_source_id)
    if (
        call is None
        or call.status not in _SUCCESS_CALL_STATUSES
        or not _matches_mechanism_call(definition, call)
    ):
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    input_data = _source_input(mechanism, call.prompt)
    expected_output = definition.validate_output(_source_output(call))
    llm = await llm_service.get_llm(call.llm_id) if call.llm_id is not None else None
    task = await get_db().get(Task, call.task_id) if call.task_id else None
    if agent_ids is not None:
        allowed = call.agent_id in agent_ids
        if task is not None:
            allowed = allowed or task.agent_id in agent_ids
        if call.conversation_round_id is not None:
            round_ = await get_db().get(ConversationRound, call.conversation_round_id)
            context = await round_execution_context(round_) if round_ is not None else None
            allowed = allowed or (context is not None and context[0] in agent_ids)
        if call.process_run_id is not None:
            process_run = await get_db().get(ProcessRun, call.process_run_id)
            allowed = allowed or (
                process_run is not None and process_run.launcher_agent_id in agent_ids
            )
        if not allowed:
            raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    reference = _llm_snapshot(llm)
    reference.update(
        {
            "llm_call_id": str(call.id),
            "requested_model": call.requested_model,
            "effective_model": call.effective_model,
            "provider": call.provider_name,
        }
    )
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "context_requires_review" if isinstance(input_data, str) else "captured",
        "input_data": input_data,
        "output": expected_output,
        "llm": reference,
        "prompts": {"system_prompt": call.system_prompt}
        if mechanism
        in {"briefing", "planner", "outcome_reflection", "goal_tracking", "task_analysis"}
        else {},
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        source_task_id=call.task_id,
        source_task_revision=int(task.revision or 1) if task is not None else None,
        name=(data.name or (task.label if task is not None else f"{mechanism} {call.id}"))[:400],
        enabled=True,
        readiness="draft" if isinstance(input_data, str) else "ready",
        input_data=capture_input(
            mechanism,
            input_data,
            objective=task.objective
            if task is not None and mechanism in {"briefing", "planner"}
            else None,
        ),
        expected_output=expected_output,
        reference=reference,
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def import_task_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: DispatcherCaseImport,
) -> EvaluationCaseRead:
    """Import the latest matching real inference attached to one Task."""
    await _dataset(mechanism, dataset_id)
    if mechanism == "task_analysis":
        from .evidence_service import build_task_evidence

        bundle = await build_task_evidence(data.task_id)
        row = LabEvaluationCase(
            dataset_id=dataset_id,
            source_task_id=data.task_id,
            name=data.name or bundle.summary.label,
            readiness="draft",
            input_data=capture_input(mechanism, bundle.payload),
            expected_output=get_mechanism(mechanism).default_output,
            source_capture={"fidelity": "captured", "input_data": bundle.payload},
        )
        await check_capture(row, data.confirmation_token)
        get_db().add(row)
        await publish()
        await get_db().refresh(row)
        return EvaluationCaseRead.model_validate(row)
    if mechanism == "memory_extraction":
        return await _import_memory_extraction_source_case(
            dataset_id,
            MechanismCaseImport(
                source_id=data.task_id, name=data.name, confirmation_token=data.confirmation_token
            ),
        )
    definition = get_mechanism(mechanism)
    task = await get_db().get(Task, data.task_id)
    if task is None:
        raise LookupError(await tr("evaluation_api.errors.case_not_found"))
    marker_filters = [
        LLMCall.system_prompt.ilike(f"%{marker}%")
        for marker in (definition.marker, *definition.marker_aliases)
    ]
    call = await get_db().scalar(
        select(LLMCall)
        .where(
            LLMCall.task_id == data.task_id,
            LLMCall.status.in_(_SUCCESS_CALL_STATUSES),
            or_(*marker_filters),
        )
        .order_by(LLMCall.created_at.desc())
        .limit(1)
    )
    if call is not None and (call.response_text.strip() or call.tool_calls):
        return await import_source_case(
            mechanism,
            dataset_id,
            MechanismCaseImport(
                source_id=call.id, name=data.name, confirmation_token=data.confirmation_token
            ),
        )

    input_data: Any
    raw_output: Any
    if mechanism == "briefing":
        briefing = task.get_briefing_result()
        if briefing is None or not briefing.prompt.strip():
            raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))
        input_data = briefing.prompt
        raw_output = {
            "result": briefing.result,
            "choices": [choice.model_dump(mode="json") for choice in briefing.choices],
        }
    elif mechanism == "planner" and task.plan:
        if call is None or not call.prompt.strip():
            raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))
        input_data = call.prompt
        raw_output = task.plan
    else:
        raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))

    expected_output = definition.validate_output(raw_output)
    llm = (
        await llm_service.get_llm(call.llm_id)
        if call is not None and call.llm_id is not None
        else None
    )
    reference = _llm_snapshot(llm)
    if call is not None:
        reference.update(
            {
                "llm_call_id": str(call.id),
                "requested_model": call.requested_model,
                "effective_model": call.effective_model,
                "provider": call.provider_name,
            }
        )
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "context_requires_review" if isinstance(input_data, str) else "captured",
        "input_data": input_data,
        "output": expected_output,
        "llm": reference,
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        source_task_id=task.id,
        source_task_revision=int(task.revision or 1),
        name=(data.name or task.label)[:400],
        enabled=True,
        readiness="draft" if isinstance(input_data, str) else "ready",
        input_data=capture_input(
            mechanism,
            input_data,
            objective=task.objective if mechanism in {"briefing", "planner"} else None,
        ),
        expected_output=expected_output,
        reference=reference,
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


def _mapping(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _items(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _executor_tool_calls(
    execution_result: dict[str, Any],
    llm_calls: list[Any],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for message in _items(execution_result.get("messages")):
        item = _mapping(message)
        name = str(item.get("tool_name") or "").strip()
        if item.get("type") == "tool" and name:
            calls.append(
                {
                    "name": name,
                    "arguments": _mapping(item.get("tool_arguments")),
                }
            )
    if calls:
        return calls
    for raw_call in llm_calls:
        call = _mapping(raw_call)
        for raw_tool in _items(call.get("tool_calls")):
            tool = _mapping(raw_tool)
            name = str(tool.get("name") or "").strip()
            if name:
                calls.append(
                    {
                        "name": name,
                        "arguments": _mapping(tool.get("arguments")),
                    }
                )
    return calls


def _executor_action(tool_calls: list[dict[str, Any]]) -> str:
    names = {str(item.get("name") or "") for item in tool_calls}
    if "conversation_task_submit" in names:
        return "start_task"
    if "conversation_process_start" in names:
        return "start_process"
    if "conversation_task_status" in names:
        return "read_status"
    if tool_calls:
        return "use_tool"
    return "reply"


def _executor_agent(snapshot: dict[str, Any], agent: Agent | None = None) -> dict[str, str]:
    source = _mapping(snapshot.get("agent"))
    first_name = _text(agent.first_name if agent is not None else source.get("first_name"))
    last_name = _text(agent.last_name if agent is not None else source.get("last_name"))
    code = _text(agent.code if agent is not None else source.get("code"))
    job_title = _text(agent.job_title if agent is not None else source.get("job_title"))
    personality = _text(agent.personality if agent is not None else source.get("personality"))
    job_description = _text(
        agent.job_description if agent is not None else source.get("job_description")
    )
    return {
        "name": f"{first_name} {last_name}".strip() or code or "Galaris agent",
        "gender": "unspecified",
        "job_title": job_title or "agent",
        "personality": personality or "Direct and reliable",
        "job_description": job_description or "Help the user with the available tools.",
    }


def _conversation_executor_case(
    mechanism: EvaluationMechanism,
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    executor = "conversation" if mechanism == "conversation_executor" else "voice"
    if executor == "conversation":
        round_ = _mapping(snapshot.get("round"))
        room = _mapping(snapshot.get("room"))
        messages = [_mapping(item) for item in _items(snapshot.get("messages"))]
        requests = [_text(item.get("text")) for item in messages if item.get("role") == "input"]
        responses = [_text(item.get("text")) for item in messages if item.get("role") == "output"]
        message = "\n\n".join(item for item in requests if item)
        response = "\n\n".join(item for item in responses if item)
        execution_result = _mapping(round_.get("execution_result"))
        language = str(round_.get("language") or "en")
        captured_datetime = str(round_.get("created_at") or "")
        channel = str(
            next(
                (item.get("platform") for item in messages if item.get("platform")),
                "messenger",
            )
        )
        room_id = str(room.get("id") or "")
        links: dict[str, list[Any]] = {
            "task_links": _items(snapshot.get("task_links")),
            "process_links": _items(snapshot.get("process_links")),
        }
    else:
        turn = _mapping(snapshot.get("turn"))
        session = _mapping(snapshot.get("session"))
        message = str(turn.get("effective_objective") or turn.get("transcript") or "").strip()
        response = str(turn.get("assistant_response") or "").strip()
        execution_result = _mapping(turn.get("execution_result"))
        language = str(session.get("language") or "en")
        captured_datetime = str(turn.get("started_at") or "")
        channel = str(session.get("transport_kind") or "voice")
        room_id = str(session.get("room_id") or "")
        links = {"task_links": [], "process_links": []}
    if not message and executor != "voice":
        raise ValueError("The source execution has no usable request")
    tool_calls = _executor_tool_calls(
        execution_result,
        _items(snapshot.get("llm_calls")),
    )
    action = _executor_action(tool_calls)
    if not tool_calls and links["task_links"]:
        action = "start_task"
    elif not tool_calls and links["process_links"]:
        action = "start_process"
    observed_processes = [
        {
            "workflow_id": str(item["arguments"].get("workflow_id") or ""),
            "observed_input": item["arguments"].get("input", {}),
        }
        for item in tool_calls
        if item["name"] == "conversation_process_start" and item["arguments"].get("workflow_id")
    ]
    linked_work = (
        "\n".join(
            f"- {str(_mapping(item).get('task_id') or '')}"
            for item in links["task_links"]
            if _mapping(item).get("task_id")
        )
        or "- none"
    )
    input_data: dict[str, Any] = {
        "message": message,
        "language": language,
        "agent": _executor_agent(snapshot),
        "datetime": captured_datetime,
        "channel": channel,
        "room_id": room_id,
        "linked_work": linked_work,
        "available_processes": observed_processes,
    }
    expected_output: dict[str, Any] = {
        "action": action,
        "response": response,
        "tool_calls": tool_calls,
    }
    reference: dict[str, Any] = {
        "source_kind": executor,
        "observed_status": str(
            _mapping(snapshot.get("round") or snapshot.get("turn")).get("status") or ""
        ),
        "llm_calls": [
            {
                "id": str(_mapping(item).get("id") or ""),
                "model": str(
                    _mapping(item).get("effective_model")
                    or _mapping(item).get("requested_model")
                    or ""
                ),
                "status": str(_mapping(item).get("status") or ""),
            }
            for item in _items(snapshot.get("llm_calls"))
        ],
    }
    label = message[:400]
    if not label:
        turn = _mapping(snapshot.get("turn"))
        sequence = turn.get("sequence")
        label = f"Voice turn {sequence}" if sequence is not None else f"Voice turn {turn.get('id')}"
    return input_data, expected_output, label, reference


async def import_executor_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: ExecutorCaseImport,
    *,
    agent_ids: Collection[int] | None = None,
) -> EvaluationCaseRead:
    """Copy one persisted Suivi execution into its matching executor dataset."""

    await _dataset(mechanism, dataset_id)
    definition = get_mechanism(mechanism)
    if definition.executor is None:
        raise ValueError("The selected mechanism is not an executor benchmark")

    source_snapshot: dict[str, Any]
    source_task_id: UUID | None = None
    source_task_revision: int | None = None
    if mechanism == "task_executor":
        task = await get_db().get(Task, data.source_id)
        if task is None:
            raise LookupError(await tr("evaluation_api.errors.case_not_found"))
        if agent_ids is not None and task.agent_id not in agent_ids:
            raise LookupError(await tr("evaluation_api.errors.case_not_found"))
        execution_result = _mapping(task.execution_result)
        message = str(execution_result.get("prompt") or task.objective or "").strip()
        if not message or not execution_result:
            raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))
        agent = await get_db().get(Agent, task.agent_id) if task.agent_id is not None else None
        tool_calls = _executor_tool_calls(execution_result, [])
        input_data = {
            "message": message,
            "language": str(_mapping(task.data).get("language") or "en"),
            "agent": _executor_agent({}, agent),
            "available_tools": sorted(
                {str(item.get("name") or "") for item in tool_calls if item.get("name")}
            ),
        }
        expected_output = {
            "action": _executor_action(tool_calls),
            "response": str(execution_result.get("result") or ""),
            "tool_calls": tool_calls,
        }
        label = task.label
        reference = {
            "source_kind": "task",
            "observed_status": task.status.value,
            "driver": agent.agent_driver if agent is not None else "",
        }
        source_snapshot = {
            "task": {
                "uri": f"galaris://task/{task.id}",
                "revision": task.revision,
                "label": task.label,
                "objective": task.objective,
                "status": task.status.value,
                "data": task.data,
                "execution_result": task.execution_result,
            },
            "agent": input_data["agent"],
        }
        source_task_id = task.id
        source_task_revision = task.revision
    elif mechanism == "conversation_executor":
        round_ = await get_db().get(ConversationRound, data.source_id)
        context = await round_execution_context(round_) if round_ is not None else None
        if agent_ids is not None and (context is None or context[0] not in agent_ids):
            raise LookupError(await tr("evaluation_api.errors.conversation_turn_not_found"))
        inspected = await inspect_conversation_round(data.source_id)
        if inspected is None:
            raise LookupError(await tr("evaluation_api.errors.conversation_turn_not_found"))
        source_snapshot = inspected
        input_data, expected_output, label, reference = _conversation_executor_case(
            mechanism, source_snapshot
        )
    elif mechanism == "voice_executor":
        round_ = await get_db().get(ConversationRound, data.source_id)
        context = await round_execution_context(round_) if round_ is not None else None
        if agent_ids is not None and (context is None or context[0] not in agent_ids):
            raise LookupError(await tr("evaluation_api.errors.conversation_turn_not_found"))
        inspected = await inspect_voice_turn(data.source_id)
        if inspected is None:
            raise LookupError(await tr("evaluation_api.errors.conversation_turn_not_found"))
        source_snapshot = inspected
        input_data, expected_output, label, reference = _conversation_executor_case(
            mechanism, source_snapshot
        )
    else:
        raise ValueError("The executor source does not match the selected mechanism")

    request_missing = not str(_mapping(input_data).get("message") or "").strip()
    if request_missing and mechanism != "voice_executor":
        raise ValueError("The source execution has no usable request")
    if not request_missing:
        definition.prompt(input_data)
    expected_output = definition.validate_output(expected_output)
    reference = {
        **reference,
        "source_id": str(data.source_id),
    }
    source_capture = {
        "captured_at": _utcnow().isoformat(),
        "fidelity": "partial" if request_missing else "exact",
        "missing_input_fields": ["message"] if request_missing else [],
        "input_data": input_data,
        "output": expected_output,
        "source": source_snapshot,
    }
    row = LabEvaluationCase(
        dataset_id=dataset_id,
        source_task_id=source_task_id,
        source_task_revision=source_task_revision,
        name=(data.name or label)[:400],
        enabled=True,
        readiness="draft" if request_missing else "ready",
        input_data=capture_input(mechanism, input_data),
        expected_output=expected_output,
        reference=reference,
        source_capture=source_capture,
    )
    await check_capture(row, data.confirmation_token)
    get_db().add(row)
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def update_case(
    mechanism: EvaluationMechanism,
    case_id: UUID,
    data: MechanismCaseUpdate,
) -> EvaluationCaseRead:
    row = await _case(mechanism, case_id)
    if row.revision != data.revision:
        raise RevisionConflictError(await tr("evaluation_api.errors.revision_conflict"))
    definition = get_mechanism(mechanism)
    dataset = await _dataset(mechanism, row.dataset_id)
    item = LabInput.model_validate(data.input_data)
    _resolved, input_data = resolve_input(mechanism, item, dataset.parameters)
    definition.prompt(input_data)
    expected = definition.validate_output(data.expected_output)
    if mechanism == "topic_classification":
        detector_input = TopicDetectionLabInput.model_validate(input_data)
        topics_value = cast(dict[str, Any], expected).get("topics")
        topics = cast(list[Any], topics_value) if isinstance(topics_value, list) else None
        if topics is None or len(topics) != len(detector_input.messages):
            raise ValueError(await tr("evaluation_api.errors.expected_topic_count"))
        input_data = detector_input.model_dump(mode="json")
    elif mechanism == "memory_extraction":
        detector_input = MemoryExtractionInput.model_validate(input_data)
        if not detector_input.topic:
            raise ValueError("Memory extraction requires a non-null Topic.")
        output = MemoryExtractionLabOutput.model_validate(expected)
        allowed = {item.id for item in detector_input.existing_memories}
        if any(value not in allowed for value in output.relevant_memory_ids):
            raise ValueError("A relevant memory id is outside the dataset corpus.")
        for operation in output.operations:
            target = getattr(operation, "target_memory_id", None)
            if target is not None and target not in allowed:
                raise ValueError("A LINK target is outside the dataset corpus.")
        input_data = detector_input.model_dump(mode="json")
    if data.name is not None:
        row.name = data.name.strip()
    row.input_data = item.model_dump(mode="json")
    row.expected_output = expected
    row.readiness = "ready"
    if "categories" in data.model_fields_set:
        row.categories = list(dict.fromkeys(data.categories))
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def duplicate_case(mechanism: EvaluationMechanism, case_id: UUID) -> EvaluationCaseRead:
    source = await _case(mechanism, case_id)
    duplicate = LabEvaluationCase(
        dataset_id=source.dataset_id,
        derived_from_case_id=source.id,
        source_task_id=source.source_task_id,
        source_task_revision=source.source_task_revision,
        name=f"{source.name[:393]} — copy",
        enabled=source.enabled,
        categories=list(source.categories),
        readiness=source.readiness,
        input_data=json.loads(json.dumps(source.input_data)),
        expected_output=json.loads(json.dumps(source.expected_output)),
        reference=json.loads(json.dumps(source.reference)),
        source_capture=json.loads(json.dumps(source.source_capture)),
    )
    get_db().add(duplicate)
    await publish()
    await get_db().refresh(duplicate)
    return EvaluationCaseRead.model_validate(duplicate)


async def restore_case_source(
    mechanism: EvaluationMechanism, case_id: UUID, confirmation_token: str | None = None
) -> EvaluationCaseRead:
    row = await _case(mechanism, case_id)
    if not row.source_capture:
        raise ValueError(await tr("evaluation_api.errors.source_capture_missing"))
    definition = get_mechanism(mechanism)
    captured_input = cast(
        dict[str, Any] | list[Any] | str,
        row.source_capture.get("input_data"),
    )
    captured_output = cast(
        dict[str, Any] | list[Any] | str,
        definition.validate_output(row.source_capture.get("output")),
    )
    restored = LabEvaluationCase(
        dataset_id=row.dataset_id,
        input_data=capture_input(mechanism, captured_input),
        expected_output=captured_output,
        source_capture=row.source_capture,
        readiness="ready",
    )
    await check_capture(restored, confirmation_token)
    dataset = await _dataset(mechanism, row.dataset_id)
    if restored.readiness == "ready":
        resolve_input(mechanism, restored.input_data, dataset.parameters)
    row.input_data = restored.input_data
    row.expected_output = restored.expected_output
    row.source_capture = restored.source_capture
    row.reference = cast(dict[str, Any], row.source_capture.get("llm") or {})
    row.readiness = restored.readiness
    await publish()
    await get_db().refresh(row)
    return EvaluationCaseRead.model_validate(row)


async def delete_case(mechanism: EvaluationMechanism, case_id: UUID) -> bool:
    try:
        row = await _case(mechanism, case_id)
    except LookupError:
        return False
    row.soft_delete()
    await publish()
    return True


async def generate_expected(
    mechanism: EvaluationMechanism,
    case_id: UUID,
    data: MechanismExpectedGenerate,
    *, llm_id: int | None = None,
) -> MechanismExpectedGenerated:
    row = await _case(mechanism, case_id)
    llm = await llm_service.get_llm(llm_id) if llm_id is not None else await llm_service.get_profile_llm(model_usages.LAB)
    if llm is None:
        raise ValueError(await tr("evaluation_api.errors.lab_llm_not_configured"))
    dataset = await _dataset(mechanism, row.dataset_id)
    _resolved, input_data = resolve_input(
        mechanism,
        row.input_data if data.input_data is None else data.input_data,
        dataset.parameters,
    )
    definition = get_mechanism(mechanism)
    system_prompt_override: str | None = str(
        dataset.configuration.get("system_prompt") or definition.system_prompt
    )
    topic_configuration: dict[str, Any] | None = None
    if definition.executor is not None:
        dataset = await _dataset(mechanism, row.dataset_id)
        suffix = (
            dataset.prompt_suffix.strip()
            if dataset.prompt_suffix is not None
            else await executor_prompt_service.default_suffix(definition.executor)
        )
        _tree, system_prompt_override = build_executor_benchmark_prompt(
            definition,
            input_data,
            suffix=suffix,
            conversation_action_policy=(
                await executor_prompt_service.default_conversation_action_policy(
                    definition.executor
                )
            ),
        )
    elif mechanism == "planner":
        dataset = await _dataset(mechanism, row.dataset_id)
        system_prompt_override = (await _planner_configuration(dataset)).system_prompt
    elif mechanism == "topic_classification":
        dataset = await _dataset(mechanism, row.dataset_id)
        topic_configuration = _topic_configuration_dump(await _topic_configuration(dataset))
    elif mechanism == "memory_extraction":
        dataset = await _dataset(mechanism, row.dataset_id)
        topic_configuration = _memory_extraction_configuration_dump(
            await _memory_extraction_configuration(dataset)
        )
    output, cost = await evaluate_mechanism(
        definition,
        input_data=input_data,
        llm=llm,
        system_prompt_override=system_prompt_override,
        topic_configuration=topic_configuration,
    )
    return MechanismExpectedGenerated(output=output, llm=_llm_snapshot(llm), cost=cost)


async def start_run(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationRunStart,
) -> EvaluationRunRead:
    dataset = await _dataset(mechanism, dataset_id)
    llm = await llm_service.get_llm(data.llm_id)
    allowed_capabilities = {"chat", "decision"} if mechanism in {"dispatcher", "topic_classification", "memory_extraction"} else {"chat"}
    if llm is None or not allowed_capabilities.intersection(llm.service_capabilities):
        raise ValueError(await tr("evaluation_api.errors.run_llm_invalid"))
    generation_model: LLM | None = None
    if "decision" in llm.service_capabilities and mechanism in {"topic_classification", "memory_extraction"}:
        generation_model = await llm_service.get_profile_llm(model_usages.DREAM)
        if generation_model is None or "chat" not in generation_model.service_capabilities:
            raise ValueError(await tr("evaluation_api.errors.run_llm_invalid"))
    judge = (
        await llm_service.get_llm(data.judge_llm_id)
        if data.judge_llm_id is not None
        else await llm_service.get_profile_llm(model_usages.LAB)
    )
    if judge is None or "chat" not in judge.service_capabilities:
        raise ValueError(await tr("evaluation_api.errors.lab_llm_not_configured"))
    rows = list(
        (
            await get_db().scalars(
                LabEvaluationCase.histo_filter(select(LabEvaluationCase))
                .where(
                    LabEvaluationCase.dataset_id == dataset.id,
                    LabEvaluationCase.enabled.is_(True),
                    LabEvaluationCase.readiness == "ready",
                )
                .order_by(LabEvaluationCase.created_at)
            )
        ).all()
    )
    if not rows:
        raise ValueError(await tr("evaluation_api.errors.no_ready_cases"))
    snapshots = [EvaluationCaseRead.model_validate(row).model_dump(mode="json") for row in rows]
    definition = get_mechanism(mechanism)
    for snapshot in snapshots:
        resolved, native = resolve_input(mechanism, snapshot["input_data"], dataset.parameters)
        snapshot["input_data"] = resolved.model_dump(mode="json")
        snapshot["resolved_input"] = native
        profile = (
            model_usages.DREAM
            if mechanism in {"topic_classification", "memory_extraction"}
            else model_usages.DISPATCHER
            if mechanism == "dispatcher"
            else model_usages.LAB
        )
        snapshot["reasoning_effort"] = await llm_service.get_profile_reasoning_effort_for_agent_id(
            profile, native.get("agent_id") if mechanism == "dispatcher" else None
        )
    if mechanism == "topic_classification":
        for snapshot in snapshots:
            snapshot["expected_output"] = definition.validate_output(
                snapshot.get("expected_output")
            )
    configuration_snapshot: dict[str, Any] = {
        "system_prompt": dataset.configuration.get("system_prompt", definition.system_prompt)
    }
    if mechanism == "planner":
        configuration_snapshot = {
            "schema": "galaris.planner-lab-benchmark-configuration",
            "dataset_id": str(dataset.id),
            "dataset_revision": dataset.revision,
            "dataset_name": dataset.name,
            "planner_configuration": _planner_configuration_dump(
                await _planner_configuration(dataset)
            ),
        }
    elif mechanism == "topic_classification":
        configuration_snapshot = {
            "schema": "galaris.topic-lab-benchmark-configuration/v1",
            "dataset_id": str(dataset.id),
            "dataset_revision": dataset.revision,
            "dataset_name": dataset.name,
            "topic_configuration": _topic_configuration_dump(await _topic_configuration(dataset)),
        }
    elif mechanism == "memory_extraction":
        configuration_snapshot = {
            "schema": "galaris.memory-extraction-lab-benchmark-configuration",
            "dataset_id": str(dataset.id),
            "dataset_revision": dataset.revision,
            "dataset_name": dataset.name,
            "memory_extraction_configuration": _memory_extraction_configuration_dump(
                await _memory_extraction_configuration(dataset)
            ),
        }
    elif definition.executor is not None:
        configuration_snapshot = await executor_prompt_service.resolve_dataset_configuration(
            definition.executor,
            dataset_id=dataset.id,
            dataset_revision=dataset.revision,
            dataset_name=dataset.name,
            prompt_suffix=dataset.prompt_suffix,
        )
        suffix = str(configuration_snapshot["prompt_suffix"])
        conversation_action_policy = str(configuration_snapshot["conversation_action_policy"])
        for snapshot in snapshots:
            tree, rendered = build_executor_benchmark_prompt(
                definition,
                snapshot["resolved_input"],
                suffix=suffix,
                conversation_action_policy=conversation_action_policy,
            )
            snapshot["prompts"] = {
                "system_tree": tree,
                "system_markdown": rendered,
            }
    snapshots = [
        {**snapshot, "repetition": repetition}
        for repetition in range(1, data.repetitions + 1)
        for snapshot in snapshots
    ]
    run = LabEvaluationRun(
        repetitions=data.repetitions,
        max_cost=data.max_cost,
        dataset_id=dataset.id,
        llm_id=llm.id,
        judge_llm_id=judge.id,
        status="queued",
        score_version=get_rubric(mechanism).version,
        llm_snapshot=_llm_snapshot(llm),
        judge_llm_snapshot=_llm_snapshot(judge),
        configuration_snapshot={
            **configuration_snapshot,
            **({"generation_llm_snapshot": _llm_snapshot(generation_model)} if generation_model is not None else {}),
            "dataset_purpose": dataset.purpose,
            "parameters": validate_parameters(mechanism, dataset.parameters),
            "contract": CONTRACTS[mechanism].descriptor(),
            "algorithm": algorithm_description(mechanism),
            "rubric": get_rubric(mechanism).prompt_value(),
            "judge_reasoning_effort": await llm_service.get_profile_reasoning_effort(
                model_usages.LAB
            ),
        },
        case_snapshots=snapshots,
        total_cases=len(snapshots),
    )
    run.configuration_snapshot = {
        **run.configuration_snapshot,
        "fingerprints": benchmark_fingerprints(
            snapshots, run.configuration_snapshot, run.llm_snapshot, run.judge_llm_snapshot
        ),
    }
    get_db().add(run)
    await publish()
    await get_db().refresh(run)
    from app.task import scheduler

    scheduler.wake()
    return EvaluationRunRead.model_validate(run)


async def list_runs(
    mechanism: EvaluationMechanism, dataset_id: UUID, *, limit: int = 50
) -> list[EvaluationRunRead]:
    await _dataset(mechanism, dataset_id)
    rows = list(
        (
            await get_db().scalars(
                LabEvaluationRun.histo_filter(select(LabEvaluationRun))
                .where(LabEvaluationRun.dataset_id == dataset_id)
                .order_by(LabEvaluationRun.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [EvaluationRunRead.model_validate(row) for row in rows]


async def _run(mechanism: EvaluationMechanism, run_id: UUID) -> LabEvaluationRun:
    row = await get_db().scalar(
        LabEvaluationRun.histo_filter(
            select(LabEvaluationRun)
            .join(LabEvaluationDataset, LabEvaluationDataset.id == LabEvaluationRun.dataset_id)
            .where(
                LabEvaluationRun.id == run_id,
                LabEvaluationDataset.mechanism == mechanism,
            )
        )
    )
    if row is None:
        raise LookupError(await tr("evaluation_api.errors.run_not_found"))
    return row


async def get_run(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunDetail | None:
    try:
        run = await _run(mechanism, run_id)
    except LookupError:
        return None
    results = list(
        (
            await get_db().scalars(
                select(LabEvaluationRunCase)
                .where(LabEvaluationRunCase.run_id == run.id)
                .order_by(LabEvaluationRunCase.created_at)
            )
        ).all()
    )
    from .judgment_service import list_campaigns
    from .agent_review_service import list_run_reviews

    return EvaluationRunDetail(
        agent_reviews=await list_run_reviews(run.id),
        campaigns=await list_campaigns(run.id),
        **EvaluationRunRead.model_validate(run).model_dump(),
        results=[EvaluationRunCaseRead.model_validate(result) for result in results],
    )


async def delete_run(mechanism: EvaluationMechanism, run_id: UUID) -> bool:
    try:
        run = await _run(mechanism, run_id)
    except LookupError:
        return False
    if run.status not in _TERMINAL_RUN_STATUSES:
        raise ValueError(await tr("evaluation_api.errors.run_delete_active"))
    results = list(
        (
            await get_db().scalars(
                LabEvaluationRunCase.histo_filter(select(LabEvaluationRunCase)).where(
                    LabEvaluationRunCase.run_id == run.id
                )
            )
        ).all()
    )
    for result in results:
        result.soft_delete()
    run.soft_delete()
    await publish()
    return True


async def process_runs() -> int:
    """Claim, evaluate detached inputs, then publish only while the lease is owned."""
    result = await claim_next_run()
    work = result.work
    if work is not None:
        if work.case_snapshot is None:
            await finish_owned_run(work.run_id, work.token)
        elif work.phase == "judgment":
            async with keep_lease(work):
                judgment = await evaluate_judgment(work)
            await publish_judgment(work, judgment)
        else:
            async with keep_lease(work):
                evaluation = await evaluate_claim(work)
            await publish_case(work.run_id, work.token, evaluation)
    return result.processed


def _analysis_markdown(
    analysis: BenchmarkAnalysisContent,
    *,
    language: str,
    mechanism: str,
) -> str:
    french = language == "fr"
    labels = {
        "title": f"Analyse du benchmark {mechanism}"
        if french
        else f"{mechanism} benchmark analysis",
        "summary": "Synthèse" if french else "Executive summary",
        "strengths": "Forces" if french else "Strengths",
        "weaknesses": "Faiblesses" if french else "Weaknesses",
        "improvements": "Pistes d’amélioration" if french else "Improvement opportunities",
        "cases": "Analyse par cas" if french else "Case-by-case analysis",
        "assessment": "Évaluation" if french else "Assessment",
        "none": "Aucun élément notable." if french else "No notable item.",
    }

    def bullets(items: list[str]) -> str:
        values = [item.strip() for item in items if item.strip()]
        return "\n".join(f"- {item}" for item in values) if values else f"- {labels['none']}"

    sections = [
        f"# {labels['title']}",
        f"## {labels['summary']}\n\n{analysis.summary.strip()}",
        f"## {labels['strengths']}\n\n{bullets(analysis.strengths)}",
        f"## {labels['weaknesses']}\n\n{bullets(analysis.weaknesses)}",
        f"## {labels['improvements']}\n\n{bullets(analysis.improvements)}",
        f"## {labels['cases']}",
    ]
    for case in analysis.case_analyses:
        score = "—" if case.score_percent is None else f"{round(case.score_percent)} %"
        sections.append(
            f"### {' '.join(case.case_name.split())}\n"
            f"**Score :** {score}\n\n"
            f"**{labels['assessment']} :** {case.assessment.strip()}\n\n"
            f"**{labels['strengths']} :**\n{bullets(case.strengths)}\n\n"
            f"**{labels['weaknesses']} :**\n{bullets(case.weaknesses)}\n\n"
            f"**{labels['improvements']} :**\n{bullets(case.improvements)}"
        )
    sections.append(f"## Conclusion\n\n{analysis.conclusion.strip()}")
    return "\n\n".join(sections).strip() + "\n"


def _bounded_analysis_value(value: Any, *, max_chars: int) -> Any:
    """Keep complete small evidence and an explicit head/tail preview of oversized values."""

    rendered = json.dumps(value, ensure_ascii=False, default=str)
    if len(rendered) <= max_chars:
        return value
    head_chars = max_chars * 3 // 4
    tail_chars = max_chars - head_chars
    return {
        "truncated_for_benchmark_analysis": True,
        "original_characters": len(rendered),
        "preview": rendered[:head_chars]
        + "\n…[deterministic truncation]…\n"
        + rendered[-tail_chars:],
    }


async def analyze_run(
    mechanism: EvaluationMechanism,
    run_id: UUID,
    data: EvaluationRunAnalysisRequest,
    *, llm_id: int | None = None, expected_state: dict[str, Any] | None = None,
) -> EvaluationRunDetail:
    run = await _run(mechanism, run_id)
    if run.status not in _TERMINAL_RUN_STATUSES:
        raise ValueError(await tr("evaluation_api.errors.run_not_terminal"))
    results = list(
        (
            await get_db().scalars(
                select(LabEvaluationRunCase)
                .where(LabEvaluationRunCase.run_id == run.id)
                .order_by(LabEvaluationRunCase.created_at)
            )
        ).all()
    )
    if not results:
        raise ValueError(await tr("evaluation_api.errors.run_has_no_results"))
    dataset = await _dataset(mechanism, run.dataset_id)
    llm = await llm_service.get_llm(llm_id) if llm_id is not None else await llm_service.get_profile_llm(model_usages.LAB)
    if llm is None or "chat" not in llm.service_capabilities:
        raise ValueError(await tr("evaluation_api.errors.lab_llm_not_configured"))
    rubric = get_rubric(mechanism)
    semantic_scoring = run.score_version == rubric.version
    per_case_budget = max(6_000, min(40_000, 120_000 // len(results)))
    payload = {
        "benchmark": {
            "mechanism": mechanism,
            "dataset": dataset.name,
            "status": run.status,
            "semantic_relevance_percent": run.score_percent if semantic_scoring else None,
            "legacy_reference_similarity_percent": (
                run.score_percent if not semantic_scoring else None
            ),
            "score_version": run.score_version,
            "evaluation_mode": (
                "semantic_rubric" if semantic_scoring else "legacy_reference_similarity"
            ),
            "rubric": rubric.prompt_value() if semantic_scoring else None,
            "scored_cases": (
                sum(result.score_percent is not None for result in results)
                if semantic_scoring
                else 0
            ),
            "total_cases": len(results),
            "candidate_llm": run.llm_snapshot,
            "judge_llm": run.judge_llm_snapshot,
            "configuration_snapshot": run.configuration_snapshot,
        },
        "case_results": [
            {
                "case_name": result.case_snapshot.get("name"),
                "input": _bounded_analysis_value(
                    result.case_snapshot.get("input_data"), max_chars=per_case_budget // 2
                ),
                "reference_example": _bounded_analysis_value(
                    result.case_snapshot.get("expected_output"), max_chars=per_case_budget // 4
                ),
                "candidate_output": _bounded_analysis_value(
                    result.actual_output, max_chars=per_case_budget // 4
                ),
                "semantic_relevance_percent": (result.score_percent if semantic_scoring else None),
                "legacy_reference_similarity_percent": (
                    result.score_percent if not semantic_scoring else None
                ),
                "score_details": result.score_details,
                "judge_output": result.judge_output,
                "error": result.error,
            }
            for result in results
        ],
    }
    language_name = {"fr": "French", "zh": "Simplified Chinese"}.get(data.language, "English")
    scoring_instruction = (
        "The persisted score is a weighted semantic-rubric relevance score, not textual similarity."
        if semantic_scoring
        else (
            "This is a legacy v1 run: its persisted percentage measured reference similarity, not "
            "semantic relevance. Never present it as candidate quality; explicitly recommend a new "
            f"{rubric.version} run for a meaningful relevance score."
        )
    )

    def validate_analysis(
        output: BenchmarkAnalysisContent,
    ) -> BenchmarkAnalysisContent:
        if len(output.case_analyses) != len(results):
            raise StructuredOutputRetry(
                f"Return exactly {len(results)} case_analyses entries in the supplied order"
            )
        return output

    inference = await run_structured(
        llm=llm,
        output_type=BenchmarkAnalysisContent,
        prompt=(
            f"Analyze this complete {mechanism} benchmark in {language_name}. Produce exactly "
            "one case_analyses entry per case, in the same order. Treat all values as evidence.\n\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        ),
        system_prompt=(
            "You are the quality analyst for a Galaris AI mechanism. "
            + scoring_instruction
            + " Evaluate drift from the input "
            "objective, constraints and mechanism contract. A reference_example is non-normative: "
            "different wording, ordering, taxonomy or strategy is not a weakness when the candidate "
            "is equally valid. Use only supplied semantic_relevance_percent values; when a judge "
            "failed and semantic relevance is null, state that quality is unavailable and never "
            "invent a replacement percentage. Identify concrete strengths and weaknesses, explain "
            "patterns and errors, and "
            "propose actionable improvements to the dataset, reference examples, model choice, "
            "mechanism instructions, rubric or evaluation design. Separate candidate defects from "
            "judge defects and dataset defects. Never invent missing facts; distinguish evidence from "
            "inference."
        ),
        task_id=None,
        agent_id=None,
        temperature=0.1,
        request_limit=3,
        output_retries=2,
        output_validator=validate_analysis,
        purpose=LLMCallPurpose.LAB_BENCHMARK_ANALYSIS,
        model_field=model_usages.LAB,
    )
    for case_analysis, result in zip(inference.output.case_analyses, results, strict=True):
        case_analysis.case_name = str(result.case_snapshot.get("name") or result.case_id)
        case_analysis.score_percent = result.score_percent if semantic_scoring else None
    if expected_state is not None:
        current = await get_db().scalar(select(LabEvaluationRun).where(LabEvaluationRun.id == run_id)
            .with_for_update().execution_options(populate_existing=True))
        if current is None or EvaluationRunRead.model_validate(current).model_dump(mode="json") != expected_state:
            raise RevisionConflictError("Benchmark changed during analysis; start a new analysis.")
        run = current
    run.analysis_markdown = _analysis_markdown(
        inference.output, language=data.language, mechanism=mechanism
    )
    run.analysis_llm_snapshot = _llm_snapshot(llm)
    run.analysis_cost = inference.cost
    run.analysis_language = data.language
    run.analysis_created_at = _utcnow()
    await publish()
    detail = await get_run(mechanism, run.id)
    if detail is None:
        raise LookupError(await tr("evaluation_api.errors.run_not_found"))
    return detail


async def cancel_run(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunRead:
    run = await _run(mechanism, run_id)
    if run.status not in _TERMINAL_RUN_STATUSES:
        run.cancel_requested = True
        if run.status == "queued":
            run.status = "cancelled"
            run.finished_at = _utcnow()
        await publish()
    return EvaluationRunRead.model_validate(run)


__all__ = [
    "RevisionConflictError",
    "analyze_run",
    "cancel_run",
    "create_case",
    "create_dataset",
    "delete_case",
    "delete_dataset",
    "delete_run",
    "duplicate_case",
    "generate_expected",
    "get_run",
    "import_executor_case",
    "import_source_case",
    "import_task_case",
    "import_topic_message_range",
    "list_cases",
    "list_datasets",
    "list_mechanisms",
    "list_runs",
    "list_source_candidates",
    "list_topic_message_agents",
    "list_topic_message_people",
    "preview_topic_message_range",
    "process_runs",
    "restore_case_source",
    "start_run",
    "update_case",
    "update_dataset",
]


def validate_configuration(mechanism: EvaluationMechanism, value: dict[str, Any]) -> dict[str, Any]:
    if get_mechanism(mechanism).executor:
        if value:
            raise ValueError("Executor instructions are configured through the prompt suffix")
        return {}
    if mechanism == "topic_classification":
        return TopicDetectionLabConfiguration.model_validate(value).model_dump(
            mode="json", by_alias=True
        )
    if mechanism == "memory_extraction":
        return MemoryExtractionLabConfiguration.model_validate(value).model_dump(
            mode="json", by_alias=True
        )
    if mechanism == "planner":
        return PlannerLabConfiguration.model_validate(value).model_dump(mode="json", by_alias=True)
    if set(value) - {"system_prompt"}:
        raise ValueError("Unknown algorithm configuration field")
    prompt = value.get("system_prompt")
    if not isinstance(prompt, str):
        raise ValueError("system_prompt must be text")
    return {"system_prompt": prompt}


def configuration_schema(mechanism: EvaluationMechanism) -> dict[str, Any]:
    if get_mechanism(mechanism).executor:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if mechanism == "topic_classification":
        return TopicDetectionLabConfiguration.model_json_schema()
    if mechanism == "memory_extraction":
        return MemoryExtractionLabConfiguration.model_json_schema()
    if mechanism == "planner":
        return PlannerLabConfiguration.model_json_schema()
    return {
        "type": "object",
        "properties": {"system_prompt": {"type": "string", "title": "Instructions"}},
    }


def algorithm_description(mechanism: EvaluationMechanism) -> dict[str, Any]:
    definition = get_mechanism(mechanism)
    return {
        "inference": {
            "temperature": 0.1 if mechanism == "task_analysis" else 0,
            "request_limit": 4
            if definition.executor
            else None
            if mechanism in {"topic_classification", "memory_extraction"}
            else 3,
            "max_tokens": 256 if mechanism == "dispatcher" else None,
            "output_retries": None if mechanism in {"dispatcher", "memory_extraction"} else 1,
            "reasoning_profile": "DREAM"
            if mechanism in {"topic_classification", "memory_extraction"}
            else "DISPATCHER"
            if mechanism == "dispatcher"
            else "LAB",
            "count_tokens_before_request": True,
            **(
                {"tool_calls_limit": 3, "parallel_tool_calls": False, "tool_retries": 1}
                if definition.executor
                else {}
            ),
        },
        "context_limits": {
            "dispatcher": {"history_messages": 10, "characters_per_message": 500},
            "briefing": {"history_messages": 6, "result_characters": 8000, "resource_choices": 12},
            "planner": {"history_messages": 30},
            "outcome_reflection": {
                "result_characters": 4000,
                "error_characters": 2000,
                "observations": 48,
            },
            "goal_tracking": {"result_characters": 30000},
        }.get(mechanism, {}),
        "judge_inference": {
            "temperature": 0,
            "request_limit": 3,
            "output_retries": 2,
            "pass_threshold": 75,
        },
        "output_schema": definition.output_type.model_json_schema()
        if definition.output_type
        else {"type": "object"},
        "rubric": get_rubric(mechanism).prompt_value(),
    }


async def preview_input(
    mechanism: EvaluationMechanism, dataset_id: UUID, item: LabInput
) -> "LabInputPreview":
    dataset = await _dataset(mechanism, dataset_id)
    resolved, native = resolve_input(mechanism, item, dataset.parameters)
    definition = get_mechanism(mechanism)
    system_prompt = str(dataset.configuration.get("system_prompt") or definition.system_prompt)
    if definition.executor:
        suffix = (
            dataset.prompt_suffix
            if dataset.prompt_suffix is not None
            else await executor_prompt_service.default_suffix(definition.executor)
        )
        _tree, system_prompt = build_executor_benchmark_prompt(
            definition,
            native,
            suffix=suffix,
            conversation_action_policy=await executor_prompt_service.default_conversation_action_policy(
                definition.executor
            ),
        )
    candidate_prompt = definition.prompt(native)
    if mechanism == "dispatcher":
        from app.agent import preview_dispatcher_input

        system_prompt, candidate_prompt = await preview_dispatcher_input(native, system_prompt)
    if mechanism == "planner":
        system_prompt = planner_evaluation_system_prompt(
            system_prompt,
            max_depth=native["max_depth"],
            max_nodes=native["max_nodes"],
            max_leaves=native["max_leaves"],
            can_clarify=native["can_clarify"],
        )
    return LabInputPreview(
        candidate_prompt=candidate_prompt,
        system_prompt=system_prompt,
        input=resolved,
        native_input=native,
        configuration=dataset.configuration,
        parameters=validate_parameters(mechanism, dataset.parameters),
        origins={
            **{key: "dataset" for key in validate_parameters(mechanism, dataset.parameters)},
            **{key: "item" for key in resolved.context},
        },
    )
