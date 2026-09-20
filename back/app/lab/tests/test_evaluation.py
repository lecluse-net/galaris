from app.lab import run_inference, mechanism_registry
from app.lab.contracts import capture_input, resolve_input
from app.lab.capture_service import CaptureParametersMismatch
from core.database import get_db
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import (
    analysis_service,
    diagnosis_service,
    dispatcher_evaluation_service,
    evaluation_service,
    evidence_service,
    executor_prompt_service,
    mechanism_evaluation_service,
)
from app.agent.models import Agent, Title
from app.connection import Connection
from app.agent.contracts import BriefingChoice, BriefingResult, DispatchDecision, DispatchResult
from app.agent.evaluation import PlannerLabConfiguration
from app.lab.models import (
    LabEvaluationCase,
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabTask,
    LabTaskDiagnosis,
)
from app.lab.mechanism_rubrics import get_rubric, list_rubrics
from app.lab.mechanism_registry import get_mechanism
from app.lab.prompts import ANALYST_SYSTEM_PROMPT
from app.lab.schemas import (
    BenchmarkAnalysisContent,
    BenchmarkCaseAnalysis,
    DispatcherExpectedDecision,
    DispatcherJudgeOutput,
    EvaluationCaseCreate,
    EvaluationCaseUpdate,
    EvaluationDatasetCreate,
    EvaluationDatasetUpdate,
    EvaluationExpectedGenerate,
    EvaluationRunAnalysisRequest,
    EvaluationRunStart,
    ExecutorCaseImport,
    MechanismCaseImport,
    MechanismCaseUpdate,
    MechanismDatasetCreate,
    MechanismJudgeOutput,
    MechanismJudgeDimension,
    PlannerDatasetConfigurationUpdate,
    TopicMessageRangeImport,
    TopicDatasetConfigurationUpdate,
    TaskAnalysisContent,
    TaskAnalysisRequest,
)
from app.llm import LLM, LLMCallPurpose, LLMProvider, model_usages
from app.llm.models import LLMCall
from app.messenger import Message
from app.task import TaskMessage
from app.task.models import Task, TaskAttempt, TaskStatus
from app.tools.models import Tool
from app.topic import Topic
from app.topic.evaluation import (
    TopicDetectionLabConfiguration,
    TopicDetectionLabPrompts,
    TopicDetectionLabTopic,
)
from core.params import Params


def test_lab_llm_uses_the_high_text_tier() -> None:
    assert model_usages.LAB == model_usages.TEXT_HIGH
    assert model_usages.LAB in model_usages.ALL


def test_lab_analysis_accepts_simplified_chinese() -> None:
    assert TaskAnalysisRequest(language="zh").language == "zh"
    assert EvaluationRunAnalysisRequest(language="zh").language == "zh"


def test_automatic_case_name_is_short_and_single_line() -> None:
    name = mechanism_evaluation_service._compact_automatic_case_name(
        "telegram",
        "garden-room",
        "Une réponse très longue\n" + "avec beaucoup de détails " * 20,
    )

    assert len(name) == 96
    assert name.endswith("…")
    assert "\n" not in name


def test_lab_exposes_all_isolated_ai_mechanisms() -> None:
    descriptors = mechanism_evaluation_service.list_mechanisms()

    assert {item.key for item in descriptors} == {
        "dispatcher",
        "task_analysis",
        "briefing",
        "planner",
        "topic_classification",
        "memory_extraction",
        "outcome_reflection",
        "goal_tracking",
        "task_executor",
        "conversation_executor",
        "voice_executor",
    }
    formats = {item.key: (item.input_format, item.output_format) for item in descriptors}
    source_import = {item.key: item.source_import for item in descriptors}
    assert formats["briefing"] == ("text", "json")
    assert formats["topic_classification"] == ("json", "json")
    assert formats["goal_tracking"] == ("text", "json")
    assert formats["conversation_executor"] == ("json", "json")
    assert source_import["topic_classification"] is True


@pytest.mark.asyncio
async def test_planner_dataset_owns_and_freezes_its_prompt(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Planner prompt provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    candidate = LLM(
        llm_provider_id=provider.id,
        code=f"planner-candidate-{uuid4()}",
        llm_name="example/planner-candidate",
        label="Planner candidate",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"planner-judge-{uuid4()}",
        llm_name="example/planner-judge",
        label="Planner judge",
    )
    db.add_all([candidate, judge])
    await db.commit()
    monkeypatch.setattr(
        mechanism_evaluation_service,
        "default_planner_lab_configuration",
        AsyncMock(return_value=PlannerLabConfiguration(system_prompt="Planner runtime v1")),
    )
    monkeypatch.setattr(
        mechanism_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=judge),
    )

    dataset = await mechanism_evaluation_service.create_dataset(
        "planner",
        MechanismDatasetCreate(name=f"Planner prompts {uuid4()}"),
    )
    assert dataset.configuration["system_prompt"] == "Planner runtime v1"

    case = await mechanism_evaluation_service.create_case(
        "planner",
        dataset.id,
        EvaluationCaseCreate(name="Complex artifact"),
    )
    await mechanism_evaluation_service.update_case(
        "planner",
        case.id,
        MechanismCaseUpdate(
            revision=case.revision,
            input_data={"variable_value": "Prepare the report"},
            expected_output=case.expected_output,
        ),
    )
    queued = await mechanism_evaluation_service.start_run(
        "planner", dataset.id, EvaluationRunStart(llm_id=candidate.id)
    )
    snapshot = queued.configuration_snapshot
    assert snapshot["planner_configuration"]["system_prompt"] == "Planner runtime v1"

    await mechanism_evaluation_service.update_planner_dataset_configuration(
        dataset.id,
        PlannerDatasetConfigurationUpdate(
            revision=dataset.revision,
            configuration=PlannerLabConfiguration(system_prompt="Planner dataset v2"),
        ),
    )
    row = await db.get(LabEvaluationRun, queued.id)
    assert row is not None
    assert row.configuration_snapshot == snapshot


def test_every_non_dispatch_mechanism_has_a_complete_versioned_semantic_rubric() -> None:
    rubrics = list_rubrics()

    assert {rubric.mechanism for rubric in rubrics} == {
        "dispatcher",
        "task_analysis",
        "briefing",
        "planner",
        "topic_classification",
        "memory_extraction",
        "outcome_reflection",
        "goal_tracking",
        "task_executor",
        "conversation_executor",
        "voice_executor",
    }
    for rubric in rubrics:
        if rubric.mechanism == "memory_extraction":
            assert rubric.version == "memory_extraction-score"
        else:
            expected_version = (
                ":v1"
                if rubric.mechanism == "task_analysis"
                else ":v3"
                if rubric.mechanism in {"topic_classification", "dispatcher"}
                else ":v2"
            )
            assert rubric.version.endswith(expected_version)
        assert rubric.critical_failure_cap_percent == 50
        assert sum(dimension.weight for dimension in rubric.dimensions) == 100
        assert len({dimension.code for dimension in rubric.dimensions}) == len(rubric.dimensions)


@pytest.mark.asyncio
async def test_memory_extraction_corpus_recall_is_bounded_to_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recall = AsyncMock(return_value=SimpleNamespace(hits=[]))
    monkeypatch.setattr(mechanism_evaluation_service, "search_memory_detailed", recall)

    memories, identities = await mechanism_evaluation_service._memory_extraction_corpus(
        agent_id=42,
        contact_item_id=None,
        topic_item_id=None,
        query="préférence de concision",
    )

    assert recall.await_args.args[0] == "préférence de concision"
    assert recall.await_args.kwargs["limit"] == 10
    assert memories == []
    assert identities == []


