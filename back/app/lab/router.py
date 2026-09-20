"""Private API for task-focused AI analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope
from core.i18n import tr

from . import (
    analysis_service,
    diagnosis_service,
    dispatcher_evaluation_service,
    evaluation_service,
    executor_prompt_service,
    mechanism_evaluation_service,
)
from .access import (
    ALL_EVALUATION_LAB_PRIVILEGES,
    DISPATCHER_PRIVILEGES,
    MECHANISM_EDIT_PRIVILEGES,
    MECHANISM_READ_PRIVILEGES,
    MECHANISM_PRIVILEGES,
)
from .assertions import (
    LabMechanismEditPrivilegeAssertion,
    LabMechanismReadPrivilegeAssertion,
)
from .dispatcher_evaluation_service import RevisionConflictError
from . import judgment_service, human_review_service
from .contracts import LabInput
from .capture_service import CaptureParametersMismatch
from .schemas import CaptureRequest, LabInputPreview, HumanReviewCreate, HumanReviewQueue
from .schemas import (
    DispatcherCaseImport,
    DispatcherTaskCandidate,
    EvaluationCaseCreate,
    EvaluationCaseRead,
    EvaluationCaseUpdate,
    EvaluationDatasetCreate,
    EvaluationDatasetRead,
    EvaluationDatasetUpdate,
    EvaluationExpectedGenerate,
    EvaluationExpectedGenerated,
    EvaluationRunDetail,
    EvaluationRunAnalysisRequest,
    EvaluationRunRead,
    EvaluationRunStart,
    EvaluationRejudge,
    ExecutorCaseImport,
    ExecutorPromptDefaultsRead,
    LabConfig,
    LabTaskAdd,
    LabTaskReference,
    LabTaskSummary,
    MechanismCaseImport,
    MechanismCaseUpdate,
    MechanismDatasetCreate,
    MechanismDescriptorRead,
    MechanismExpectedGenerate,
    MechanismExpectedGenerated,
    MechanismSourceCandidate,
    MemoryExtractionDatasetConfigurationUpdate,
    MemoryExtractionPromptDefaultRead,
    PlannerDatasetConfigurationUpdate,
    PlannerPromptDefaultRead,
    TopicMessageAgentRead,
    TopicMessagePersonRead,
    TopicMessageRangeImport,
    TopicMessageRangePreview,
    TopicDatasetConfigurationUpdate,
    EvaluationMechanism,
    TaskAnalysis,
    TaskAnalysisRequest,
)

router = APIRouter(prefix="/evaluation", tags=["task-analysis-lab"])


@router.get("/{mechanism}/runs/{run_id}/human-review", response_model=HumanReviewQueue)
@authorize(privileges=MECHANISM_READ_PRIVILEGES, assertion=LabMechanismReadPrivilegeAssertion)
async def read_human_review(
    mechanism: EvaluationMechanism, run_id: UUID, campaign_id: UUID | None = None
) -> HumanReviewQueue:
    try:
        return await human_review_service.review_queue(mechanism, run_id, campaign_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{mechanism}/runs/{run_id}/human-review", response_model=HumanReviewQueue)
@authorize(privileges=MECHANISM_EDIT_PRIVILEGES, assertion=LabMechanismEditPrivilegeAssertion)
async def submit_human_review(
    mechanism: EvaluationMechanism, run_id: UUID, data: HumanReviewCreate
) -> HumanReviewQueue:
    try:
        return await human_review_service.submit_review(mechanism, run_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{mechanism}/datasets/{dataset_id}/preview", response_model=LabInputPreview)
@authorize(privileges=MECHANISM_READ_PRIVILEGES, assertion=LabMechanismReadPrivilegeAssertion)
async def preview_lab_input(
    mechanism: EvaluationMechanism, dataset_id: UUID, data: LabInput
) -> LabInputPreview:
    try:
        return await mechanism_evaluation_service.preview_input(mechanism, dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{mechanism}/runs/{run_id}/rejudge", response_model=EvaluationRunRead)
@authorize(privileges=MECHANISM_EDIT_PRIVILEGES, assertion=LabMechanismEditPrivilegeAssertion)
async def rejudge_benchmark(
    mechanism: EvaluationMechanism, run_id: UUID, data: EvaluationRejudge
) -> EvaluationRunRead:
    try:
        return await judgment_service.rejudge(mechanism, run_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{mechanism}/runs/{run_id}/resume", response_model=EvaluationRunRead)
@authorize(privileges=MECHANISM_EDIT_PRIVILEGES, assertion=LabMechanismEditPrivilegeAssertion)
async def resume_benchmark(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunRead:
    try:
        return await judgment_service.resume(mechanism, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _detail(key: str) -> str:
    return await tr(f"evaluation_api.errors.{key}")


async def _task_in_scope(task_id: UUID) -> None:
    scope = await current_management_scope()
    if (
        await evaluation_service.get_task(
            task_id,
            agent_ids=scope.agent_ids,
        )
        is None
    ):
        raise HTTPException(status_code=404, detail=await _detail("task_not_found"))


@router.get("/config", response_model=LabConfig)
@authorize(privileges=ALL_EVALUATION_LAB_PRIVILEGES)
async def read_config() -> LabConfig:
    return await evaluation_service.config()


@router.get("/candidates", response_model=list[LabTaskSummary])
@authorize(privileges=[Privileges.EVALUATION_ACCESS, Privileges.EVALUATION_EDIT])
async def read_candidates(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    search: Annotated[str | None, Query(max_length=300)] = None,
) -> list[LabTaskSummary]:
    scope = await current_management_scope()
    return await evaluation_service.list_candidates(
        limit=limit,
        search=search,
        agent_ids=scope.agent_ids,
    )


@router.get("/tasks", response_model=list[LabTaskReference])
@authorize(privileges=[Privileges.EVALUATION_ACCESS, Privileges.EVALUATION_EDIT])
async def read_lab_tasks() -> list[LabTaskReference]:
    scope = await current_management_scope()
    return await evaluation_service.list_tasks(agent_ids=scope.agent_ids)


@router.post(
    "/tasks",
    response_model=LabTaskReference,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.EVALUATION_EDIT)
async def add_lab_task(data: LabTaskAdd) -> LabTaskReference:
    try:
        scope = await current_management_scope()
        return await evaluation_service.add_task(
            data.task_id,
            agent_ids=scope.agent_ids,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.EVALUATION_EDIT)
async def remove_lab_task(task_id: UUID) -> None:
    scope = await current_management_scope()
    if not await evaluation_service.remove_task(
        task_id,
        agent_ids=scope.agent_ids,
    ):
        raise HTTPException(status_code=404, detail=await _detail("lab_task_not_found"))


@router.get("/tasks/{task_id}/diagnoses", response_model=list[TaskAnalysis])
@authorize(privileges=[Privileges.EVALUATION_ACCESS, Privileges.EVALUATION_EDIT])
async def read_task_diagnoses(
    task_id: UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[TaskAnalysis]:
    try:
        await _task_in_scope(task_id)
        return await diagnosis_service.list_diagnoses(task_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/analyze", response_model=TaskAnalysis)
@authorize(privileges=Privileges.EVALUATION_EDIT)
async def analyze_task(task_id: UUID, data: TaskAnalysisRequest) -> TaskAnalysis:
    try:
        await _task_in_scope(task_id)
        return await analysis_service.analyze_task(
            task_id=task_id,
            language=data.language,
            user_context=data.user_context,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dispatcher/datasets", response_model=list[EvaluationDatasetRead])
@authorize(privileges=list(DISPATCHER_PRIVILEGES))
async def read_dispatcher_datasets() -> list[EvaluationDatasetRead]:
    return await dispatcher_evaluation_service.list_datasets()


@router.post(
    "/dispatcher/datasets",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def create_dispatcher_dataset(
    data: EvaluationDatasetCreate,
) -> EvaluationDatasetRead:
    return await dispatcher_evaluation_service.create_dataset(data)


@router.patch("/dispatcher/datasets/{dataset_id}", response_model=EvaluationDatasetRead)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def update_dispatcher_dataset(
    dataset_id: UUID, data: EvaluationDatasetUpdate
) -> EvaluationDatasetRead:
    try:
        return await dispatcher_evaluation_service.update_dataset(dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/memory_extraction/prompt-default",
    response_model=MemoryExtractionPromptDefaultRead,
)
@authorize(privileges=list(MECHANISM_PRIVILEGES["memory_extraction"]))
async def read_memory_extraction_prompt_default() -> MemoryExtractionPromptDefaultRead:
    return await mechanism_evaluation_service.memory_extraction_prompt_default()


@router.get(
    "/planner/prompt-default",
    response_model=PlannerPromptDefaultRead,
)
@authorize(privileges=list(MECHANISM_PRIVILEGES["planner"]))
async def read_planner_prompt_default() -> PlannerPromptDefaultRead:
    return await mechanism_evaluation_service.planner_prompt_default()


@router.delete("/dispatcher/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def delete_dispatcher_dataset(dataset_id: UUID) -> None:
    if not await dispatcher_evaluation_service.delete_dataset(dataset_id):
        raise HTTPException(status_code=404, detail=await _detail("dataset_not_found"))


@router.get("/dispatcher/datasets/{dataset_id}/cases", response_model=list[EvaluationCaseRead])
@authorize(privileges=list(DISPATCHER_PRIVILEGES))
async def read_dispatcher_cases(dataset_id: UUID) -> list[EvaluationCaseRead]:
    try:
        return await dispatcher_evaluation_service.list_cases(dataset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/dispatcher/datasets/{dataset_id}/cases",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def create_dispatcher_case(
    dataset_id: UUID, data: EvaluationCaseCreate
) -> EvaluationCaseRead:
    try:
        return await dispatcher_evaluation_service.create_case(dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dispatcher/candidates", response_model=list[DispatcherTaskCandidate])
@authorize(privileges=list(DISPATCHER_PRIVILEGES))
async def read_dispatcher_candidates(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    search: Annotated[str | None, Query(max_length=300)] = None,
) -> list[DispatcherTaskCandidate]:
    scope = await current_management_scope()
    return await dispatcher_evaluation_service.list_task_candidates(
        limit=limit,
        search=search,
        agent_ids=scope.agent_ids,
    )


@router.post(
    "/dispatcher/datasets/{dataset_id}/cases/from-task",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def import_dispatcher_case(
    dataset_id: UUID, data: DispatcherCaseImport
) -> EvaluationCaseRead:
    try:
        await _task_in_scope(data.task_id)
        return await dispatcher_evaluation_service.import_task_case(dataset_id, data)
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/dispatcher/cases/{case_id}", response_model=EvaluationCaseRead)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def update_dispatcher_case(case_id: UUID, data: EvaluationCaseUpdate) -> EvaluationCaseRead:
    try:
        return await dispatcher_evaluation_service.update_case(case_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/dispatcher/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def delete_dispatcher_case(case_id: UUID) -> None:
    if not await dispatcher_evaluation_service.delete_case(case_id):
        raise HTTPException(status_code=404, detail=await _detail("case_not_found"))


@router.post(
    "/dispatcher/cases/{case_id}/duplicate",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def duplicate_dispatcher_case(case_id: UUID) -> EvaluationCaseRead:
    try:
        return await dispatcher_evaluation_service.duplicate_case(case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/dispatcher/cases/{case_id}/restore-source", response_model=EvaluationCaseRead)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def restore_dispatcher_case(
    case_id: UUID, data: CaptureRequest = Body(default_factory=CaptureRequest)
) -> EvaluationCaseRead:
    try:
        return await dispatcher_evaluation_service.restore_case_source(
            case_id, data.confirmation_token
        )
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/dispatcher/cases/{case_id}/generate-expected",
    response_model=EvaluationExpectedGenerated,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def generate_dispatcher_expected(
    case_id: UUID, data: EvaluationExpectedGenerate
) -> EvaluationExpectedGenerated:
    try:
        return await dispatcher_evaluation_service.generate_expected(case_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/dispatcher/datasets/{dataset_id}/runs",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def start_dispatcher_run(dataset_id: UUID, data: EvaluationRunStart) -> EvaluationRunRead:
    try:
        return await dispatcher_evaluation_service.start_run(dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dispatcher/datasets/{dataset_id}/runs", response_model=list[EvaluationRunRead])
@authorize(privileges=list(DISPATCHER_PRIVILEGES))
async def read_dispatcher_runs(
    dataset_id: UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[EvaluationRunRead]:
    try:
        return await dispatcher_evaluation_service.list_runs(dataset_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dispatcher/runs/{run_id}", response_model=EvaluationRunDetail)
@authorize(privileges=list(DISPATCHER_PRIVILEGES))
async def read_dispatcher_run(run_id: UUID) -> EvaluationRunDetail:
    run = await dispatcher_evaluation_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=await _detail("run_not_found"))
    return run


@router.post("/dispatcher/runs/{run_id}/analyze", response_model=EvaluationRunDetail)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def analyze_dispatcher_run(
    run_id: UUID, data: EvaluationRunAnalysisRequest
) -> EvaluationRunDetail:
    try:
        return await dispatcher_evaluation_service.analyze_run(run_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dispatcher/runs/{run_id}/cancel", response_model=EvaluationRunRead)
@authorize(privileges=Privileges.DISPATCHER_EVALUATION_EDIT)
async def cancel_dispatcher_run(run_id: UUID) -> EvaluationRunRead:
    try:
        return await dispatcher_evaluation_service.cancel_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/executor-prompts/defaults", response_model=ExecutorPromptDefaultsRead)
@authorize(
    privileges=[
        *MECHANISM_PRIVILEGES["task_executor"],
        *MECHANISM_PRIVILEGES["conversation_executor"],
        *MECHANISM_PRIVILEGES["voice_executor"],
    ]
)
async def read_executor_prompt_defaults() -> ExecutorPromptDefaultsRead:
    return await executor_prompt_service.read_defaults()


@router.get("/mechanisms", response_model=list[MechanismDescriptorRead])
@authorize(privileges=MECHANISM_READ_PRIVILEGES)
async def read_mechanisms() -> list[MechanismDescriptorRead]:
    return mechanism_evaluation_service.list_mechanisms()


@router.get(
    "/topic-classification/message-agents",
    response_model=list[TopicMessageAgentRead],
)
@authorize(privileges=list(MECHANISM_PRIVILEGES["topic_classification"]))
async def read_topic_message_agents() -> list[TopicMessageAgentRead]:
    scope = await current_management_scope()
    return await mechanism_evaluation_service.list_topic_message_agents(agent_ids=scope.agent_ids)


@router.get(
    "/topic-classification/message-people",
    response_model=list[TopicMessagePersonRead],
)
@authorize(privileges=list(MECHANISM_PRIVILEGES["topic_classification"]))
async def read_topic_message_people(
    agent_id: Annotated[int, Query(ge=1)],
) -> list[TopicMessagePersonRead]:
    scope = await current_management_scope()
    if not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return await mechanism_evaluation_service.list_topic_message_people(agent_id)


@router.get(
    "/topic-classification/message-preview",
    response_model=TopicMessageRangePreview,
)
@authorize(privileges=list(MECHANISM_PRIVILEGES["topic_classification"]))
async def preview_topic_messages(
    agent_id: Annotated[int, Query(ge=1)],
    connection_id: Annotated[int, Query(ge=1)],
    user_id: Annotated[str, Query(min_length=1, max_length=512)],
    date_from: datetime,
    date_to: datetime,
) -> TopicMessageRangePreview:
    try:
        scope = await current_management_scope()
        if not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return await mechanism_evaluation_service.preview_topic_message_range(
            TopicMessageRangeImport(
                agent_id=agent_id,
                connection_id=connection_id,
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/topic-classification/datasets/{dataset_id}/cases/from-message-range",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.TOPIC_CLASSIFICATION_EVALUATION_EDIT)
async def import_topic_messages(
    dataset_id: UUID,
    data: TopicMessageRangeImport,
) -> EvaluationCaseRead:
    try:
        return await mechanism_evaluation_service.import_topic_message_range(dataset_id, data)
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/topic-classification/datasets/{dataset_id}/configuration",
    response_model=EvaluationDatasetRead,
)
@authorize(privileges=Privileges.TOPIC_CLASSIFICATION_EVALUATION_EDIT)
async def update_topic_dataset_configuration(
    dataset_id: UUID,
    data: TopicDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    try:
        return await mechanism_evaluation_service.update_topic_dataset_configuration(
            dataset_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mechanism_evaluation_service.RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch(
    "/memory_extraction/datasets/{dataset_id}/configuration",
    response_model=EvaluationDatasetRead,
)
@authorize(privileges=Privileges.MEMORY_EXTRACTION_EVALUATION_EDIT)
async def update_memory_extraction_dataset_configuration(
    dataset_id: UUID,
    data: MemoryExtractionDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    try:
        return await mechanism_evaluation_service.update_memory_extraction_dataset_configuration(
            dataset_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mechanism_evaluation_service.RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch(
    "/planner/datasets/{dataset_id}/configuration",
    response_model=EvaluationDatasetRead,
)
@authorize(privileges=Privileges.PLANNER_EVALUATION_EDIT)
async def update_planner_dataset_configuration(
    dataset_id: UUID,
    data: PlannerDatasetConfigurationUpdate,
) -> EvaluationDatasetRead:
    try:
        return await mechanism_evaluation_service.update_planner_dataset_configuration(
            dataset_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mechanism_evaluation_service.RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{mechanism}/datasets", response_model=list[EvaluationDatasetRead])
@authorize(
    privileges=MECHANISM_READ_PRIVILEGES,
    assertion=LabMechanismReadPrivilegeAssertion,
)
async def read_mechanism_datasets(
    mechanism: EvaluationMechanism,
) -> list[EvaluationDatasetRead]:
    return await mechanism_evaluation_service.list_datasets(mechanism)


@router.post(
    "/{mechanism}/datasets",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def create_mechanism_dataset(
    mechanism: EvaluationMechanism, data: MechanismDatasetCreate
) -> EvaluationDatasetRead:
    return await mechanism_evaluation_service.create_dataset(mechanism, data)


@router.patch("/{mechanism}/datasets/{dataset_id}", response_model=EvaluationDatasetRead)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def update_mechanism_dataset(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationDatasetUpdate,
) -> EvaluationDatasetRead:
    try:
        return await mechanism_evaluation_service.update_dataset(mechanism, dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mechanism_evaluation_service.RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{mechanism}/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def delete_mechanism_dataset(mechanism: EvaluationMechanism, dataset_id: UUID) -> None:
    if not await mechanism_evaluation_service.delete_dataset(mechanism, dataset_id):
        raise HTTPException(status_code=404, detail=await _detail("dataset_not_found"))


@router.get(
    "/{mechanism}/datasets/{dataset_id}/cases",
    response_model=list[EvaluationCaseRead],
)
@authorize(
    privileges=MECHANISM_READ_PRIVILEGES,
    assertion=LabMechanismReadPrivilegeAssertion,
)
async def read_mechanism_cases(
    mechanism: EvaluationMechanism, dataset_id: UUID
) -> list[EvaluationCaseRead]:
    try:
        return await mechanism_evaluation_service.list_cases(mechanism, dataset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/datasets/{dataset_id}/cases",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def create_mechanism_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationCaseCreate,
) -> EvaluationCaseRead:
    try:
        return await mechanism_evaluation_service.create_case(mechanism, dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{mechanism}/candidates", response_model=list[MechanismSourceCandidate])
@authorize(
    privileges=MECHANISM_READ_PRIVILEGES,
    assertion=LabMechanismReadPrivilegeAssertion,
)
async def read_mechanism_candidates(
    mechanism: EvaluationMechanism,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    search: Annotated[str | None, Query(max_length=300)] = None,
) -> list[MechanismSourceCandidate]:
    scope = await current_management_scope()
    return await mechanism_evaluation_service.list_source_candidates(
        mechanism,
        search=search,
        limit=limit,
        agent_ids=scope.agent_ids,
    )


@router.post(
    "/{mechanism}/datasets/{dataset_id}/cases/from-source",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def import_mechanism_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: MechanismCaseImport,
) -> EvaluationCaseRead:
    try:
        scope = await current_management_scope()
        return await mechanism_evaluation_service.import_source_case(
            mechanism,
            dataset_id,
            data,
            agent_ids=scope.agent_ids,
        )
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/datasets/{dataset_id}/cases/from-task",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def import_mechanism_task_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: DispatcherCaseImport,
) -> EvaluationCaseRead:
    try:
        await _task_in_scope(data.task_id)
        return await mechanism_evaluation_service.import_task_case(mechanism, dataset_id, data)
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/datasets/{dataset_id}/cases/from-execution",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def import_executor_execution_case(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: ExecutorCaseImport,
) -> EvaluationCaseRead:
    try:
        scope = await current_management_scope()
        return await mechanism_evaluation_service.import_executor_case(
            mechanism,
            dataset_id,
            data,
            agent_ids=scope.agent_ids,
        )
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{mechanism}/cases/{case_id}", response_model=EvaluationCaseRead)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def update_mechanism_case(
    mechanism: EvaluationMechanism, case_id: UUID, data: MechanismCaseUpdate
) -> EvaluationCaseRead:
    try:
        return await mechanism_evaluation_service.update_case(mechanism, case_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mechanism_evaluation_service.RevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{mechanism}/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def delete_mechanism_case(mechanism: EvaluationMechanism, case_id: UUID) -> None:
    if not await mechanism_evaluation_service.delete_case(mechanism, case_id):
        raise HTTPException(status_code=404, detail=await _detail("case_not_found"))


@router.post(
    "/{mechanism}/cases/{case_id}/duplicate",
    response_model=EvaluationCaseRead,
    status_code=status.HTTP_201_CREATED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def duplicate_mechanism_case(
    mechanism: EvaluationMechanism, case_id: UUID
) -> EvaluationCaseRead:
    try:
        return await mechanism_evaluation_service.duplicate_case(mechanism, case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/cases/{case_id}/restore-source",
    response_model=EvaluationCaseRead,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def restore_mechanism_case(
    mechanism: EvaluationMechanism,
    case_id: UUID,
    data: CaptureRequest = Body(default_factory=CaptureRequest),
) -> EvaluationCaseRead:
    try:
        return await mechanism_evaluation_service.restore_case_source(
            mechanism, case_id, data.confirmation_token
        )
    except CaptureParametersMismatch as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/cases/{case_id}/generate-expected",
    response_model=MechanismExpectedGenerated,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def generate_mechanism_expected(
    mechanism: EvaluationMechanism,
    case_id: UUID,
    data: MechanismExpectedGenerate,
) -> MechanismExpectedGenerated:
    try:
        return await mechanism_evaluation_service.generate_expected(mechanism, case_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{mechanism}/datasets/{dataset_id}/runs",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def start_mechanism_run(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    data: EvaluationRunStart,
) -> EvaluationRunRead:
    try:
        return await mechanism_evaluation_service.start_run(mechanism, dataset_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{mechanism}/datasets/{dataset_id}/runs",
    response_model=list[EvaluationRunRead],
)
@authorize(
    privileges=MECHANISM_READ_PRIVILEGES,
    assertion=LabMechanismReadPrivilegeAssertion,
)
async def read_mechanism_runs(
    mechanism: EvaluationMechanism,
    dataset_id: UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[EvaluationRunRead]:
    try:
        return await mechanism_evaluation_service.list_runs(mechanism, dataset_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{mechanism}/runs/{run_id}", response_model=EvaluationRunDetail)
@authorize(
    privileges=MECHANISM_READ_PRIVILEGES,
    assertion=LabMechanismReadPrivilegeAssertion,
)
async def read_mechanism_run(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunDetail:
    run = await mechanism_evaluation_service.get_run(mechanism, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=await _detail("run_not_found"))
    return run


@router.delete("/{mechanism}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def delete_mechanism_run(mechanism: EvaluationMechanism, run_id: UUID) -> None:
    try:
        deleted = await mechanism_evaluation_service.delete_run(mechanism, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=await _detail("run_not_found"))


@router.post("/{mechanism}/runs/{run_id}/analyze", response_model=EvaluationRunDetail)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def analyze_mechanism_run(
    mechanism: EvaluationMechanism,
    run_id: UUID,
    data: EvaluationRunAnalysisRequest,
) -> EvaluationRunDetail:
    try:
        return await mechanism_evaluation_service.analyze_run(mechanism, run_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{mechanism}/runs/{run_id}/cancel", response_model=EvaluationRunRead)
@authorize(
    privileges=MECHANISM_EDIT_PRIVILEGES,
    assertion=LabMechanismEditPrivilegeAssertion,
)
async def cancel_mechanism_run(mechanism: EvaluationMechanism, run_id: UUID) -> EvaluationRunRead:
    try:
        return await mechanism_evaluation_service.cancel_run(mechanism, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