@pytest.mark.asyncio
async def test_memory_extraction_import_preserves_source_corpus_with_dataset_parameters(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Memory Lab {suffix}", gender="X")
    topic = Topic(title="Préférences durables")
    db.add_all([title, topic])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Memory Lab",
        code=f"memory-lab-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    task = Task(
        label="Conserver une préférence",
        objective="Je préfère les réponses courtes.",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        topic_id=topic.id,
    )
    db.add(task)
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "memory_extraction",
        MechanismDatasetCreate(name=f"Memory import {suffix}"),
    )
    corpus = [
        {
            "id": "memory-001",
            "title": "Réponses courtes",
            "content": "La personne préfère les réponses courtes.",
            "memory_type": "core",
            "keywords": ["concision"],
            "score": 0.0,
        }
    ]
    identities = [
        {
            "local_id": "memory-001",
            "production_memory_id": str(uuid4()),
        }
    ]
    corpus_recall = AsyncMock(return_value=(corpus, identities))
    monkeypatch.setattr(
        mechanism_evaluation_service,
        "_memory_extraction_corpus",
        corpus_recall,
    )
    monkeypatch.setattr(
        mechanism_evaluation_service.topic_service,
        "project_memory",
        AsyncMock(return_value=None),
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_source_case,
        "memory_extraction",
        dataset.id,
        MechanismCaseImport(source_id=task.id),
    )

    assert imported.source_capture["input_data"]["source_kind"] == "task"
    assert imported.input_data["variable_value"]["task_trace"]["objective"] == task.objective
    assert imported.source_capture["input_data"]["existing_memories"] == corpus
    assert imported.source_capture["memory_corpus_count"] == 1
    assert imported.source_capture["production_memory_identities"] == identities
    assert corpus_recall.await_args.kwargs["query"] == task.objective
    assert corpus_recall.await_args.kwargs["topic_item_id"] is None

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == imported.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.execute(delete(Topic).where(Topic.id == topic.id))
    await db.execute(delete(Agent).where(Agent.id == agent.id))
    await db.execute(delete(Title).where(Title.id == title.id))
    await db.commit()


@pytest.mark.asyncio
async def test_task_executor_import_copies_one_execution_into_the_selected_dataset(
    db: AsyncSession,
) -> None:
    task = Task(
        label="Publish the report",
        objective="Publish the verified report",
        status=TaskStatus.SUCCESS,
        data={"language": "fr"},
        execution_result={
            "prompt": "Exact executor input: publish the verified report",
            "result": "Le rapport a été publié.",
            "messages": [
                {
                    "type": "tool",
                    "tool_name": "messenger_send_file",
                    "tool_arguments": {"path": "report.pdf"},
                }
            ],
        },
    )
    db.add(task)
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "task_executor",
        MechanismDatasetCreate(name=f"Task executor import {uuid4()}"),
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_executor_case,
        "task_executor",
        dataset.id,
        ExecutorCaseImport(source_id=task.id),
    )

    assert imported.dataset_id == dataset.id
    assert imported.source_task_id == task.id
    assert (
        imported.input_data["variable_value"] == "Exact executor input: publish the verified report"
    )
    assert imported.source_capture["input_data"]["language"] == "fr"
    assert imported.expected_output == {
        "action": "use_tool",
        "response": "Le rapport a été publié.",
        "tool_calls": [{"name": "messenger_send_file", "arguments": {"path": "report.pdf"}}],
    }
    assert imported.source_capture["source"]["task"]["execution_result"] == task.execution_result
    assert imported.reference["source_id"] == str(task.id)


@pytest.mark.asyncio
async def test_conversation_executor_import_copies_the_round_into_the_selected_dataset(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    snapshot = {
        "round": {
            "id": str(source_id),
            "status": "SUCCEEDED",
            "language": "fr",
            "execution_result": {
                "messages": [
                    {
                        "type": "tool",
                        "tool_name": "conversation_task_submit",
                        "tool_arguments": {"objective": "Préparer le rapport détaillé"},
                    }
                ]
            },
        },
        "room": {"id": str(uuid4())},
        "agent": {
            "code": "alice",
            "first_name": "Alice",
            "last_name": "Conversation",
        },
        "messages": [
            {
                "role": "input",
                "platform": "telegram",
                "text": "Prépare un rapport détaillé",
            },
            {
                "role": "output",
                "platform": "telegram",
                "text": "Je lance la préparation du rapport.",
            },
        ],
        "task_links": [{"task_id": str(uuid4())}],
        "process_links": [],
        "llm_calls": [],
    }
    monkeypatch.setattr(
        mechanism_evaluation_service,
        "inspect_conversation_round",
        AsyncMock(return_value=snapshot),
    )
    dataset = await mechanism_evaluation_service.create_dataset(
        "conversation_executor",
        MechanismDatasetCreate(name=f"Conversation executor import {uuid4()}"),
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_executor_case,
        "conversation_executor",
        dataset.id,
        ExecutorCaseImport(source_id=source_id),
    )

    assert imported.dataset_id == dataset.id
    assert imported.source_task_id is None
    assert imported.input_data["variable_value"] == "Prépare un rapport détaillé"
    assert imported.source_capture["input_data"]["language"] == "fr"
    assert imported.expected_output["action"] == "start_task"
    assert imported.expected_output["tool_calls"][0]["name"] == "conversation_task_submit"
    assert imported.source_capture["source"] == snapshot
    assert imported.reference["source_kind"] == "conversation"
    assert imported.reference["source_id"] == str(source_id)


@pytest.mark.asyncio
async def test_voice_executor_import_copies_the_turn_into_the_selected_dataset(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    snapshot = {
        "turn": {
            "id": str(source_id),
            "status": "COMPLETED",
            "transcript": "Quelle heure est-il ?",
            "effective_objective": "Répondre avec l’heure actuelle",
            "assistant_response": "Il est quatorze heures.",
            "execution_result": {"messages": []},
        },
        "session": {"language": "fr"},
        "agent": {
            "code": "alice",
            "first_name": "Alice",
            "last_name": "Voice",
        },
        "llm_calls": [],
    }
    monkeypatch.setattr(
        mechanism_evaluation_service,
        "inspect_voice_turn",
        AsyncMock(return_value=snapshot),
    )
    dataset = await mechanism_evaluation_service.create_dataset(
        "voice_executor",
        MechanismDatasetCreate(name=f"Voice executor import {uuid4()}"),
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_executor_case,
        "voice_executor",
        dataset.id,
        ExecutorCaseImport(source_id=source_id),
    )

    assert imported.dataset_id == dataset.id
    assert imported.input_data["variable_value"] == "Répondre avec l’heure actuelle"
    assert imported.expected_output == {
        "action": "reply",
        "response": "Il est quatorze heures.",
        "tool_calls": [],
    }
    assert imported.source_capture["source"] == snapshot
    assert imported.reference["source_kind"] == "voice"
    assert imported.reference["source_id"] == str(source_id)


@pytest.mark.asyncio
async def test_voice_executor_import_keeps_native_audio_turn_without_transcript_as_draft(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = uuid4()
    snapshot = {
        "turn": {
            "id": str(source_id),
            "sequence": 2,
            "status": "INTERRUPTED",
            "transcript": None,
            "effective_objective": None,
            "assistant_response": "Je vous écoute.",
            "execution_result": None,
        },
        "session": {"language": "fr", "transport_kind": "matrix_call"},
        "agent": {
            "code": "alice",
            "first_name": "Alice",
            "last_name": "Voice",
        },
        "llm_calls": [],
    }
    monkeypatch.setattr(
        mechanism_evaluation_service,
        "inspect_voice_turn",
        AsyncMock(return_value=snapshot),
    )
    dataset = await mechanism_evaluation_service.create_dataset(
        "voice_executor",
        MechanismDatasetCreate(name=f"Native voice import {uuid4()}"),
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_executor_case,
        "voice_executor",
        dataset.id,
        ExecutorCaseImport(source_id=source_id),
    )

    assert imported.name == "Voice turn 2"
    assert imported.readiness == "draft"
    assert imported.input_data["variable_value"] == ""
    assert imported.expected_output == {
        "action": "reply",
        "response": "Je vous écoute.",
        "tool_calls": [],
    }
    assert imported.source_capture["fidelity"] == "partial"
    assert imported.source_capture["missing_input_fields"] == ["message"]
    assert imported.reference["source_id"] == str(source_id)


@pytest.mark.asyncio
async def test_executor_dataset_starts_with_the_current_system_prompt(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_suffix = "## Current system value\n\nDelegate substantial work."
    monkeypatch.setattr(
        executor_prompt_service,
        "default_suffix",
        AsyncMock(return_value=default_suffix),
    )

    dataset = await mechanism_evaluation_service.create_dataset(
        "task_executor",
        MechanismDatasetCreate(name=f"Task prompts {uuid4()}"),
    )

    assert dataset.prompt_suffix == default_suffix
    row = await db.get(LabEvaluationDataset, dataset.id)
    assert row is not None
    assert row.prompt_suffix == default_suffix


@pytest.mark.asyncio
async def test_executor_run_freezes_the_dataset_prompt(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Executor prompt provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    candidate = LLM(
        llm_provider_id=provider.id,
        code=f"executor-candidate-{uuid4()}",
        llm_name="example/executor-candidate",
        label="Executor candidate",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"executor-judge-{uuid4()}",
        llm_name="example/executor-judge",
        label="Executor judge",
    )
    db.add_all([candidate, judge])
    await db.commit()
    monkeypatch.setattr(
        mechanism_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=judge),
    )
    suffix = "## Benchmark suffix\n\nLaunch substantial work as a Task."
    dataset = await mechanism_evaluation_service.create_dataset(
        "conversation_executor",
        MechanismDatasetCreate(
            name=f"Conversation prompts {uuid4()}",
            prompt_suffix=suffix,
        ),
    )
    case = await mechanism_evaluation_service.create_case(
        "conversation_executor",
        dataset.id,
        EvaluationCaseCreate(name="Long report"),
    )
    await mechanism_evaluation_service.update_case(
        "conversation_executor",
        case.id,
        MechanismCaseUpdate(
            revision=case.revision,
            input_data=case.input_data,
            expected_output=case.expected_output,
        ),
    )

    queued = await mechanism_evaluation_service.start_run(
        "conversation_executor",
        dataset.id,
        EvaluationRunStart(llm_id=candidate.id),
    )
    snapshot = queued.configuration_snapshot
    row = await db.get(LabEvaluationRun, queued.id)
    assert row is not None
    frozen_case = row.case_snapshots[0]
    tree = frozen_case["prompts"]["system_tree"]
    rendered = frozen_case["prompts"]["system_markdown"]

    assert snapshot["executor"] == "conversation"
    assert snapshot["prompt_tree_schema"] == "galaris.system-prompt/v1"
    assert snapshot["prompt_renderer"] == "markdown/v1"
    assert snapshot["prompt_source"] == "dataset"
    assert snapshot["prompt_dataset_id"] == str(dataset.id)
    assert snapshot["prompt_dataset_name"] == dataset.name
    assert snapshot["prompt_dataset_revision"] == dataset.revision
    assert snapshot["prompt_suffix"] == suffix
    assert tree["children"][-1]["source"] == "executor_prompt_suffix"
    assert rendered.endswith(suffix)

    await mechanism_evaluation_service.update_dataset(
        "conversation_executor",
        dataset.id,
        EvaluationDatasetUpdate(
            revision=dataset.revision,
            name=dataset.name,
            description=dataset.description,
            prompt_suffix="Changed after the run was queued.",
        ),
    )
    await db.refresh(row)
    assert row.configuration_snapshot == snapshot
    assert row.case_snapshots[0]["prompts"]["system_markdown"] == rendered


@pytest.mark.asyncio
async def test_topic_run_freezes_dataset_catalogue_and_prompts(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Topic snapshot provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    candidate = LLM(
        llm_provider_id=provider.id,
        code=f"topic-candidate-{uuid4()}",
        llm_name="example/topic-candidate",
        label="Topic candidate",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"topic-judge-{uuid4()}",
        llm_name="example/topic-judge",
        label="Topic judge",
    )
    db.add_all([candidate, judge])
    await db.commit()
    monkeypatch.setattr(
        mechanism_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=judge),
    )
    dataset = await mechanism_evaluation_service.create_dataset(
        "topic_classification",
        MechanismDatasetCreate(name=f"Frozen Topics {uuid4()}"),
    )
    configuration = TopicDetectionLabConfiguration(
        topics=[TopicDetectionLabTopic(title="Cuisine japonaise")],
        prompts=TopicDetectionLabPrompts(
            continuity_system_prompt="Frozen continuity prompt.",
            resolution_system_prompt="Frozen resolution prompt.",
        ),
    )
    dataset = await mechanism_evaluation_service.update_topic_dataset_configuration(
        dataset.id,
        TopicDatasetConfigurationUpdate(
            revision=dataset.revision,
            configuration=configuration,
        ),
    )
    case = await mechanism_evaluation_service.create_case(
        "topic_classification",
        dataset.id,
        EvaluationCaseCreate(name=dataset.name),
    )
    await mechanism_evaluation_service.update_case(
        "topic_classification",
        case.id,
        MechanismCaseUpdate(
            revision=case.revision,
            input_data=capture_input(
                "topic_classification",
                {
                    "messages": [{"text": "Préparons des ramen.", "time": 100}],
                    "initial_topic": None,
                },
            ),
            expected_output={"topics": ["Cuisine japonaise"]},
        ),
    )

    queued = await mechanism_evaluation_service.start_run(
        "topic_classification",
        dataset.id,
        EvaluationRunStart(llm_id=candidate.id),
    )
    snapshot = queued.configuration_snapshot

    frozen_configuration = snapshot["topic_configuration"]
    assert frozen_configuration["topics"][0]["title"] == "Cuisine japonaise"
    assert frozen_configuration["prompts"] == {
        "continuity_system_prompt": "Frozen continuity prompt.",
        "resolution_system_prompt": "Frozen resolution prompt.",
    }
    assert snapshot["dataset_id"] == str(dataset.id)
    assert snapshot["dataset_revision"] == dataset.revision


def test_semantic_score_is_weighted_and_independent_of_reference_similarity() -> None:
    rubric = get_rubric("briefing")
    scores = {
        "objective_fidelity": 100,
        "constraint_coverage": 80,
        "actionability": 90,
        "resource_relevance": 70,
        "verification_quality": 60,
    }
    judged = MechanismJudgeOutput(
        dimensions=[
            MechanismJudgeDimension(
                code=dimension.code,
                score_percent=scores[dimension.code],
                assessment="Observable assessment.",
            )
            for dimension in rubric.dimensions
        ],
        strengths=["The result satisfies the objective."],
        weaknesses=["Verification could be more explicit."],
        critical_failures=[],
        confidence_percent=90,
        explanation="Semantically strong despite a different representation.",
    )

    semantic_score = run_inference._semantic_score(rubric, judged)
    strict_score, _ = run_inference._structured_score(
        {
            "result": "Write, check, then deliver the report.",
            "choices": ["provider", "messenger"],
        },
        {
            "result": "Deliver a verified report using Messenger and its provider URI.",
            "choices": ["messenger", "provider"],
        },
    )

    assert semantic_score == 82.0
    assert strict_score == 0.0

    judged.critical_failures = ["A critical constraint was violated."]
    assert run_inference._semantic_score(rubric, judged) == 50.0


@pytest.mark.asyncio
async def test_mechanism_judge_is_pointwise_and_non_normative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric = get_rubric("briefing")
    output = MechanismJudgeOutput(
        dimensions=[
            MechanismJudgeDimension(
                code=dimension.code,
                score_percent=75,
                assessment="Solid with a limited gap.",
            )
            for dimension in rubric.dimensions
        ],
        strengths=["Useful result."],
        weaknesses=["One limited gap."],
        critical_failures=[],
        confidence_percent=85,
        explanation="A valid alternative to the reference.",
    )
    run = AsyncMock(return_value=SimpleNamespace(output=output, cost=0.01))
    monkeypatch.setattr(run_inference, "run_structured", run)

    judged, cost = await run_inference._judge(
        judge=cast(LLM, SimpleNamespace()),
        mechanism="briefing",
        input_data="Prepare and deliver a verified report.",
        expected={"result": "Reference wording"},
        actual={"result": "Different but valid wording"},
    )

    assert judged == output
    assert cost == 0.01
    call = run.await_args.kwargs
    assert "pointwise quality evaluator" in call["system_prompt"]
    assert "non-normative example" in call["system_prompt"]
    assert "never require its wording" in call["system_prompt"]


@pytest.mark.asyncio
async def test_generic_lab_cases_preserve_native_text_and_json_formats(
    db: AsyncSession,
) -> None:
    briefing_dataset = await mechanism_evaluation_service.create_dataset(
        "briefing", MechanismDatasetCreate(name=f"Briefing {uuid4()}")
    )
    briefing_case = await mechanism_evaluation_service.create_case(
        "briefing",
        briefing_dataset.id,
        EvaluationCaseCreate(name="Prepare execution"),
    )
    assert briefing_case.input_data == {"variable_value": "", "context": {}}

    saved = await mechanism_evaluation_service.update_case(
        "briefing",
        briefing_case.id,
        MechanismCaseUpdate(
            revision=briefing_case.revision,
            input_data={"variable_value": "Publish the report"},
            expected_output={
                "result": "Deliver the report with the available resource.",
                "choices": [
                    {
                        "kind": "tool",
                        "identifier": "messenger_send_file",
                        "label": "Messenger",
                        "reason": "The artifact must be delivered.",
                        "score": 1.0,
                    }
                ],
            },
        ),
    )
    assert saved.readiness == "ready"
    assert saved.input_data["variable_value"] == "Publish the report"
    assert saved.expected_output["choices"][0]["kind"] == "tool"

    topic_dataset = await mechanism_evaluation_service.create_dataset(
        "topic_classification", MechanismDatasetCreate(name=f"Topics {uuid4()}")
    )
    topic_case = await mechanism_evaluation_service.create_case(
        "topic_classification",
        topic_dataset.id,
        EvaluationCaseCreate(name="Classify an activity"),
    )
    assert topic_case.input_data["variable_value"] == [""]
    assert topic_case.expected_output == {"topics": [""]}
    with pytest.raises(ValueError, match="expected Topic"):
        await mechanism_evaluation_service.update_case(
            "topic_classification",
            topic_case.id,
            MechanismCaseUpdate(
                revision=topic_case.revision,
                input_data=capture_input(
                    "topic_classification",
                    {
                        "messages": [
                            {"text": "Premier message", "time": 1},
                            {"text": "Deuxième message", "time": 2},
                        ],
                        "initial_topic": None,
                    },
                ),
                expected_output={"topics": ["Un seul topic"]},
            ),
        )
    saved_topic_case = await mechanism_evaluation_service.update_case(
        "topic_classification",
        topic_case.id,
        MechanismCaseUpdate(
            revision=topic_case.revision,
            input_data=capture_input(
                "topic_classification",
                {
                    "messages": [
                        {"text": "Parlons du potager.", "time": 1_786_006_740},
                        {"text": "Et pour les tomates ?", "time": 1_786_006_800},
                    ],
                    "initial_topic": None,
                },
            ),
            expected_output={"topics": ["Potager urbain", "Potager urbain"]},
        ),
    )
    assert saved_topic_case.expected_output == {"topics": ["Potager urbain", "Potager urbain"]}
    assert saved_topic_case.readiness == "ready"
    with pytest.raises(ValueError):
        get_mechanism("topic_classification").validate_output({"topic": "Ancienne référence JSON"})

    await db.execute(
        delete(LabEvaluationCase).where(LabEvaluationCase.id.in_([briefing_case.id, topic_case.id]))
    )
    await db.execute(
        delete(LabEvaluationDataset).where(
            LabEvaluationDataset.id.in_([briefing_dataset.id, topic_dataset.id])
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_generic_lab_task_capture_confirms_parameters_and_preserves_source(
    db: AsyncSession,
) -> None:
    task = Task(label="Prepare a report", status=TaskStatus.SUCCESS)
    db.add(task)
    await db.flush()
    call = LLMCall(
        task_id=task.id,
        provider_name="test",
        requested_model="reference-model",
        effective_model="reference-model",
        status="completed",
        prompt="Task: prepare and deliver the report",
        system_prompt=(
            "You prepare a concise execution briefing for another AI agent before a "
            "complex HIGH-effort task."
        ),
        response_text="",
        tool_calls=[
            {
                "id": "output-1",
                "name": "final_result",
                "arguments": {
                    "result": "Prepare, verify and deliver the report.",
                    "choices": [
                        {
                            "kind": "other",
                            "identifier": "verification",
                            "label": "Verification",
                            "reason": "Check the artifact.",
                            "score": 1.0,
                        }
                    ],
                },
            }
        ],
    )
    db.add(call)
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "briefing", MechanismDatasetCreate(name=f"Imported briefing {uuid4()}")
    )

    candidates = await mechanism_evaluation_service.list_source_candidates("briefing", limit=50)
    capture_request = dispatcher_evaluation_service.DispatcherCaseImport(task_id=task.id)
    with pytest.raises(CaptureParametersMismatch) as mismatch:
        await mechanism_evaluation_service.import_task_case("briefing", dataset.id, capture_request)
    assert not await mechanism_evaluation_service.list_cases("briefing", dataset.id)
    imported = await mechanism_evaluation_service.import_task_case(
        "briefing",
        dataset.id,
        capture_request.model_copy(
            update={"confirmation_token": mismatch.value.detail["confirmation_token"]}
        ),
    )

    assert call.id in {candidate.call_id for candidate in candidates}
    assert imported.source_task_id == task.id
    assert imported.readiness == "draft"
    assert imported.source_capture["input_data"] == call.prompt
    assert imported.expected_output["result"].startswith("Prepare")
    assert imported.source_capture["input_data"] == call.prompt
    assert imported.source_capture["prompts"]["system_prompt"] == call.system_prompt

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == imported.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(LLMCall).where(LLMCall.id == call.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.commit()


@pytest.mark.asyncio
async def test_generic_benchmark_can_only_be_deleted_after_it_stops(
    db: AsyncSession,
) -> None:
    dataset = await mechanism_evaluation_service.create_dataset(
        "topic_classification",
        MechanismDatasetCreate(name=f"Deletable benchmark {uuid4()}"),
    )
    run = LabEvaluationRun(
        dataset_id=dataset.id,
        status="running",
        score_version="topic_classification-score:v2",
        llm_snapshot={},
        judge_llm_snapshot={},
        configuration_snapshot={},
        case_snapshots=[],
        total_cases=0,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    with pytest.raises(ValueError, match="benchmark"):
        await mechanism_evaluation_service.delete_run("topic_classification", run.id)

    run.status = "cancelled"
    await db.commit()
    assert await mechanism_evaluation_service.delete_run("topic_classification", run.id)
    assert await mechanism_evaluation_service.get_run("topic_classification", run.id) is None
    assert not await mechanism_evaluation_service.delete_run("topic_classification", run.id)

    await db.execute(delete(LabEvaluationRun).where(LabEvaluationRun.id == run.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.commit()


@pytest.mark.asyncio
async def test_topic_lab_previews_and_imports_one_human_ai_exchange_as_one_case(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Topic source {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Topic",
        code=f"topic-source-{suffix}",
        agent_driver="internal",
    )
    tool = Tool(
        code=f"topic-source-{suffix}",
        label="Topic source",
        description="",
        connection_schema={},
    )
    db.add_all([agent, tool])
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    topic = Topic(
        title="Potager urbain",
        description="Cultures et entretien d'un petit potager en ville.",
        keywords=["potager", "balcon"],
    )
    db.add_all([connection, topic])
    await db.flush()
    baseline = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
    previous_task = Task(
        label="Choisir des tomates pour le balcon",
        status=TaskStatus.SUCCESS,
        agent_id=agent.id,
        topic_id=topic.id,
        messenger_connection_id=connection.id,
        message_platform="telegram",
        message_group_id="garden-room",
        created_at=baseline,
    )
    messages = [
        Message(
            connection_id=connection.id,
            tool_id=tool.id,
            platform="telegram",
            remote_message_id=f"garden-{index}",
            direction="inbound" if index % 2 == 0 else "outbound",
            room_id="garden-room",
            user_id="alice" if index % 2 == 0 else None,
            text=f"Message potager {index}",
            created_at=baseline + timedelta(minutes=index + 1),
            metadata_={"sender_display_name": "Alice"},
        )
        for index in range(12)
    ]
    unrelated = Message(
        connection_id=connection.id,
        tool_id=tool.id,
        platform="telegram",
        remote_message_id="other-room",
        direction="inbound",
        room_id="other-room",
        user_id="bob",
        text="Ce message ne doit pas entrer dans la fenêtre.",
        created_at=baseline + timedelta(minutes=12),
    )
    previous_task.messages = [
        TaskMessage(
            external_message_id="garden-0",
            platform="telegram",
            text="Message potager 0",
        )
    ]
    db.add_all([previous_task, *messages, unrelated])
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "topic_classification",
        MechanismDatasetCreate(name=f"Imported topic exchange {suffix}"),
    )

    agents = await mechanism_evaluation_service.list_topic_message_agents()
    people = await mechanism_evaluation_service.list_topic_message_people(agent.id)
    range_filter = TopicMessageRangeImport(
        agent_id=agent.id,
        connection_id=connection.id,
        user_id="alice",
        date_from=baseline + timedelta(minutes=1),
        date_to=baseline + timedelta(minutes=12),
    )
    preview = await mechanism_evaluation_service.preview_topic_message_range(range_filter)
    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_topic_message_range, dataset.id, range_filter
    )

    assert any(item.id == agent.id for item in agents)
    assert [(item.connection_id, item.user_id) for item in people] == [
        (connection.id, "alice"),
        (connection.id, "bob"),
    ]
    assert preview.total_count == 12
    assert preview.truncated is False
    assert [item.role for item in preview.messages] == [
        "human" if index % 2 == 0 else "assistant" for index in range(12)
    ]
    assert preview.messages[0].detected_topic == topic.title
    assert imported.name == (
        f"{agent.first_name} {agent.last_name} · alice · 2026-08-01 → 2026-08-01"
    )
    assert imported.readiness == "draft"
    assert imported.expected_output == {"topics": [topic.title, *("" for _ in range(11))]}
    assert imported.source_capture["input_data"]["initial_topic"] is None
    assert imported.input_data["variable_value"] == [
        f"Message potager {index}" for index in range(12)
    ]
    assert imported.source_capture["input_data"]["messages"][0]["sender_external_id"] == "human"
    assert imported.source_capture["input_data"]["messages"][1]["sender_external_id"] == "assistant"
    assert imported.source_capture["input_data"]["messages"][1]["sender_agent_id"] == agent.id
    assert all(
        item["room_external_id"] == "exchange"
        for item in imported.source_capture["input_data"]["messages"]
    )
    assert str(topic.id) not in json.dumps(imported.input_data)
    assert imported.source_capture["reference_output_available"] is True
    assert imported.source_capture["import_filter"]["user_id"] == "alice"
    assert "output" not in imported.source_capture

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == imported.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(Message).where(Message.connection_id == connection.id))
    await db.execute(delete(Task).where(Task.id == previous_task.id))
    await db.execute(delete(Topic).where(Topic.id == topic.id))
    await db.execute(delete(Connection).where(Connection.id == connection.id))
    await db.execute(delete(Tool).where(Tool.id == tool.id))
    await db.execute(delete(Agent).where(Agent.id == agent.id))
    await db.execute(delete(Title).where(Title.id == title.id))
    await db.commit()


@pytest.mark.asyncio
async def test_task_capture_uses_persisted_briefing_when_structured_trace_has_no_text(
    db: AsyncSession,
) -> None:
    task = Task(label="Prepare a durable briefing", status=TaskStatus.SUCCESS)
    task.set_briefing_result(
        BriefingResult(
            prompt="# Execution briefing input\n\nTask: prepare the report",
            system_prompt="Recorded briefing system prompt",
            result="Prepare, verify, then deliver the report.",
            choices=[
                BriefingChoice(
                    kind="other",
                    identifier="verification",
                    label="Verification",
                    reason="Check the result before delivery.",
                    score=1.0,
                )
            ],
        )
    )
    db.add(task)
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "briefing", MechanismDatasetCreate(name=f"Task briefing {uuid4()}")
    )

    imported = await capture_with_source_parameters(
        mechanism_evaluation_service.import_task_case,
        "briefing",
        dataset.id,
        dispatcher_evaluation_service.DispatcherCaseImport(task_id=task.id),
    )

    assert imported.readiness == "draft"
    assert imported.input_data["variable_value"] == (task.objective or "")
    assert imported.expected_output["result"] == "Prepare, verify, then deliver the report."
    assert imported.expected_output["choices"][0]["identifier"] == "verification"
    assert imported.source_capture["fidelity"] == "context_requires_review"

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == imported.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.commit()


@pytest.mark.asyncio
async def test_generic_worker_is_isolated_from_dispatcher_and_scores_with_lab_judge(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Mechanism provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    candidate = LLM(
        llm_provider_id=provider.id,
        code=f"memory-candidate-{uuid4()}",
        llm_name="example/memory-candidate",
        label="Memory candidate",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"memory-judge-{uuid4()}",
        llm_name="example/memory-judge",
        label="Memory judge",
    )
    db.add_all([candidate, judge])
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "memory_extraction", MechanismDatasetCreate(name=f"Memory run {uuid4()}")
    )
    created_row = LabEvaluationCase(
        dataset_id=dataset.id,
        name="Remember a preference",
        enabled=True,
        readiness="draft",
        input_data={"variable_value": ""},
        expected_output={},
        reference={"source_kind": "task"},
        source_capture={"source_kind": "task"},
    )
    db.add(created_row)
    await db.commit()
    await db.refresh(created_row)
    created = await mechanism_evaluation_service._case(  # pyright: ignore[reportPrivateUsage]
        "memory_extraction", created_row.id
    )
    expected = {
        "operations": [
            {
                "action": "CREATE",
                "title": "Preferred language",
                "content": "The user prefers French.",
                "memory_type": "core",
                "keywords": ["language"],
                "retention_reason": "explicit_user_preference",
                "future_utility": "high",
                "reason": "Explicit preference",
            }
        ],
        "relevant_memory_ids": [],
        "ranked_memory_ids": [],
    }
    dataset_row = await db.get(LabEvaluationDataset, dataset.id)
    dataset_row.parameters = {
        "source_kind": "task",
    }
    await db.commit()
    saved = await mechanism_evaluation_service.update_case(
        "memory_extraction",
        created_row.id,
        MechanismCaseUpdate(
            revision=created.revision,
            input_data=capture_input(
                "memory_extraction",
                {
                    "source_kind": "task",
                    "topic": {"id": "topic-1", "title": "Preferences"},
                    "history": [],
                    "current": [
                        {
                            "speaker_name": "User",
                            "speaker_kind": "human",
                            "text": "The user explicitly says they prefer French.",
                        }
                    ],
                    "task_trace": {"objective": "Remember the explicit preference."},
                    "existing_memories": [],
                },
            ),
            expected_output=expected,
        ),
    )
    monkeypatch.setattr(
        mechanism_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=judge),
    )
    monkeypatch.setattr(
        run_inference,
        "evaluate_mechanism",
        AsyncMock(return_value=(saved.expected_output, 0.03)),
    )
    monkeypatch.setattr(
        run_inference,
        "_judge",
        AsyncMock(
            return_value=(
                MechanismJudgeOutput(
                    dimensions=[
                        MechanismJudgeDimension(
                            code=item.code,
                            score_percent=100,
                            assessment="No material gap.",
                        )
                        for item in get_rubric("memory_extraction").dimensions
                    ],
                    strengths=["Grounded and durable."],
                    weaknesses=[],
                    critical_failures=[],
                    confidence_percent=95,
                    explanation="Equivalent output.",
                ),
                0.01,
            )
        ),
    )

    queued = await mechanism_evaluation_service.start_run(
        "memory_extraction", dataset.id, EvaluationRunStart(llm_id=candidate.id)
    )

    assert await mechanism_evaluation_service.process_runs() == 1
    assert await mechanism_evaluation_service.process_runs() == 1
    completed = await mechanism_evaluation_service.get_run("memory_extraction", queued.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.score_percent == 100
    assert completed.structured_score_percent == 100
    assert completed.score_version == "memory_extraction-score"
    assert completed.results[0].actual_output == saved.expected_output
    assert completed.results[0].score_details["reference_role"] == "non_normative_example"
    assert (
        completed.configuration_snapshot["memory_extraction_configuration"] == dataset.configuration
    )
    assert completed.results[0].score_details["memory_extraction"]["decision"] == "CREATE"

    await db.execute(delete(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == queued.id))
    await db.execute(delete(LabEvaluationRun).where(LabEvaluationRun.id == queued.id))
    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == created_row.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(LLM).where(LLM.id.in_([candidate.id, judge.id])))
    await db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
    await db.commit()


@pytest.mark.asyncio
async def test_generic_worker_never_replaces_a_failed_judge_with_strict_similarity(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Failed judge provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    candidate = LLM(
        llm_provider_id=provider.id,
        code=f"briefing-candidate-{uuid4()}",
        llm_name="example/briefing-candidate",
        label="Briefing candidate",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"failed-judge-{uuid4()}",
        llm_name="example/failed-judge",
        label="Unavailable judge",
    )
    db.add_all([candidate, judge])
    await db.commit()
    dataset = await mechanism_evaluation_service.create_dataset(
        "briefing", MechanismDatasetCreate(name=f"Failed judgment {uuid4()}")
    )
    created = await mechanism_evaluation_service.create_case(
        "briefing",
        dataset.id,
        EvaluationCaseCreate(name="Prepare a report"),
    )
    expected = {
        "result": "Prepare and verify the report.",
        "choices": [],
    }
    saved = await mechanism_evaluation_service.update_case(
        "briefing",
        created.id,
        MechanismCaseUpdate(
            revision=created.revision,
            input_data={"variable_value": "Prepare and verify the report."},
            expected_output=expected,
        ),
    )
    monkeypatch.setattr(
        mechanism_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=judge),
    )
    monkeypatch.setattr(
        run_inference,
        "evaluate_mechanism",
        AsyncMock(return_value=(saved.expected_output, 0.03)),
    )
    monkeypatch.setattr(
        run_inference,
        "_judge",
        AsyncMock(side_effect=RuntimeError("Judge provider failed")),
    )

    queued = await mechanism_evaluation_service.start_run(
        "briefing", dataset.id, EvaluationRunStart(llm_id=candidate.id)
    )
    assert await mechanism_evaluation_service.process_runs() == 1
    assert await mechanism_evaluation_service.process_runs() == 1
    completed = await mechanism_evaluation_service.get_run("briefing", queued.id)

    assert completed is not None
    assert completed.status == "partial"
    assert completed.score_percent is None
    assert completed.structured_score_percent == 100
    assert completed.results[0].score_percent is None
    assert completed.results[0].structured_score_percent == 100
    assert completed.results[0].score_details["judge_status"] == "failed"
    assert completed.results[0].judge_output == {"error": "Judge provider failed"}

    await db.execute(delete(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == queued.id))
    await db.execute(delete(LabEvaluationRun).where(LabEvaluationRun.id == queued.id))
    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == created.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(LLM).where(LLM.id.in_([candidate.id, judge.id])))
    await db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
    await db.commit()


def test_dispatcher_critical_constraints_cannot_be_compensated() -> None:
    from app.lab.objective_checks import check_output

    checks = check_output(
        "dispatcher",
        {"forced_route": "EXEC"},
        {
            "route": "PLAN",
            "effort": "standard",
            "language": "en",
            "reasoning": "A plan is needed",
        },
    )
    assert any(
        check["code"] == "forced_route" and not check["passed"] and check["critical"]
        for check in checks
    )


@pytest.mark.asyncio
async def test_manual_dispatcher_case_starts_as_draft_and_becomes_ready_when_saved(
    db: AsyncSession,
) -> None:
    dataset = await dispatcher_evaluation_service.create_dataset(
        EvaluationDatasetCreate(name=f"Manual cases {uuid4()}")
    )

    created = await dispatcher_evaluation_service.create_case(
        dataset.id,
        EvaluationCaseCreate(name="Manual route case"),
    )

    assert created.name == "Manual route case"
    assert created.source_task_id is None
    assert created.readiness == "draft"
    assert created.input_data["variable_value"] == ""
    assert created.input_data == {"variable_value": "", "context": {"messages": []}}
    assert created.expected_output == {
        "reasoning": "",
        "route": "EXEC",
        "effort": "standard",
        "language": "fr",
    }
    assert created.source_capture == {}

    saved = await dispatcher_evaluation_service.update_case(
        created.id,
        EvaluationCaseUpdate(
            revision=created.revision,
            input_data={**created.input_data, "variable_value": "Répondre au message"},
            expected_output=DispatcherExpectedDecision(
                reasoning="Une réponse directe suffit.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
        ),
    )

    assert saved.readiness == "ready"
    assert saved.input_data["variable_value"] == "Répondre au message"

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == created.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.commit()


@pytest.mark.asyncio
async def test_dispatcher_case_import_copies_a_real_task_and_can_be_duplicated(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        label="Send the report",
        objective="Deliver the report",
        status=TaskStatus.EXEC,
        data={"text": "Envoie le rapport", "api_key": "must-not-be-copied"},
    )
    task.set_dispatch_result(
        DispatchResult(
            prompt="Captured user prompt",
            system_prompt="Captured system prompt",
            decision=DispatchDecision(
                reasoning="A delivery requires one external action.",
                route="EXEC",
                effort="high",
                language="fr",
            ),
            driver_code="internal",
            allowed_routes=["EXEC", "PLAN"],
        )
    )
    task.dispatch_result["decision"]["requires_action"] = True
    db.add(task)
    await db.commit()
    dataset = await dispatcher_evaluation_service.create_dataset(
        EvaluationDatasetCreate(name=f"Dispatcher {uuid4()}")
    )

    from fastapi import HTTPException
    from app.lab.router import import_dispatcher_case

    monkeypatch.setitem(import_dispatcher_case.__globals__, "_task_in_scope", AsyncMock())
    request = dispatcher_evaluation_service.DispatcherCaseImport(task_id=task.id)
    with pytest.raises(HTTPException) as conflict:
        await import_dispatcher_case(dataset.id, request)
    assert conflict.value.status_code == 409
    assert conflict.value.detail["code"] == "dataset_parameters_mismatch"
    assert not await dispatcher_evaluation_service.list_cases(dataset.id)
    imported = await import_dispatcher_case(
        dataset.id,
        request.model_copy(
            update={"confirmation_token": conflict.value.detail["confirmation_token"]}
        ),
    )
    assert imported.readiness == "draft"
    assert "parameters" not in imported.input_data
    dataset_row = await db.get(LabEvaluationDataset, dataset.id)
    assert dataset_row.parameters == dataset.parameters
    duplicate = await dispatcher_evaluation_service.duplicate_case(imported.id)

    assert imported.source_task_id == task.id
    assert imported.source_capture["prompts"] == {
        "mode": "captured",
        "prompt": "Captured user prompt",
        "system_prompt": "Captured system prompt",
    }
    assert imported.input_data["variable_value"] == task.objective
    assert imported.expected_output["route"] == "EXEC"
    assert "requires_action" not in imported.expected_output
    assert imported.source_capture["input_data"]["data"] == {"text": "Envoie le rapport"}
    assert imported.source_capture["output"]["decision"] == imported.expected_output
    assert duplicate.id != imported.id
    assert duplicate.derived_from_case_id == imported.id
    assert duplicate.source_capture == imported.source_capture

    await db.execute(
        delete(LabEvaluationCase).where(LabEvaluationCase.id.in_([imported.id, duplicate.id]))
    )
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.commit()


@pytest.mark.asyncio
async def test_generate_expected_uses_the_configured_lab_model(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Expected provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    lab_llm = LLM(
        llm_provider_id=provider.id,
        code=f"lab-expected-{uuid4()}",
        llm_name="example/lab-reference",
        label="Configured Lab reference model",
    )
    dataset = LabEvaluationDataset(name=f"Generated expectation {uuid4()}", mechanism="dispatcher")
    db.add_all([lab_llm, dataset])
    await db.flush()
    case = LabEvaluationCase(
        dataset_id=dataset.id,
        name="Choose a route",
        input_data={"variable_value": "Send a report"},
        expected_output={},
    )
    db.add(case)
    await db.commit()

    expected_result = DispatchResult(
        prompt="Built by the dispatcher",
        system_prompt="Current dispatcher instructions",
        cost=0.04,
        decision=DispatchDecision(
            reasoning="Sending the report requires an action.",
            route="EXEC",
            effort="standard",
            language="en",
        ),
    )
    resolve_lab_model = AsyncMock(return_value=lab_llm)
    evaluate = AsyncMock(return_value=expected_result)
    monkeypatch.setattr(
        dispatcher_evaluation_service.llm_service,
        "get_profile_llm",
        resolve_lab_model,
    )
    monkeypatch.setattr(
        dispatcher_evaluation_service,
        "evaluate_dispatcher_input",
        evaluate,
    )

    generated = await dispatcher_evaluation_service.generate_expected(
        case.id,
        EvaluationExpectedGenerate(input_data=case.input_data),
    )

    assert generated.output.route == "EXEC"
    assert generated.llm["id"] == lab_llm.id
    assert generated.cost == 0.04
    resolve_lab_model.assert_awaited_once_with(model_usages.LAB)
    assert (
        evaluate.await_args.kwargs["input_data"]["objective"] == case.input_data["variable_value"]
    )
    assert evaluate.await_args.kwargs["llm"].id == lab_llm.id

    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == case.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(LLM).where(LLM.id == lab_llm.id))
    await db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
    await db.commit()


@pytest.mark.asyncio
async def test_dispatcher_run_freezes_cases_and_persists_a_perfect_score(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Lab provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    llm = LLM(
        llm_provider_id=provider.id,
        code=f"lab-test-{uuid4()}",
        llm_name="example/dispatcher-test",
        label="Dispatcher test model",
    )
    judge = LLM(
        llm_provider_id=provider.id,
        code=f"lab-judge-{uuid4()}",
        llm_name="example/lab-judge",
        label="Configured Lab model",
    )
    task = Task(label="Answer briefly", objective="Answer briefly", status=TaskStatus.EXEC)
    expected_result = DispatchResult(
        prompt="Captured prompt",
        system_prompt="Captured system",
        cost=0.03,
        decision=DispatchDecision(
            reasoning="A direct contextual reply is sufficient.",
            route="EXEC",
            effort="standard",
            language="en",
        ),
        allowed_routes=["EXEC", "PLAN"],
    )
    task.set_dispatch_result(expected_result)
    db.add_all([llm, judge, task])
    await db.commit()
    dataset = await dispatcher_evaluation_service.create_dataset(
        EvaluationDatasetCreate(name=f"Frozen run {uuid4()}")
    )
    case = await capture_with_source_parameters(
        dispatcher_evaluation_service.import_task_case,
        dataset.id,
        dispatcher_evaluation_service.DispatcherCaseImport(task_id=task.id),
    )
    evaluate = AsyncMock(return_value=expected_result)
    monkeypatch.setattr(mechanism_registry, "evaluate_dispatcher_input", evaluate)
    resolve_judge = AsyncMock(return_value=judge)
    monkeypatch.setattr(
        dispatcher_evaluation_service.llm_service,
        "get_profile_llm",
        resolve_judge,
    )
    judge_reasoning = AsyncMock(
        return_value=(
            MechanismJudgeOutput(
                dimensions=[
                    {"code": dim.code, "score_percent": 100, "assessment": "Supported"}
                    for dim in get_rubric("dispatcher").dimensions
                ],
                confidence_percent=95,
                explanation="Supported",
            ),
            0.02,
        )
    )
    monkeypatch.setattr(run_inference, "_judge", judge_reasoning)

    queued = await dispatcher_evaluation_service.start_run(
        dataset.id, EvaluationRunStart(llm_id=llm.id)
    )
    task.set_dispatch_result(
        DispatchResult(
            prompt="Changed after run start",
            system_prompt="Changed after run start",
            decision=DispatchDecision(
                reasoning="Changed",
                route="PLAN",
                effort="high",
                language="fr",
            ),
        )
    )
    await db.commit()

    assert await mechanism_evaluation_service.process_runs() == 1
    assert await mechanism_evaluation_service.process_runs() == 1
    completed = await dispatcher_evaluation_service.get_run(queued.id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.score_percent == 100.0
    assert completed.structured_score_percent == 100.0
    assert completed.judge_llm_id == judge.id
    assert completed.judge_llm_snapshot["label"] == judge.label
    assert len(completed.results) == 1
    assert completed.results[0].case_id == case.id
    assert "prompts" not in completed.results[0].case_snapshot
    assert (
        completed.results[0].case_snapshot["input_data"]["variable_value"]
        == case.input_data["variable_value"]
    )
    assert completed.results[0].actual_output == case.expected_output
    assert (
        evaluate.await_args.kwargs["input_data"]["objective"] == case.input_data["variable_value"]
    )
    assert evaluate.await_args.kwargs["llm"].id == llm.id
    resolve_judge.assert_awaited_once_with(model_usages.LAB)
    judge_reasoning.assert_awaited_once()

    await db.execute(delete(LabEvaluationRunCase).where(LabEvaluationRunCase.run_id == queued.id))
    await db.execute(delete(LabEvaluationRun).where(LabEvaluationRun.id == queued.id))
    await db.execute(delete(LabEvaluationCase).where(LabEvaluationCase.id == case.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.execute(delete(LLM).where(LLM.id.in_([llm.id, judge.id])))
    await db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
    await db.commit()


@pytest.mark.asyncio
async def test_benchmark_analysis_receives_all_results_and_persists_markdown(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = LLMProvider(
        name=f"Analysis provider {uuid4()}",
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    llm = LLM(
        llm_provider_id=provider.id,
        code=f"benchmark-analysis-{uuid4()}",
        llm_name="example/benchmark-analysis",
        label="Benchmark analysis model",
    )
    dataset = LabEvaluationDataset(name=f"Analyzed benchmark {uuid4()}", mechanism="dispatcher")
    db.add_all([llm, dataset])
    await db.flush()
    run = LabEvaluationRun(
        dataset_id=dataset.id,
        llm_id=llm.id,
        status="completed",
        score_percent=62.0,
        structured_score_percent=62.0,
        llm_snapshot={"label": "Candidate"},
        total_cases=1,
        completed_cases=1,
    )
    db.add(run)
    await db.flush()
    result = LabEvaluationRunCase(
        run_id=run.id,
        case_snapshot={
            "name": "Route a report",
            "input_data": {"objective": "Send the report"},
            "expected_output": {"route": "EXEC", "effort": "high"},
        },
        actual_output={"route": "EXEC", "effort": "standard"},
        score_details={"matches": {"route": True, "effort": False}},
        score_percent=62.0,
        structured_score_percent=62.0,
    )
    db.add(result)
    await db.commit()

    captured: dict[str, Any] = {}

    async def analyze(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            output=BenchmarkAnalysisContent(
                summary="The route is correct but effort is underestimated.",
                strengths=["The route is consistently correct."],
                weaknesses=["Effort is underestimated."],
                improvements=["Add clearer high-effort examples."],
                case_analyses=[
                    BenchmarkCaseAnalysis(
                        case_name="Route a report",
                        score_percent=62.0,
                        assessment="The route matches, while effort does not.",
                        strengths=["Correct route."],
                        weaknesses=["Incorrect effort."],
                        improvements=["Clarify the effort rubric."],
                    )
                ],
                conclusion="The model needs effort calibration.",
            ),
            cost=0.12,
        )

    monkeypatch.setattr(
        dispatcher_evaluation_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=llm),
    )
    monkeypatch.setattr(dispatcher_evaluation_service, "run_structured", analyze)

    analyzed = await dispatcher_evaluation_service.analyze_run(
        run.id, EvaluationRunAnalysisRequest(language="fr")
    )

    assert '"input": {"objective": "Send the report"}' in captured["prompt"]
    assert '"actual_output": {"route": "EXEC", "effort": "standard"}' in captured["prompt"]
    assert analyzed.analysis_markdown is not None
    assert "## Forces" in analyzed.analysis_markdown
    assert "## Faiblesses" in analyzed.analysis_markdown
    assert "## Pistes d’amélioration" in analyzed.analysis_markdown
    assert "### Route a report" in analyzed.analysis_markdown
    assert analyzed.analysis_llm_snapshot["label"] == llm.label
    assert analyzed.analysis_cost == 0.12
    assert analyzed.analysis_language == "fr"
    assert analyzed.analysis_created_at is not None

    await db.execute(delete(LabEvaluationRunCase).where(LabEvaluationRunCase.id == result.id))
    await db.execute(delete(LabEvaluationRun).where(LabEvaluationRun.id == run.id))
    await db.execute(delete(LabEvaluationDataset).where(LabEvaluationDataset.id == dataset.id))
    await db.execute(delete(LLM).where(LLM.id == llm.id))
    await db.execute(delete(LLMProvider).where(LLMProvider.id == provider.id))
    await db.commit()


def test_analysis_prompt_describes_real_galaris_levers() -> None:
    assert "not separate\n  configurable Lab targets" in ANALYST_SYSTEM_PROMPT
    assert "standard\n  and high-effort models" in ANALYST_SYSTEM_PROMPT
    assert "Tools and connections" in ANALYST_SYSTEM_PROMPT
    assert "Preferences -> Tasks" in ANALYST_SYSTEM_PROMPT
    assert "model's prose is never proof" in ANALYST_SYSTEM_PROMPT


def test_evidence_sanitizer_redacts_nested_credentials() -> None:
    value = evidence_service.sanitize_evidence(
        {
            "api_key": "secret",
            "input_tokens": 123,
            "TASK_AGENT_MAX_REQUESTS": 50,
            "nested": {
                "access_token": "token",
                "safe": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            },
        }
    )
    assert value == {
        "api_key": "[REDACTED]",
        "input_tokens": 123,
        "TASK_AGENT_MAX_REQUESTS": 50,
        "nested": {
            "access_token": "[REDACTED]",
            "safe": "Authorization: Bearer [REDACTED]",
        },
    }


@pytest.mark.asyncio
async def test_task_selection_is_idempotent_and_candidates_exclude_it(
    db: AsyncSession,
) -> None:
    selected = Task(label="Selected task", status=TaskStatus.SUCCESS)
    candidate = Task(label="Candidate task", status=TaskStatus.ERROR)
    db.add_all([selected, candidate])
    await db.commit()

    first = await evaluation_service.add_task(selected.id)
    second = await evaluation_service.add_task(selected.id)
    candidates = await evaluation_service.list_candidates(limit=500)
    references = await evaluation_service.list_tasks()

    assert first.task_id == selected.id
    assert second.task_id == selected.id
    assert [row.task_id for row in references].count(selected.id) == 1
    assert candidate.id in {row.task_id for row in candidates}
    assert selected.id not in {row.task_id for row in candidates}

    await db.execute(delete(LabTask).where(LabTask.task_id == selected.id))
    await db.execute(delete(Task).where(Task.id.in_([selected.id, candidate.id])))
    await db.commit()


@pytest.mark.asyncio
async def test_live_evidence_contains_attempts_llm_calls_and_related_tasks(
    db: AsyncSession,
) -> None:
    root = Task(
        label="Analyze me",
        objective="Send a sourced answer",
        status=TaskStatus.ERROR,
        last_error="Provider timeout",
        data={"api_key": "must-not-leak"},
        execution_result={"success": False, "result": "Timed out"},
    )
    db.add(root)
    await db.flush()
    child = Task(
        label="Related child",
        parent_id=root.id,
        status=TaskStatus.SUCCESS,
        execution_result={"success": True, "result": "Partial research"},
    )
    attempt = TaskAttempt(
        task_id=root.id,
        attempt_number=1,
        phase="DISPATCH",
        status="ERROR",
        worker_id="test-worker",
        lease_token=uuid4(),
        retryable=False,
        error="Provider timeout",
    )
    call = LLMCall(
        task_id=root.id,
        provider_name="test",
        requested_model="test-model",
        effective_model="test-model",
        status="error",
        prompt="Complete the objective",
        system_prompt="System",
        error="Provider timeout",
        tool_calls=[{"id": "call-1", "name": "web_search", "arguments": {}}],
    )
    db.add_all([child, attempt, call])
    await db.commit()

    bundle = await evidence_service.build_task_evidence(root.id)

    assert bundle.coverage.task_count == 2
    assert bundle.coverage.attempt_count == 1
    assert bundle.coverage.llm_call_count == 1
    assert bundle.coverage.tool_call_count == 1
    assert bundle.payload["selected_task"]["data"]["api_key"] == "[REDACTED]"
    assert bundle.payload["related_tasks"][0]["uri"] == f"galaris://task/{child.id}"
    assert any(
        signal["code"] == "attempt_failures" for signal in bundle.payload["deterministic_signals"]
    )

    await db.execute(delete(LLMCall).where(LLMCall.id == call.id))
    await db.execute(delete(TaskAttempt).where(TaskAttempt.id == attempt.id))
    await db.execute(delete(Task).where(Task.id.in_([child.id, root.id])))
    await db.commit()


@pytest.mark.asyncio
async def test_analysis_is_a_direct_structured_llm_call_without_task_pipeline(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        label="Independent analysis",
        objective="Return a sourced answer",
        status=TaskStatus.SUCCESS,
        execution_result={"success": True, "result": "Answer without source"},
    )
    db.add(task)
    await db.commit()
    await evaluation_service.add_task(task.id)

    fake_llm = SimpleNamespace(label="Lab analyzer")
    build_model = AsyncMock(return_value=object())
    captured: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["agent_args"] = args
            captured["agent_kwargs"] = kwargs

        async def run(self, prompt: str) -> SimpleNamespace:
            captured["prompt"] = prompt
            return SimpleNamespace(
                output=TaskAnalysisContent(
                    verdict="partial",
                    confidence=0.86,
                    summary="The answer omitted the requested source.",
                    goal_assessment="Only part of the functional objective was met.",
                    observed_outcome="A usable answer was produced without a citation.",
                    findings=[],
                    root_causes=[],
                    recommendations=[],
                )
            )

    monkeypatch.setattr(
        analysis_service.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=fake_llm),
    )
    monkeypatch.setattr(analysis_service, "build_model_for_llm", build_model)
    monkeypatch.setattr(analysis_service, "PydanticAgent", cast(Any, FakeAgent))
    monkeypatch.setattr(analysis_service, "estimate_cost_from_usage", lambda *_args: 0.02)

    analysis = await analysis_service.analyze_task(
        task_id=task.id,
        language="en",
        user_context="I expected a verifiable source.",
    )

    build_model.assert_awaited_once_with(
        fake_llm,
        purpose=LLMCallPurpose.LAB_TASK_ANALYSIS,
        reasoning_effort=None,
    )
    assert captured["agent_kwargs"]["system_prompt"] == ANALYST_SYSTEM_PROMPT
    assert "SELECTED_TASK" in str(captured["prompt"])
    assert "I expected a verifiable source." in str(captured["prompt"])
    assert str(task.id) in str(captured["prompt"])
    assert analysis.task_id == task.id
    assert analysis.task_revision == task.revision
    assert analysis.model == "Lab analyzer"
    assert analysis.cost == 0.02
    assert analysis.evidence.has_final_result is True
    assert analysis.created_at is not None

    row = await db.get(LabTaskDiagnosis, analysis.id)
    assert row is not None
    assert row.content["summary"] == "The answer omitted the requested source."
    assert row.evidence_coverage["has_final_result"] is True
    assert "user_context" not in row.content
    diagnoses = await diagnosis_service.list_diagnoses(task.id)
    assert [diagnosis.id for diagnosis in diagnoses] == [analysis.id]

    assert await evaluation_service.remove_task(task.id) is True
    await evaluation_service.add_task(task.id)
    retained = await diagnosis_service.list_diagnoses(task.id)
    assert [diagnosis.id for diagnosis in retained] == [analysis.id]

    await db.execute(delete(LabTaskDiagnosis).where(LabTaskDiagnosis.task_id == task.id))
    await db.execute(delete(LabTask).where(LabTask.task_id == task.id))
    await db.execute(delete(Task).where(Task.id == task.id))
    await db.commit()


async def capture_with_source_parameters(capture, *args):
    """Use matching dataset fixtures for tests of faithful source reproduction."""
    try:
        return await capture(*args)
    except CaptureParametersMismatch as mismatch:
        dataset = await get_db().get(LabEvaluationDataset, UUID(mismatch.detail["dataset_id"]))
        dataset.parameters = {
            **dataset.parameters,
            **{
                difference["name"]: difference["source_value"]
                for difference in mismatch.detail["differences"]
                if difference.get("scope") != "configuration"
            },
        }
        dataset.configuration = {
            **dataset.configuration,
            **{
                difference["name"]: difference["source_value"]
                for difference in mismatch.detail["differences"]
                if difference.get("scope") == "configuration"
            },
        }
        await get_db().commit()
        return await capture(*args)
